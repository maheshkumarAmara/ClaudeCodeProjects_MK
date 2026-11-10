"""Go-Live Congrats — page.

Embeds assets/Go_Live_Congrats_UI.html (the form) in an iframe. When the user clicks Send via Claude, the form
posts a message to this page. The page checks it, shows the exact channels and message, and, once the user
confirms, opens Terminal with Claude Code already running /go-live-congrats. Posting to Slack is an outward step the
company's tool-validation policy makes a person approve, so the only thing left to do is approve it there. The page
then shows "Posted" by itself.

If the page can't be reached, the form falls back to copying the command, as it always did.
Nothing here posts to Slack or holds a Slack credential.
"""

import json
import shlex
import sys
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# theme.py, pov_page.py and golive_flow.py live in the project root, one level above pages/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import golive_flow as flow  # noqa: E402
from pov_page import find_claude, open_in_terminal  # noqa: E402
from theme import apply_theme  # noqa: E402

st.set_page_config(page_title="Go-Live Congrats · Rubrik", page_icon="🎉", layout="wide")
apply_theme("golive")

HTML_PATH = Path(__file__).parent.parent / "assets" / "Go_Live_Congrats_UI.html"
GIVE_UP_SECONDS = 15 * 60
POLL_SECONDS = 4

# Receives the form's message in the page and hands it to Python. components.html cannot name its iframe, so the
# listener accepts a message only if it came from an iframe that is part of THIS page (event.source is that
# iframe's window), has the one message type the form sends, and carries an object payload. A message from
# another tab, another site or a popup is ignored. Python then validates every field again (clean_payload).
LISTENER_JS = """
export default function(component) {
  const { setTriggerValue } = component;
  if (window.__goliveListener) { window.removeEventListener('message', window.__goliveListener); }
  window.__goliveListener = function (event) {
    const data = event.data;
    if (!data || data.type !== 'golive-congrats' || data.payload === null || typeof data.payload !== 'object') { return; }
    const fromThisPage = Array.from(document.querySelectorAll('iframe'))
      .some(function (f) { return f.contentWindow === event.source; });
    if (!fromThisPage) { return; }
    // Tell the form the page has it, so the form does not also copy the command to the clipboard.
    try { event.source.postMessage({ type: 'golive-congrats-ack' }, '*'); } catch (e) { /* ignore */ }
    setTriggerValue('payload', JSON.stringify(data.payload));
  };
  window.addEventListener('message', window.__goliveListener);
}
"""
listener = st.components.v2.component("golive_listener", js=LISTENER_JS)


def _write_launcher(run: dict, claude: str) -> Path:
    path = run["dir"] / "run.command"
    path.write_text(
        "#!/bin/bash\n"
        f"cd {shlex.quote(str(flow.REPO_ROOT))} || exit 1\n"
        f"exec {shlex.quote(claude)} {shlex.quote(run['command'])}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


state = st.session_state
state.setdefault("golive_pending", None)   # a validated message waiting for the user's confirmation
state.setdefault("golive_run", None)       # the run that was started
state.setdefault("golive_error", None)
flow.purge_old_runs()

# ── the form ─────────────────────────────────────────────────────────────────
if not HTML_PATH.exists():
    st.error(f"Tool file not found at {HTML_PATH}")
    st.stop()
form_html = HTML_PATH.read_text(encoding="utf-8")
# The form fills the window; the confirm/progress section below it is normal padded content. Each gets its own
# keyed container (CSS class st-key-<key>) so the full-window iframe rule in theme.py applies to the form only.
with st.container(key="golive_form"):
    components.html(form_html, height=900, scrolling=True)

# ── the bridge ───────────────────────────────────────────────────────────────
message = listener(key="golive_bridge", on_payload_change=lambda: None)
incoming = getattr(message, "payload", None) if message is not None else None
if incoming and incoming != state.get("golive_last_message"):
    state["golive_last_message"] = incoming
    state["golive_error"], state["golive_run"] = None, None
    try:
        state["golive_pending"] = flow.clean_payload(json.loads(incoming))
    except (flow.PayloadError, json.JSONDecodeError) as exc:
        state["golive_pending"], state["golive_error"] = None, str(exc)

# ── confirm / progress / result ──────────────────────────────────────────────
# Everything below renders inside the "golive_panel" container (opened here, left open to the end of the script),
# which theme.py styles as normal padded content under the full-window form.
_panel = st.container(key="golive_panel")
_panel.__enter__()

if state["golive_error"]:
    st.error(state["golive_error"])

pending, run = state["golive_pending"], state["golive_run"]

if pending and run is None:
    st.subheader("Ready to post this message")
    st.markdown("**Channels:** " + ", ".join(f"#{c}" for c in pending["channels"]))
    with st.expander("Preview the message (Slack formatting shown as typed)", expanded=True):
        st.text(pending["message"])
    claude_bin = find_claude()
    if claude_bin is None:
        st.error("The `claude` CLI was not found. Use the copied command in the form instead.")
    else:
        st.caption("Opens Terminal with Claude Code running /go-live-congrats. Your only step there is approving "
                   "the Slack post (your company's policy requires a person to).")
        go, cancel = st.columns(2)
        if go.button("Confirm and post", type="primary", key="golive_confirm"):
            new_run = flow.prepare_run(pending)
            error = open_in_terminal(_write_launcher(new_run, claude_bin))
            if error:
                state["golive_error"] = error
            else:
                new_run["launched"] = True
                state["golive_run"] = new_run
            st.rerun()
        if cancel.button("Cancel", key="golive_cancel"):
            state["golive_pending"] = None
            st.rerun()

elif run is not None:
    @st.fragment(run_every=None if run.get("finished") else POLL_SECONDS)
    def watch() -> None:
        result = flow.read_result(run)
        elapsed = int(time.time() - run["started"])
        if result:
            first_time = not run.get("finished")
            run["finished"] = True
            where = ", ".join(f"#{c}" for c in (result["channels"] or run["channels"]))
            if result["status"] == "posted":
                st.success(f"Posted to {where}.")
            else:
                st.error(f"The post did not complete{': ' + result['error'] if result['error'] else '.'} "
                         "Check the Terminal window and your Slack channel.")
            if first_time:
                st.rerun()  # one full rerun so polling stops; guarded by first_time so it can never loop
        elif elapsed >= GIVE_UP_SECONDS:
            run["finished"] = True
            st.warning("No confirmation after 15 minutes. Check the Terminal window and the Slack channel; "
                       "the message may still have been posted.")
        else:
            st.info(f"Waiting for Claude Code… {elapsed // 60}m {elapsed % 60:02d}s. "
                    "Approve the Slack post in the Terminal window.")
    watch()
    with st.expander("Run it yourself instead"):
        st.markdown("Open Claude Code in this project folder, paste this command and press Enter:")
        st.code(run["command"], language="text")
    if st.button("Post another message", key="golive_another"):
        state["golive_pending"], state["golive_run"], state["golive_error"] = None, None, None
        st.rerun()
