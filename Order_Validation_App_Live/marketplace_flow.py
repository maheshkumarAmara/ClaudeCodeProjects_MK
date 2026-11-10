"""Logic for the Marketplace Email page, kept free of Streamlit so it can be tested on its own.

The form (assets/Marketplace_Email_UI.html) posts a message to the page when the user clicks Send Email or
Create draft. This module checks that message, renders the real email with the existing render script (plain
Python, no model), and prepares the Claude Code run that does the Gmail step. Sending an email is the one step
the company's tool-validation policy makes a person approve, so the run happens in Claude Code, where it can be.

Nothing here sends mail or talks to Gmail.
"""

import base64
import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDER_SCRIPT = REPO_ROOT / ".claude" / "commands" / "render_marketplace_email.py"
RUNS_DIR = REPO_ROOT / "claude_outputs" / "marketplace_runs"
KEEP_RUNS_DAYS = 7
VENV_PYTHON = Path.home() / "venv" / "bin" / "python"

PROVIDERS = ("AWS", "AWS_Partner", "GCP_Direct", "GCP_Partner", "Azure", "Azure_Partner")
MODES = ("send", "draft")
MAX_DATA_CHARS = 20_000        # the base64 form data is a few hundred characters; this is generous
MAX_FIELD_CHARS = 500
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-']+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_QUOTE = re.compile(r"^Q-?\d{3,9}$", re.IGNORECASE)
_B64 = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")


class PayloadError(ValueError):
    """The message from the form is not something to act on. The text is safe to show the user."""


def _text(value, name: str, required: bool = True, limit: int = MAX_FIELD_CHARS) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise PayloadError(f"{name} must be text.")
    value = value.strip()
    if required and not value:
        raise PayloadError(f"{name} is required.")
    if len(value) > limit:
        raise PayloadError(f"{name} is too long.")
    if any(ch in value for ch in "\r\n\x00"):
        raise PayloadError(f"{name} must be a single line.")
    return value


def _email(value, name: str) -> str:
    value = _text(value, name)
    if not _EMAIL.match(value):
        raise PayloadError(f"{name} is not a valid email address: {value!r}.")
    return value


def clean_payload(raw) -> dict:
    """Checks the message the form posted and returns a clean, fixed-shape dict (or raises PayloadError).

    The message comes from the browser, so every field is checked and anything unexpected is dropped:
    only the known keys are kept, addresses must look like addresses, and the form data must be base64 that
    decodes to a JSON object. No value is ever put on a shell command line unquoted.
    """
    if not isinstance(raw, dict):
        raise PayloadError("The form sent an unexpected message.")
    mode = _text(raw.get("mode"), "Mode")
    if mode not in MODES:
        raise PayloadError("Mode must be send or draft.")
    provider = _text(raw.get("provider"), "Provider")
    if provider not in PROVIDERS:
        raise PayloadError(f"Unknown provider: {provider!r}.")
    quote = _text(raw.get("quote"), "Quote number")
    if not _QUOTE.match(quote):
        raise PayloadError(f"Quote number should look like Q-123456, got {quote!r}.")
    quote = "Q-" + re.sub(r"^[Qq]-?", "", quote)

    to = _email(raw.get("to"), "To")
    cc_raw = raw.get("cc") or []
    if isinstance(cc_raw, str):
        cc_raw = [part for part in cc_raw.split(",")]
    if not isinstance(cc_raw, list):
        raise PayloadError("CC must be a list of addresses.")
    cc = [_email(item, "CC") for item in cc_raw if isinstance(item, str) and item.strip()]
    sender = _text(raw.get("from"), "From", required=False)
    if sender:
        sender = _email(sender, "From")

    # The renderer has no defaults: every field it prints comes from this data, so it is required.
    data = _text(raw.get("data"), "Form data", limit=MAX_DATA_CHARS)
    if not _B64.match(data):
        raise PayloadError("The form data is not valid base64.")
    try:
        decoded = json.loads(base64.b64decode(data, validate=True).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PayloadError(f"The form data could not be read: {exc}") from exc
    if not isinstance(decoded, dict):
        raise PayloadError("The form data must be a JSON object.")
    return {"mode": mode, "provider": provider, "quote": quote, "to": to, "cc": cc, "from": sender, "data": data}


def render_email(payload: dict, python: str | None = None, runner=subprocess.run) -> dict:
    """Runs the existing render script and returns {"subject", "html"}. Raises RuntimeError with a clear message."""
    interpreter = python or (str(VENV_PYTHON) if VENV_PYTHON.exists() else "python3")
    command = [interpreter, str(RENDER_SCRIPT), "--provider", payload["provider"], "--quote", payload["quote"],
               "--data", payload["data"]]
    try:
        result = runner(command, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Could not run the email renderer: {exc}") from exc
    if result.returncode != 0:
        # A Python traceback ends with the useful line (for example "KeyError: 'accountId'"), so keep the tail.
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise RuntimeError(f"The email renderer failed: {detail[-1][:300] if detail else 'no output'}")
    try:
        rendered = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("The email renderer returned something that is not JSON.") from exc
    if not isinstance(rendered, dict) or rendered.get("error"):
        raise RuntimeError(f"The email renderer reported: {rendered.get('error') if isinstance(rendered, dict) else rendered}")
    if not isinstance(rendered.get("subject"), str) or not isinstance(rendered.get("html"), str) or not rendered["html"].strip():
        raise RuntimeError("The renderer did not return a subject and a body.")
    return {"subject": rendered["subject"], "html": rendered["html"]}


def build_command(payload: dict) -> str:
    """The /MarketPlaceAutomation line, the same format the form has always shown."""
    command = f"/MarketPlaceAutomation {payload['provider']} {payload['quote']} to:{payload['to']}"
    for address in payload["cc"]:
        command += f" cc:{address}"
    if payload["from"]:
        command += f" from:{payload['from']}"
    if payload["data"]:
        command += f" --data {payload['data']}"
    return command


def prepare_run(payload: dict, rendered: dict, now: datetime | None = None) -> dict:
    """Saves the rendered email in a new run folder and returns the run record.

    For a send, Claude Code is given the existing /MarketPlaceAutomation command plus the path to write its
    result file. For a draft, it is given the saved subject and body so no shell is needed to create the draft.
    """
    now = now or datetime.now()
    run_dir = RUNS_DIR / now.strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "email.html").write_text(rendered["html"], encoding="utf-8")
    (run_dir / "email.json").write_text(
        json.dumps({"to": payload["to"], "cc": payload["cc"], "subject": rendered["subject"]}), encoding="utf-8")
    result_path = run_dir / "result.json"
    if payload["mode"] == "send":
        prompt = f"{build_command(payload)}\nWrite the result to {result_path}"
    else:
        prompt = (
            f"Create a Gmail DRAFT (do not send) using the mcp__gmail__draft_email tool. "
            f"to: {payload['to']}; cc: {', '.join(payload['cc']) or '(none)'}; "
            f"subject: read it from {run_dir / 'email.json'}; body: the exact contents of {run_dir / 'email.html'}, "
            f"body_type html. Then write {result_path} as JSON with status \"drafted\", the to address and the subject."
        )
    return {"dir": run_dir, "mode": payload["mode"], "to": payload["to"], "subject": rendered["subject"],
            "prompt": prompt, "result_path": result_path, "started": time.time()}


def read_result(run: dict) -> dict | None:
    """The result file Claude Code wrote, or None if it is not there yet or not readable."""
    try:
        data = json.loads(Path(run["result_path"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("status") in ("sent", "drafted") else None


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
