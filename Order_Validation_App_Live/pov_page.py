"""Shared page for the PO validators: prepares a run of a skill and shows its result.

Two thin pages use this module, one per skill (pages/PO_Validation.py for /povAgent, pages/PO_Validation_POV.py
for /pov), so the logic lives in one place. The validation itself is the skill, which reads the PO, queries
Salesforce (QA / UAT only) and writes an Excel report. It runs in Claude Code, where the company's
tool-validation policy lets you approve each step; this page does not start it in the background. The page:

  1. saves the uploaded PO (and, for /povAgent, an optional JSON order file) under the skill's inputs folder,
  2. opens Terminal with Claude Code already running the skill on those files, and
  3. finds the finished workbook and Google Sheet link in the skill's outputs folder.

Nothing here reads credentials or calls Salesforce. The helpers take a PovConfig so one module serves both skills.
"""

import json
import re
import shlex
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
KEEP_INPUTS_DAYS = 7
HISTORY_SIZE = 10
POLL_SECONDS = 5            # how often the page looks for the finished report
SHEET_GRACE_SECONDS = 180   # how long to wait for the Google Sheet link after the workbook appears
GIVE_UP_SECONDS = 30 * 60   # stop polling a run that never produced a report
PO_TYPES = ["pdf", "docx", "doc", "xlsx", "xls", "png", "jpg", "jpeg", "tiff", "bmp", "gif"]


@dataclass(frozen=True)
class PovConfig:
    """What differs between the two PO validators."""

    skill: str                 # "pov" or "povAgent": the slash command and the skill folder name
    title: str                 # page title shown to the user
    accepts_json: bool         # /povAgent compares a JSON order file too; /pov does not
    description: str           # one-line caption under the title
    note: str = ""             # optional extra line, e.g. a limitation of the skill
    repo_root: Path = field(default=REPO_ROOT)
    accepts_edi: bool = False  # /pov_EDI compares an X12 850 .edi file instead of a JSON one

    @property
    def extra_name(self) -> str:
        """Label of the optional second file, or "" when the skill takes only a PO."""
        return "JSON" if self.accepts_json else "EDI" if self.accepts_edi else ""

    @property
    def input_dir(self) -> Path:
        return self.repo_root / "claude_outputs" / f"{self.skill}_inputs"

    @property
    def output_dir(self) -> Path:
        return self.repo_root / "claude_outputs" / f"{self.skill}_outputs"

    @property
    def skill_file(self) -> Path:
        return self.repo_root / ".claude" / "skills" / self.skill / "SKILL.md"

    @property
    def key(self) -> str:
        """Prefix for session-state and widget keys, so the two pages never share state."""
        return f"povpage_{self.skill}"


def _safe_suffix(filename: str) -> str:
    """A plain extension taken from the upload's name; anything odd becomes no extension."""
    suffix = Path(filename).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,5}", suffix) else ""


def _quote(path: Path) -> str:
    """A path inside single quotes, as the skill's prompt expects, with any quote escaped."""
    return "'" + str(path).replace("'", "'\\''") + "'"


def build_command(cfg: PovConfig, files: list[Path], env: str) -> str:
    return f"/{cfg.skill} " + " ".join(_quote(p) for p in files) + f" Env: {env}"


def validate_json(raw: bytes) -> str | None:
    """An error message if the bytes are not UTF-8 JSON, else None."""
    try:
        json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return f"The JSON file is not valid JSON: {exc}"
    return None


def validate_edi(raw: bytes) -> str | None:
    """An error message if the bytes are not an X12 850 (ISA header, ST*850), else None.

    Only a quick look so a wrong file is caught before Claude Code starts; the skill does the real parsing.
    The element separator is the character after "ISA", so it is not assumed to be "*".
    """
    try:
        text = raw.decode("utf-8-sig").lstrip()
    except UnicodeDecodeError:
        return "The EDI file is not text, so it is not an X12 850."
    if not text.startswith("ISA") or len(text) < 106:
        return "The EDI file does not start with an X12 ISA header, so it is not an X12 850."
    element = text[3]
    if not re.search(r"(^|[^A-Za-z0-9])ST" + re.escape(element) + "850" + re.escape(element), text):
        return "The EDI file has no ST*850 segment, so it is not a purchase order (X12 850)."
    return None


