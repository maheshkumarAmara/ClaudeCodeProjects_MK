"""Marketplace Email Automation — page.

Embeds assets/Marketplace_Email_UI.html (the form) in an iframe. When the user clicks Send Email or Create draft,
the form posts a message to this page. The page checks it, renders the real email with the existing render
script (plain Python), shows the exact To / CC / Subject / body, and, once the user confirms:

  * Send:  opens Terminal with Claude Code already running /MarketPlaceAutomation. Sending mail is the one step
           the company's tool-validation policy makes a person approve, so the only thing left to do is click
           Approve there. The page then shows "Sent" by itself.
  * Draft: runs Claude Code in the background to create a Gmail draft (draft creation is allowed without a
           prompt) and shows the result; the user presses Send in Gmail.

The old "copy the command and paste it into Claude" dialog in the form is kept as a fallback.
Nothing here sends mail by itself or holds any Gmail credential.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# theme.py, pov_page.py and marketplace_flow.py live in the project root, one level above pages/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import marketplace_flow as flow  # noqa: E402
from pov_page import find_claude, open_in_terminal  # noqa: E402
from theme import apply_theme  # noqa: E402

st.set_page_config(page_title="Marketplace Email Automation · Rubrik", page_icon="✉️", layout="wide")
apply_theme("marketplace")

HTML_PATH = Path(__file__).parent.parent / "assets" / "Marketplace_Email_UI.html"
GIVE_UP_SECONDS = 15 * 60
POLL_SECONDS = 4
DRAFT_BUDGET_USD = os.environ.get("MARKETPLACE_DRAFT_BUDGET_USD", "0.75")

# Receives the form's message in the page and hands it to Python. components.html cannot name its iframe, so the
# listener accepts a message only if it came from an iframe that is part of THIS page (event.source is that
# iframe's window), has the one message type the form sends, and carries an object payload. A message from
# another tab, another site or a popup is ignored. Python then validates every field again (clean_payload).
LISTENER_JS = """
export default function(component) {
  const { setTriggerValue } = component;
  if (window.__marketplaceListener) { window.removeEventListener('message', window.__marketplaceListener); }
  window.__marketplaceListener = function (event) {
    const data = event.data;
    if (!data || data.type !== 'marketplace-email' || data.payload === null || typeof data.payload !== 'object') { return; }
    const fromThisPage = Array.from(document.querySelectorAll('iframe'))
      .some(function (f) { return f.contentWindow === event.source; });
    if (!fromThisPage) { return; }
    // Tell the form the page has it, so the form does not also show its copy-the-command fallback.
    try { event.source.postMessage({ type: 'marketplace-email-ack' }, '*'); } catch (e) { /* ignore */ }
    setTriggerValue('payload', JSON.stringify(data.payload));
  };
  window.addEventListener('message', window.__marketplaceListener);
}
"""
listener = st.components.v2.component("marketplace_listener", js=LISTENER_JS)


def _draft_command(claude: str, run: dict) -> list[str]:
    """Headless Claude Code run that may only read the run files, write the result file and create a draft."""
    return [
        claude, "-p", run["prompt"],
        "--output-format", "json", "--no-session-persistence",
        "--permission-mode", "dontAsk", "--setting-sources", "project",
        "--max-budget-usd", str(DRAFT_BUDGET_USD), "--max-turns", "8",
        "--add-dir", str(run["dir"]),
        "--mcp-config", str(run["dir"] / "gmail_mcp.json"), "--strict-mcp-config",
        "--allowedTools", "Read,Write,mcp__gmail__draft_email",
        "--disallowedTools", "mcp__gmail__send_email,WebFetch,WebSearch,Bash",
    ]


def _write_gmail_mcp_config(run_dir: Path) -> bool:
    """A config with only the Gmail server, copied from the user's own Claude setup (never into the repo)."""
    try:
        server = json.loads((Path.home() / ".claude.json").read_text(encoding="utf-8"))["mcpServers"]["gmail"]
    except (OSError, KeyError, ValueError):
        return False
    path = run_dir / "gmail_mcp.json"
    path.write_text(json.dumps({"mcpServers": {"gmail": server}}), encoding="utf-8")
    path.chmod(0o600)
    return True


