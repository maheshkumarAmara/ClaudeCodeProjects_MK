"""Test Case Review — runs the /test-case-review skill.

Enter a Jira story key or URL (and, optionally, paste a story or test cases). On confirm the page opens Terminal
with Claude Code already running /test-case-review. The skill reads the story and its test case subtasks, builds
a Google Doc with the coverage gaps and a Go / No-Go verdict, and (if ticked) comments on the Jira subtask and
posts to Slack. Those steps need a person's approval under the company's tool-validation policy, so the only
thing to do in Terminal is approve them. The page then shows the Google Doc link by itself.

All the logic is in tcr_flow.py. Nothing here holds a Jira, Google or Slack credential.
"""

import shlex
import shutil
import sys
import time
from pathlib import Path

import streamlit as st

# theme.py, pov_page.py and tcr_flow.py live in the project root, one level above pages/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tcr_flow as flow  # noqa: E402
from pov_page import find_claude, open_in_terminal  # noqa: E402
from theme import apply_theme  # noqa: E402

st.set_page_config(page_title="Test Case Review · Rubrik", page_icon="🧪", layout="wide")
apply_theme("tcr")

POLL_SECONDS = 5
GIVE_UP_SECONDS = 30 * 60
KEY = "tcr"


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


def _launch(run: dict) -> str | None:
    """Opens Terminal with Claude Code running the review. Returns an error message, or None on success."""
    claude = find_claude()
    if claude is None:
        return "The `claude` CLI was not found, so Terminal can't be opened from here. Use the manual command below."
    # Removed first so only a result written by this launch counts.
    run["result_path"].unlink(missing_ok=True)
    error = open_in_terminal(_write_launcher(run, claude))
    if error:
        return error
    run.update(launched=True, started=time.time(), finished=False)
    return None


state = st.session_state
state.setdefault(f"{KEY}_run", None)
state.setdefault(f"{KEY}_error", None)
flow.purge_old_runs()

st.title("Test Case Review")
st.caption("Review the test cases for a Jira story against its acceptance criteria, find the gaps and get a "
           "Go / No-Go verdict in a Google Doc, using the /test-case-review skill.")
if not flow.SKILL_FILE.exists():
    st.error(f"The /{flow.SKILL} skill is missing at `{flow.SKILL_FILE}`.")

run = state[f"{KEY}_run"]

if run is None:
    defaults = flow.config_defaults()
    ticket = st.text_input("Jira story key or URL", placeholder="PRDOPS-722 or https://rubrik.atlassian.net/browse/PRDOPS-722",
                           key=f"{KEY}_ticket")
    with st.expander("Or paste a story or test cases (optional)"):
        pasted = st.text_area("Pasted text", height=180, key=f"{KEY}_pasted", label_visibility="collapsed",
                              help="With a Jira key, this is extra context. Without one, it is reviewed on its own.")
    post_jira = st.checkbox("Post a comment on the test case subtask in Jira", value=defaults["POST_JIRA_COMMENT"],
                            key=f"{KEY}_jira",
                            help="Needs jira-dashboard/.env with your Jira API token (see the skill's README).")
    post_slack = st.checkbox("Post a summary to Slack", value=defaults["POST_SLACK_NOTIFICATION"], key=f"{KEY}_slack",
                             help="Goes to the channel set in the skill's config.txt.")
    st.caption("Both default to the skill's config.txt. Untick to review without notifying anyone.")

    st.caption("Start review opens Terminal with Claude Code already running /test-case-review. Your only step there "
               "is approving its prompts (Jira and Drive reads, the Google Doc, and the Jira / Slack posts if ticked). "
               "This page then shows the Google Doc link by itself.")
    if st.button("Start review", type="primary", key=f"{KEY}_start", disabled=not (ticket.strip() or pasted.strip())):
        try:
            run_input = flow.clean_input(ticket, pasted)
        except flow.InputError as exc:
            st.error(str(exc))
        else:
            new_run = flow.prepare_run(run_input, post_jira, post_slack)
            # Launched once, here in the click handler; later reruns of the page never launch again.
            state[f"{KEY}_error"] = _launch(new_run)
            state[f"{KEY}_run"] = new_run
            st.rerun()
else:
    launched = run.get("launched", False)
    subject = run["ticket"] or "pasted text"

    st.subheader(f"Review: {subject}")
    st.markdown(
        f"**Jira comment:** {'will be posted' if run['post_jira'] else 'skipped'}  \n"
        f"**Slack summary:** {'will be posted' if run['post_slack'] else 'skipped'}"
    )
    if state[f"{KEY}_error"]:
        st.error(state[f"{KEY}_error"])
    if st.button("Open again in Claude Code" if launched else "Try opening Claude Code again",
                 type="secondary" if launched else "primary", key=f"{KEY}_open"):
        state[f"{KEY}_error"] = _launch(run)
        st.rerun()

    if launched:
        @st.fragment(run_every=None if run.get("finished") else POLL_SECONDS)
        def watch() -> None:
            result = flow.read_result(run)
            elapsed = int(time.time() - run["started"])
            if result:
                first_time = not run.get("finished")
                run["finished"] = True
                st.success("Review finished.")
                cols = st.columns(3)
                cols[0].metric("Verdict", result["verdict"] or "—")
                cols[1].metric("Coverage score", f"{result['coverage']}%" if result["coverage"] is not None else "—")
                if result["doc_url"]:
                    cols[2].link_button("Open Google Doc", result["doc_url"], key=f"{KEY}_doc")
                else:
                    st.caption("No Google Doc link was saved. Check the Terminal window.")
                if first_time:
                    st.rerun()  # one full rerun so polling stops; guarded by first_time so it can never loop
            elif elapsed >= GIVE_UP_SECONDS:
                first_time = not run.get("finished")
                run["finished"] = True
                st.warning("No result after 30 minutes. Check the Terminal window; the review may still have finished.")
                if first_time:
                    st.rerun()
            else:
                st.info(f"Waiting for Claude Code… {elapsed // 60}m {elapsed % 60:02d}s. "
                        "Approve the prompts in the Terminal window.")
        watch()

    with st.expander("Run it yourself instead", expanded=not launched):
        st.markdown("Open Claude Code in this project folder, paste this command and press Enter:")
        st.code(run["command"], language="text")

    again, delete = st.columns(2)
    if again.button("Start another review", key=f"{KEY}_another"):
        state[f"{KEY}_run"], state[f"{KEY}_error"] = None, None
        st.rerun()
    if delete.button("Delete prepared files", key=f"{KEY}_delete"):
        shutil.rmtree(run["dir"], ignore_errors=True)
        state[f"{KEY}_run"], state[f"{KEY}_error"] = None, None
        st.rerun()

st.caption("The review is written by a model running in Claude Code under your company's tool-validation policy. "
           "Check the Google Doc before acting on the verdict.")
