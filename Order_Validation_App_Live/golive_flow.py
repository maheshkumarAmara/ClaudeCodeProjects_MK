"""Logic for the Go-Live Congrats page, kept free of Streamlit so it can be tested on its own.

The form (assets/Go_Live_Congrats_UI.html) posts a message to the page when the user clicks Send via Claude. This
module checks that message and prepares the Claude Code run that posts it to Slack. Posting to Slack is an outward
step the company's tool-validation policy makes a person approve, so the run happens in Claude Code, where it can be.

Nothing here talks to Slack.
"""

import base64
import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "claude_outputs" / "golive_runs"
KEEP_RUNS_DAYS = 7

MAX_CHANNELS = 5
MAX_MESSAGE_CHARS = 4_000     # Slack truncates long messages; the form's message is well under this
MAX_B64_CHARS = 20_000
_CHANNEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_B64 = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")


class PayloadError(ValueError):
    """The message from the form is not something to act on. The text is safe to show the user."""


def _channels(value) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        raise PayloadError("Channels must be a list or comma-separated text.")
    channels = []
    for item in value:
        if not isinstance(item, str):
            raise PayloadError("Each channel must be text.")
        name = item.strip().lstrip("#")
        if not name:
            continue
        if not _CHANNEL.match(name):
            raise PayloadError(f"Not a valid Slack channel name or ID: {item.strip()[:40]!r}.")
        if name not in channels:
            channels.append(name)
    if not channels:
        raise PayloadError("Enter at least one Slack channel.")
    if len(channels) > MAX_CHANNELS:
        raise PayloadError(f"At most {MAX_CHANNELS} channels at a time.")
    return channels


def clean_payload(raw) -> dict:
    """Checks the message the form posted and returns {"channels", "message", "b64"} (or raises PayloadError).

    The message comes from the browser, so every field is checked and only the known keys are kept. The message
    must be base64 that decodes to plain text; the base64 form is what goes on the command line, so nothing the
    user typed ever reaches a shell unquoted.
    """
    if not isinstance(raw, dict):
        raise PayloadError("The form sent an unexpected message.")
    channels = _channels(raw.get("channel"))
    b64 = raw.get("message")
    if not isinstance(b64, str) or not b64.strip():
        raise PayloadError("Generate a preview first: there is no message to post.")
    b64 = b64.strip()
    if len(b64) > MAX_B64_CHARS or not _B64.match(b64):
        raise PayloadError("The message is not valid base64, or is too long.")
    try:
        message = base64.b64decode(b64, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise PayloadError(f"The message could not be read: {exc}") from exc
    message = message.replace("\x00", "").strip()
    if not message:
        raise PayloadError("The message is empty.")
    if len(message) > MAX_MESSAGE_CHARS:
        raise PayloadError(f"The message is longer than {MAX_MESSAGE_CHARS:,} characters.")
    return {"channels": channels, "message": message, "b64": b64}


def build_command(payload: dict, result_path: Path | None = None) -> str:
    """The /go-live-congrats fast-mode line, plus where to write the result."""
    command = f'/go-live-congrats --channel "{",".join(payload["channels"])}" --message "{payload["b64"]}"'
    if result_path is not None:
        command += (f"\nWhen finished, write {result_path} as JSON with status \"posted\" and channels "
                    f"(the list of channels it was posted to). If any post failed, use status \"failed\" "
                    f"and an error string.")
    return command


def prepare_run(payload: dict, now: datetime | None = None) -> dict:
    """Saves the message in a new run folder and returns the run record."""
    now = now or datetime.now()
    run_dir = RUNS_DIR / now.strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "message.txt").write_text(payload["message"], encoding="utf-8")
    result_path = run_dir / "result.json"
    return {"dir": run_dir, "channels": payload["channels"], "result_path": result_path,
            "started": time.time(), "command": build_command(payload, result_path)}


def read_result(run: dict) -> dict | None:
    """The result file Claude Code wrote, or None if it is not there yet or not readable."""
    try:
        data = json.loads(Path(run["result_path"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("status") not in ("posted", "failed"):
        return None
    channels = data.get("channels")
    error = data.get("error")
    return {"status": data["status"],
            "channels": [c for c in channels if isinstance(c, str)][:MAX_CHANNELS] if isinstance(channels, list) else [],
            "error": error[:300] if isinstance(error, str) else None}


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