def _write_launcher(run: dict, claude: str) -> Path:
    import shlex
    path = run["dir"] / "run.command"
    path.write_text(
        "#!/bin/bash\n"
        f"cd {shlex.quote(str(flow.REPO_ROOT))} || exit 1\n"
        f"exec {shlex.quote(claude)} {shlex.quote(run['prompt'])}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


state = st.session_state
state.setdefault("mkt_pending", None)   # a validated, rendered email waiting for the user's confirmation
state.setdefault("mkt_run", None)       # the run that was started
state.setdefault("mkt_error", None)
flow.purge_old_runs()

# ── the form ─────────────────────────────────────────────────────────────────
if not HTML_PATH.exists():
    st.error(f"Tool file not found at {HTML_PATH}")
    st.stop()
form_html = HTML_PATH.read_text(encoding="utf-8")
# The form fills the window; the confirm/progress section below it is normal padded content. Each gets its own
# keyed container (CSS class st-key-<key>) so the full-window iframe rule in theme.py applies to the form only.
with st.container(key="mkt_form"):
    components.html(form_html, height=900, scrolling=True)

# ── the bridge ───────────────────────────────────────────────────────────────
message = listener(key="marketplace_bridge", on_payload_change=lambda: None)
incoming = getattr(message, "payload", None) if message is not None else None
if incoming and incoming != state.get("mkt_last_message"):
    state["mkt_last_message"] = incoming
    state["mkt_error"], state["mkt_run"] = None, None
    try:
        payload = flow.clean_payload(json.loads(incoming))
        rendered = flow.render_email(payload)
        state["mkt_pending"] = {"payload": payload, "rendered": rendered}
    except (flow.PayloadError, RuntimeError, json.JSONDecodeError) as exc:
        state["mkt_pending"], state["mkt_error"] = None, str(exc)

# ── confirm / progress / result ──────────────────────────────────────────────
# Everything below renders inside the "mkt_panel" container (opened here, left open to the end of the script),
# which theme.py styles as normal padded content under the full-window form.
_panel = st.container(key="mkt_panel")
_panel.__enter__()

if state["mkt_error"]:
    st.error(state["mkt_error"])

pending, run = state["mkt_pending"], state["mkt_run"]

if pending and run is None:
    payload, rendered = pending["payload"], pending["rendered"]
    verb = "send" if payload["mode"] == "send" else "create a draft of"
    st.subheader(f"Ready to {verb} this email")
    st.markdown(
        f"**To:** {payload['to']}  \n"
        f"**CC:** {', '.join(payload['cc']) or '—'}  \n"
        f"**Subject:** {rendered['subject']}"
    )
    with st.expander("Preview the email", expanded=True):
        components.html(rendered["html"], height=420, scrolling=True)
    claude_bin = find_claude()
    if claude_bin is None:
        st.error("The `claude` CLI was not found. Use Copy Command in the form instead.")
    else:
        if payload["mode"] == "send":
            st.caption("Opens Terminal with Claude Code running /MarketPlaceAutomation. Your only step there is "
                       "approving the Gmail send (your company's policy requires a person to).")
        else:
            st.caption("Creates a draft in your Gmail in the background; nothing is sent. Press Send in Gmail yourself.")
        go, cancel = st.columns(2)
        if go.button("Confirm and send" if payload["mode"] == "send" else "Confirm and create draft", type="primary"):
            run = flow.prepare_run(payload, rendered)
            if payload["mode"] == "send":
                error = open_in_terminal(_write_launcher(run, claude_bin))
                if error:
                    state["mkt_error"] = error
                else:
                    run["launched"] = True
                    state["mkt_run"] = run
            else:
                if not _write_gmail_mcp_config(run["dir"]):
                    state["mkt_error"] = "Gmail is not set up in your Claude config, so a draft can't be created from here."
                else:
                    with open(run["dir"] / "draft.log", "w", encoding="utf-8") as log:
                        run["proc"] = subprocess.Popen(_draft_command(claude_bin, run), cwd=str(flow.REPO_ROOT),
                                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True, text=True)
                    state["mkt_run"] = run
            st.rerun()
        if cancel.button("Cancel"):
            state["mkt_pending"] = None
            st.rerun()

elif run is not None:
    @st.fragment(run_every=None if run.get("finished") else POLL_SECONDS)
    def watch() -> None:
        result = flow.read_result(run)
        elapsed = int(time.time() - run["started"])
        proc = run.get("proc")
        if result:
            first_time = not run.get("finished")
            run["finished"] = True
            word = "Sent" if result["status"] == "sent" else "Draft created"
            st.success(f"{word}: {run['subject']} → {run['to']}")
            if result["status"] == "drafted":
                st.caption("Open Gmail, check the draft and press Send.")
            if first_time:
                st.rerun()
        elif proc is not None and proc.poll() is not None:
            run["finished"] = True
            tail = (run["dir"] / "draft.log").read_text(encoding="utf-8", errors="replace")[-600:] if (run["dir"] / "draft.log").exists() else ""
            st.error("The draft run ended without confirming a draft. Nothing was sent. "
                     "If the Gmail tool was refused, use Send instead.")
            if tail:
                st.code(tail, language="text")
        elif elapsed >= GIVE_UP_SECONDS:
            run["finished"] = True
            st.warning("No confirmation after 15 minutes. Check the Terminal window and your Gmail Sent or Drafts folder; "
                       "the email may still have gone out.")
        elif run["mode"] == "send":
            st.info(f"Waiting for Claude Code… {elapsed // 60}m {elapsed % 60:02d}s. Approve the Gmail send in the Terminal window.")
        else:
            st.info(f"Creating the draft… {elapsed}s")
    watch()
    if st.button("Start another email"):
        state["mkt_pending"], state["mkt_run"], state["mkt_error"] = None, None, None
        st.rerun()