def save_run(cfg: PovConfig, po, order, env: str, now: datetime | None = None) -> dict:
    """Saves the uploads under a new run folder and returns the run record."""
    now = now or datetime.now()
    run_dir = cfg.input_dir / now.strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    files = []
    # Fixed names: the uploaded file's own name never reaches the command line.
    if po is not None:
        path = run_dir / f"po{_safe_suffix(po.name)}"
        path.write_bytes(po.getvalue())
        files.append(path)
    if order is not None and (cfg.accepts_json or cfg.accepts_edi):
        # Fixed name too: the uploaded name never reaches the command line, and ".edi" is what the skill looks for.
        path = run_dir / ("order.json" if cfg.accepts_json else "order.edi")
        path.write_bytes(order.getvalue())
        files.append(path)
    return {"dir": run_dir, "files": files, "env": env, "started": time.time(),
            "command": build_command(cfg, files, env)}


def find_reports(cfg: PovConfig, since: float | None = None, limit: int = HISTORY_SIZE) -> list[dict]:
    """Finished workbooks (newest first) with the Google Sheet link saved next to each, if any."""
    if not cfg.output_dir.exists():
        return []
    reports = []
    for xlsx in sorted(cfg.output_dir.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True):
        if since is not None and xlsx.stat().st_mtime < since - 1:
            continue
        link = None
        url_file = xlsx.with_name(xlsx.stem + "_Google_Sheet_link.url")
        if url_file.exists():
            match = re.search(r"^URL=(\S+)", url_file.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
            link = match.group(1) if match else None
        reports.append({"path": xlsx, "link": link, "when": datetime.fromtimestamp(xlsx.stat().st_mtime)})
        if len(reports) >= limit:
            break
    return reports


def purge_old_inputs(cfg: PovConfig, days: int = KEEP_INPUTS_DAYS) -> None:
    """Best-effort removal of prepared input folders older than `days`."""
    if not cfg.input_dir.exists():
        return
    cutoff = time.time() - days * 86400
    for folder in cfg.input_dir.iterdir():
        try:
            if folder.is_dir() and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


def find_claude() -> str | None:
    """The claude CLI: on PATH, else in the places Claude Code installs itself."""
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (Path.home() / ".local" / "bin" / "claude", Path.home() / ".claude" / "local" / "claude"):
        if candidate.exists():
            return str(candidate)
    return None


def write_launcher(cfg: PovConfig, run: dict, claude: str) -> Path:
    """A double-clickable .command file that starts Claude Code with the skill's prompt.

    Claude Code runs interactively in a Terminal window so a person can approve the tool prompts
    the company's tool-validation policy requires. `exec` hands the window to Claude Code, and
    shlex.quote keeps the prompt one intact argument whatever the paths contain.
    """
    path = run["dir"] / "run.command"
    path.write_text(
        "#!/bin/bash\n"
        f"cd {shlex.quote(str(cfg.repo_root))} || exit 1\n"
        f"exec {shlex.quote(claude)} {shlex.quote(run['command'])}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def open_in_terminal(launcher: Path, opener=subprocess.run) -> str | None:
    """Opens the launcher in Terminal. Returns an error message, or None on success."""
    try:
        # A list of arguments, no shell. A .command file avoids the macOS Automation prompt
        # that scripting Terminal with AppleScript would raise.
        result = opener(["open", "-a", "Terminal", str(launcher)], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Could not open Terminal: {exc}"
    if getattr(result, "returncode", 0) != 0:
        return f"Could not open Terminal: {(getattr(result, 'stderr', '') or '').strip() or 'open failed'}"
    return None


def report_state(cfg: PovConfig, run: dict, now: float | None = None) -> dict:
    """Where a launched run stands, judged only from the output folder.

    stage: 'waiting' (no complete workbook yet), 'workbook' (workbook ready, Sheet link not yet),
    'done' (workbook and link, or the link grace period passed) or 'timeout' (nothing after GIVE_UP_SECONDS).
    A workbook counts only if it is newer than the run, a valid zip, and the same size as at the last poll,
    so a half-written file is never offered.
    """
    now = now if now is not None else time.time()
    elapsed = now - run["started"]
    state = {"stage": "waiting", "elapsed": elapsed, "report": None}
    reports = find_reports(cfg, since=run["started"])
    for report in reports:
        path = report["path"]
        try:
            size = path.stat().st_size
        except OSError:
            continue
        previous = run.setdefault("sizes", {}).get(str(path))
        run["sizes"][str(path)] = size
        if previous != size or not zipfile.is_zipfile(path):
            continue                      # still being written, or not a workbook
        run.setdefault("ready_at", {}).setdefault(str(path), now)
        state["report"] = report
        waited = now - run["ready_at"][str(path)]
        state["stage"] = "done" if (report["link"] or waited >= SHEET_GRACE_SECONDS) else "workbook"
        return state
    if elapsed >= GIVE_UP_SECONDS:
        state["stage"] = "timeout"
    return state


def render_reports(st, reports: list[dict], key_prefix: str) -> None:
    for i, report in enumerate(reports):
        cols = st.columns([5, 2, 2])
        cols[0].markdown(f"**{report['path'].name}**  \n{report['when']:%d %b %Y, %H:%M}")
        cols[1].download_button(
            "Download Excel", report["path"].read_bytes(), file_name=report["path"].name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"{key_prefix}_dl_{i}",
        )
        if report["link"]:
            cols[2].link_button("Open Google Sheet", report["link"], key=f"{key_prefix}_sheet_{i}")


def render_page(st, cfg: PovConfig) -> None:
    """The whole page body. Streamlit is passed in so this module imports without it (and is testable)."""
    purge_old_inputs(cfg)

    st.title(cfg.title)
    st.caption(cfg.description + " Salesforce **QA or UAT only**.")
    if cfg.note:
        st.caption(cfg.note)
    if not cfg.skill_file.exists():
        st.error(f"The /{cfg.skill} skill is missing at `{cfg.skill_file}`.")

    state = st.session_state
    run_key = f"{cfg.key}_run"
    state.setdefault(run_key, None)

    tab_prepare, tab_reports = st.tabs(["Prepare a run", "Finished reports"])

    with tab_prepare:
        run = state[run_key]
        if run is None:
            # The right column only holds the QA/UAT picker, so keep it narrow and let the uploads
            # take the rest of the page width.
            left, right = st.columns([5, 1])
            json_file = None   # the optional second file: JSON for /povAgent, an X12 850 .edi for /pov_EDI
            with left:
                po_file = st.file_uploader("Purchase order", type=PO_TYPES, key=f"{cfg.key}_po",
                                           help="One PO: PDF, Word, Excel or an image.")
                if cfg.accepts_json:
                    json_file = st.file_uploader(
                        "JSON order file (optional)", type=["json"], key=f"{cfg.key}_json",
                        help="Adds JSON vs Quote and PO vs JSON checks to the PO vs Quote checks.",
                    )
                elif cfg.accepts_edi:
                    json_file = st.file_uploader(
                        "EDI order file (optional)", type=["edi"], key=f"{cfg.key}_edi",
                        help="An X12 850 purchase order; any file name, ending in .edi. "
                             "Adds EDI vs Quote and PO vs EDI checks to the PO vs Quote checks.",
                    )
            with right:
                env = st.radio("Salesforce environment", ["QA", "UAT"], horizontal=True, key=f"{cfg.key}_env")
                st.caption("Production is never queried.")

            if st.button("Prepare validation", type="primary", key=f"{cfg.key}_prepare",
                         disabled=not (po_file or json_file)):
                error = None
                for label, upload in (("PO", po_file), (cfg.extra_name, json_file)):
                    if upload is not None and upload.size > MAX_UPLOAD_BYTES:
                        error = f"The {label} file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
                if json_file is not None and error is None:
                    error = (validate_json if cfg.accepts_json else validate_edi)(json_file.getvalue())
                if error:
                    st.error(error)
                else:
                    state[run_key] = save_run(cfg, po_file, json_file, env)
                    st.rerun()
        else:
            claude_bin = find_claude()
            launched = run.get("launched", False)

            if not launched:
                st.success("Files saved and ready.")
            if claude_bin is None:
                st.error("The `claude` CLI was not found, so it can't be opened from here. Use the manual command below.")
            else:
                label = "Open again in Claude Code" if launched else "Open in Claude Code"
                if st.button(label, type="primary", key=f"{cfg.key}_open"):
                    launcher = write_launcher(cfg, run, claude_bin)
                    error = open_in_terminal(launcher)
                    if error:
                        st.error(error)
                    else:
                        # The clock restarts at launch so only reports written by this launch count.
                        run.update(launched=True, started=time.time(), sizes={}, ready_at={})
                        st.rerun()
                if not launched:
                    st.caption(
                        f"Opens Terminal with Claude Code already running /{cfg.skill} on your files. "
                        "Your only step there is approving its prompts (Salesforce queries, the workbook build, "
                        "the Google Sheet upload). This page then picks up the report by itself."
                    )

            if launched:
                @st.fragment(run_every=POLL_SECONDS if not run.get("finished") else None)
                def watch_run() -> None:
                    status = report_state(cfg, run)
                    minutes, seconds = divmod(int(status["elapsed"]), 60)
                    if status["stage"] == "waiting":
                        st.info(f"Waiting for Claude Code… {minutes}m {seconds:02d}s. Approve the prompts in the Terminal window.")
                    elif status["stage"] == "workbook":
                        st.info("Workbook ready. Waiting for the Google Sheet link…")
                    elif status["stage"] == "timeout":
                        first_time = not run.get("finished")
                        run["finished"] = True
                        st.warning("No report appeared after 30 minutes. Check the Terminal window, then press Check again.")
                        if st.button("Check again", key=f"{cfg.key}_again"):
                            # Gives it one more minute of polling before it times out again.
                            run.update(started=time.time() - GIVE_UP_SECONDS + 60, finished=False)
                            st.rerun()
                        elif first_time:
                            st.rerun()  # stop polling; guarded by first_time so it can never loop
                    else:
                        first_time = not run.get("finished")
                        run["finished"] = True
                        st.success("Validation finished.")
                        if not status["report"]["link"]:
                            st.caption("No Google Sheet link was saved; the upload may have been skipped or failed. The Excel report is below.")
                        render_reports(st, [status["report"]], f"{cfg.key}_run")
                        if first_time:
                            # One full rerun so the fragment is redefined without run_every and polling stops.
                            # Guarded by first_time so it can never loop.
                            st.rerun()

                watch_run()

            with st.expander("Run it yourself instead"):
                st.markdown("Open Claude Code in this project folder, paste this command and press Enter:")
                st.code(run["command"], language="text")
            st.caption(f"Environment: {run['env']} · saved in `{run['dir']}`")

            again, delete = st.columns(2)
            if again.button("Prepare another", key=f"{cfg.key}_another"):
                state[run_key] = None
                st.rerun()
            if delete.button("Delete prepared files", key=f"{cfg.key}_delete"):
                shutil.rmtree(run["dir"], ignore_errors=True)
                state[run_key] = None
                st.rerun()

    with tab_reports:
        recent = find_reports(cfg)
        if recent:
            render_reports(st, recent, f"{cfg.key}_hist")
        else:
            st.info(f"No reports yet. They appear here after a /{cfg.skill} run, saved in claude_outputs/{cfg.skill}_outputs.")

    st.caption(
        "The model that validates the PO runs in Claude Code under your company's tool-validation policy. "
        "Confirm the verdict against the workbook before acting on it."
    )
