"""Logic for the Test Case Review page, kept free of Streamlit so it can be tested on its own.

The page collects a Jira key or URL (and, optionally, pasted story / test-case text), then opens Terminal with
Claude Code already running /test-case-review. The skill creates a Google Doc, posts a Jira comment and posts to
Slack; those steps need a person's approval under the company's tool-validation policy, so the run happens in
Claude Code, where they can be approved. The skill is asked to write a small result file that the page polls.

Nothing here talks to Jira, Google, or Slack.
"""

import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = "test-case-review"
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / SKILL
SKILL_FILE = SKILL_DIR / "SKILL.md"
CONFIG_FILE = SKILL_DIR / "config.txt"
RUNS_DIR = REPO_ROOT / "claude_outputs" / "tcr_runs"
KEEP_RUNS_DAYS = 7

JIRA_HOST = os.environ.get("TCR_JIRA_HOST", "rubrik.atlassian.net").lower()
MAX_TEXT_CHARS = 50_000
_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{1,7}$")
_KEY_IN_PATH = re.compile(r"/browse/([A-Za-z][A-Za-z0-9]{1,9}-\d{1,7})(?:[/?#]|$)")
VERDICTS = ("GO", "CONDITIONAL GO", "NO-GO")


class InputError(ValueError):
    """The input is not something to act on. The text is safe to show the user."""


def parse_ticket(raw) -> str:
    """A Jira key (PRDOPS-722) from a key or a browse URL on the configured Jira host, else InputError."""
    if not isinstance(raw, str):
        raise InputError("Enter a Jira key or URL.")
    value = raw.strip()
    if not value:
        raise InputError("Enter a Jira key or URL.")
    if any(ch in value for ch in "\r\n\x00"):
        raise InputError("The Jira key or URL must be a single line.")
    if _KEY.match(value.upper()) and "/" not in value:
        return value.upper()
    parsed = urlparse(value)
    if parsed.scheme == "https" and (parsed.hostname or "").lower() == JIRA_HOST:
        match = _KEY_IN_PATH.search(parsed.path + "/")
        if match:
            return match.group(1).upper()
        selected = re.search(r"selectedIssue=([A-Za-z][A-Za-z0-9]{1,9}-\d{1,7})", parsed.query)
        if selected:
            return selected.group(1).upper()
    raise InputError(f"Not a Jira key like PRDOPS-722 or a https://{JIRA_HOST}/browse/... link: {value[:80]!r}.")


def clean_text(raw) -> str:
    """Pasted story / test-case text: trimmed, capped, no NUL bytes. Empty string if nothing was pasted."""
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise InputError("The pasted text must be text.")
    text = raw.replace("\x00", "").strip()
    if len(text) > MAX_TEXT_CHARS:
        raise InputError(f"The pasted text is longer than {MAX_TEXT_CHARS:,} characters.")
    return text


def clean_input(ticket, pasted=None) -> dict:
    """A fixed-shape dict: {"ticket": key or None, "text": pasted text}. At least one must be given."""
    text = clean_text(pasted)
    ticket_raw = ticket.strip() if isinstance(ticket, str) else ticket
    key = parse_ticket(ticket_raw) if ticket_raw else None
    if key is None and not text:
        raise InputError("Enter a Jira key or URL, or paste a story or test cases.")
    return {"ticket": key, "text": text}


def config_defaults(config_file: Path | None = None) -> dict:
    """POST_JIRA_COMMENT / POST_SLACK_NOTIFICATION as set in the skill's config.txt (true when missing)."""
    defaults = {"POST_JIRA_COMMENT": True, "POST_SLACK_NOTIFICATION": True}
    try:
        lines = (config_file or CONFIG_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return defaults
    for line in lines:
        name, sep, value = line.strip().partition("=")
        if sep and name in defaults and not line.lstrip().startswith("#"):
            defaults[name] = value.strip().lower() != "false"
    return defaults


def build_command(run_input: dict, post_jira: bool, post_slack: bool, text_path: Path | None = None,
                  result_path: Path | None = None) -> str:
    """The /test-case-review prompt: the input, a one-run override line, and where to write the result."""
    if run_input["ticket"]:
        command = f"/{SKILL} {run_input['ticket']}"
        if text_path is not None:
            command += f"\nAlso use the extra context pasted in {text_path}."
    else:
        command = f"/{SKILL} Review the story / test cases pasted in {text_path}."
    command += (f"\nOverrides for this run (they beat config.txt): "
                f"POST_JIRA_COMMENT={'true' if post_jira else 'false'}, "
                f"POST_SLACK_NOTIFICATION={'true' if post_slack else 'false'}.")
    if result_path is not None:
        command += (f"\nWhen finished, write {result_path} as JSON with status \"done\", doc_url (the Google Doc link), "
                    f"verdict (GO, CONDITIONAL GO or NO-GO) and coverage (the Coverage Score as a whole number).")
    return command


def prepare_run(run_input: dict, post_jira: bool, post_slack: bool, now: datetime | None = None) -> dict:
    """Saves any pasted text in a new run folder and returns the run record."""
    now = now or datetime.now()
    run_dir = RUNS_DIR / now.strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    text_path = None
    if run_input["text"]:
        text_path = run_dir / "pasted.txt"
        text_path.write_text(run_input["text"], encoding="utf-8")
    result_path = run_dir / "result.json"
    return {"dir": run_dir, "ticket": run_input["ticket"], "result_path": result_path, "started": time.time(),
            "post_jira": post_jira, "post_slack": post_slack,
            "command": build_command(run_input, post_jira, post_slack, text_path, result_path)}


def read_result(run: dict) -> dict | None:
    """The result file Claude Code wrote, or None if it is not there yet or not readable.

    Only a Google Docs link is accepted as doc_url, so the page never shows an arbitrary link.
    """
    try:
        data = json.loads(Path(run["result_path"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("status") != "done":
        return None
    url = data.get("doc_url")
    parsed = urlparse(url) if isinstance(url, str) else None
    doc_url = url if parsed and parsed.scheme == "https" and parsed.hostname == "docs.google.com" else None
    verdict = data.get("verdict")
    coverage = data.get("coverage")
    return {"doc_url": doc_url,
            "verdict": verdict if verdict in VERDICTS else None,
            "coverage": coverage if isinstance(coverage, int) and not isinstance(coverage, bool) else None}


def purge_old_runs(days: int = KEEP_RUNS_DAYS, runs_dir: Path | None = None) -> None:
    """Best-effort removal of run folders older than `days`."""
    runs_dir = runs_dir or RUNS_DIR
    if not runs_dir.exists():
        return
    cutoff = time.time() - days * 86400
    for folder in runs_dir.iterdir():
        try:
            if folder.is_dir() and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass
