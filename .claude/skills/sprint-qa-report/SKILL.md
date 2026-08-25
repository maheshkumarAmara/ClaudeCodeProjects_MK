---
name: sprint-qa-report
description: Generate a QA Sprint Report with 4 tabs (Reports | Overall Summary | TestCase Coverage | Sheet1), upload to Google Drive, and send sign-off email. Tab order and names match the reference template exactly. Use when asked to create a sprint QA report, generate sprint status report, or prepare sprint sign-off email. Interactively prompts for sprint config (name, dates, TC sheet) on each run, pre-filling values from the previous run stored in .last_run.json; user can confirm or change any field before generation begins.
argument-hint: (no args; interactive config prompt appears) or: <SPRINT_NAME> [TC_SHEET_URL] [from=EMAIL] [to=EMAIL1,EMAIL2] [cc=EMAIL1,EMAIL2]
allowed-tools: Bash(python3 *), Bash(grep *), Bash(ls *), Bash(find *), Read(*), Edit(*)
---

## PERFORMANCE RULES — read BEFORE executing any step

This skill issues **exactly 5 python3 Bash calls** in total. Do NOT add extra calls between steps.

| Call | Step | Description |
|------|------|-------------|
| 1 | Step 0a | Fetch stored config + sprint tabs + JIRA dates |
| 2 | Steps 0c → 1–5 | Save confirmed config + query JIRA + fetch TC sheet + compute metrics |
| 3 | Step 6 Script A | Clone master template xlsx + copy to /tmp/sprint_qa_working.xlsx |
| 4 | Step 6 Script B | Populate xlsx with sprint data (openpyxl) + upload to Drive |
| 5 | Steps 7–8b | Re-read sheet + build email + send |

**Between call 1 and call 2** → wait for user config confirmation (Step 0b).
**Between call 4 and call 5** → wait for user to review and reply "send" (Step 6e).

> **STRICT PROHIBITION: Never use MCP tools (`mcp__*`) or `WebFetch` at any point during skill execution. All API calls are handled inside the python3 scripts via `urllib`.**
> **Do NOT make any extra Bash calls (grep, ls, find, cat) between the 5 python3 calls — embed all logic inside the python3 scripts to avoid extra approval prompts.**
> **Tip for fastest runs: pre-fill `.claude/skills/sprint-qa-report/.env` with SPRINT_NAME, FROM_EMAIL, TO_EMAILS, CC_EMAILS so Step 0b auto-confirms and skips the interactive config prompt.**

---

You are an expert QA engineer generating sprint QA sign-off reports for the Rubrik QA team.

## Constants

```
# Default TC sheet — used when the user does not supply a TC_SHEET_URL argument
DEFAULT_TC_SHEET_FILE_ID  = "1lBhXjFci29i-RAY1MkU5ljMF12lUg_uk3mgJhKhJPM8"
DEFAULT_TC_SHEET_BASE_URL = "https://docs.google.com/spreadsheets/d/1lBhXjFci29i-RAY1MkU5ljMF12lUg_uk3mgJhKhJPM8/edit"

# Resolved at runtime in Step 1 (either from user input or from the defaults above)
TC_SHEET_FILE_ID  = ""   # set in Step 1
TC_SHEET_BASE_URL = ""   # set in Step 1
TC_SPRINT_TAB_URL = ""   # set in Step 3: f"{TC_SHEET_BASE_URL}#gid={FOUND_GID}"

# Master template xlsx — cloned for each sprint report. DO NOT change this ID.
# Stored locally at ~/.claude/sprint_qa_master_template.xlsx (auto-downloaded on first run).
TEMPLATE_DRIVE_FILE_ID = "1Xa6eoVU4hXgZAaeApuOIXhK2lC5YG-Pr"
TEMPLATE_LOCAL_PATH    = "~/.claude/sprint_qa_master_template.xlsx"

TOKEN_FILE        = str(Path.home() / ".gdrive-mcp-token.json")
REPORT_FOLDER_ID  = "1vdPP7M8QBA3Mj8qhSfSs_runBc8YBCQP"
```

> **RULE: Never ask the user for the TC sheet — it has a default. Accept it only if the user voluntarily provides it as an argument.**

The TC sheet has one tab per sprint. Key columns (0-indexed):
- **col 1** → `Ticket#` (JIRA story key)
- **col 3** → `Test Case No#`
- **col 4** → `Test Case` (name)
- **col 5** → `Test Case Description`
- **col 9** → `Expected Result`
- **col 10** → `QA Status`
- **col 11** → `Status` (Pass / Fail / Blocked / In Progress)
- **col 12** → `QA Contact` (tested by)

## Configuration — .env file

All inputs can be pre-set in a `.env` file so the user can run `/sprint-qa-report` with no arguments.

**Location:** `.claude/skills/sprint-qa-report/.env`
*(copy `.env.example` in the same folder and fill in your values)*

```
# .env — Sprint QA Report configuration
# Lines starting with # are comments. All values are optional — unset values fall back to defaults.

SPRINT_NAME   = F27-Sprint 7

# START_DATE and END_DATE are auto-fetched from JIRA — do NOT set them here.
# START_DATE  =
# END_DATE    =

# TC sheet URL (full URL, short URL with #gid, or bare file ID).
# Leave blank to use the default Rubrik QA TC sheet.
TC_SHEET_URL  =

# Email settings
FROM_EMAIL    = your.name@rubrik.com
TO_EMAILS     = user1@rubrik.com, user2@rubrik.com
CC_EMAILS     = manager@rubrik.com
```

**Priority:** command-line arguments > `.env` values > built-in defaults.
If SPRINT_NAME is missing from both the `.env` and arguments, the skill will stop and ask the user. START_DATE and END_DATE are always auto-fetched from JIRA — they are never required from the user.

## Input

The user provided: **$ARGUMENTS**

Values are resolved in this order: `$ARGUMENTS` → `.env` file → built-in defaults.

**Required inputs** (must come from arguments or `.env`):
1. `SPRINT_NAME`   — e.g. `F27-Sprint 7`

**Auto-derived inputs** (fetched from JIRA Board API — do NOT ask the user):
2. `START_DATE`    — Sprint start date; auto-fetched from JIRA when sprint is selected.
3. `END_DATE`      — Sprint end date; auto-fetched from JIRA when sprint is selected.

**Optional inputs** (arguments use `key=value` syntax; `.env` uses `KEY = value`):
4. `TC_SHEET_URL`  — Google Sheets URL or bare file ID. If omitted → `DEFAULT_TC_SHEET_FILE_ID`.
5. `FROM_EMAIL`    — Sender address. If omitted → Gmail API sends as the authenticated account.
6. `TO_EMAILS`     — Comma-separated To recipients. If omitted → Step 6e will ask.
7. `CC_EMAILS`     — Comma-separated CC recipients. If omitted → no CC.

---

## Step 0 — Interactive Config (runs first, before data collection)

> Read stored config from `.last_run.json` (or built-in defaults), present to user, save confirmed values, then proceed.

### Step 0a — Read stored config + fetch TC sheet tabs

Run this python3 script:

```python
import json, ssl, urllib.request, re
from pathlib import Path

import subprocess as _sp, os as _os
try:
    _git_root = _sp.check_output(["git","rev-parse","--show-toplevel"],text=True,cwd=_os.getcwd()).strip()
    SKILL_DIR = Path(_git_root) / ".claude" / "skills" / "sprint-qa-report"
    if not SKILL_DIR.exists(): raise FileNotFoundError("skill dir not in repo")
except Exception:
    SKILL_DIR = Path.home() / ".claude" / "sprint-qa-report-config"
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
TEMP_FILE  = SKILL_DIR / ".last_run.json"
TOKEN_FILE = Path.home() / ".gdrive-mcp-token.json"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode    = ssl.CERT_NONE

TC_OPTIONS = {
    "a": "https://docs.google.com/spreadsheets/d/1lBhXjFci29i-RAY1MkU5ljMF12lUg_uk3mgJhKhJPM8/edit?gid=569799728#gid=569799728",
    "b": "https://docs.google.com/spreadsheets/d/12xxjFEe2aeOk1X7z2vQalkOEp6fr9_5BMhKRy3C5hgw/edit?gid=0#gid=0",
    "c": "https://docs.google.com/spreadsheets/d/165DKk33NS-NqO-jciKBPM-ym0l6RtMV6QZc4o8pIRbw/edit?gid=614334348#gid=614334348",
}

BUILTIN_DEFAULTS = {
    "SPRINT_NAME":  "F27-Sprint 7",
    "START_DATE":   "",   # auto-fetched from JIRA
    "END_DATE":     "",   # auto-fetched from JIRA
    "TC_SHEET_URL": TC_OPTIONS["a"],
    "FROM_EMAIL":   "",
    "TO_EMAILS":    "",
    "CC_EMAILS":    "",
}

cfg = BUILTIN_DEFAULTS.copy()
source = "built-in defaults"
if TEMP_FILE.exists():
    try:
        stored = json.loads(TEMP_FILE.read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in stored.items() if v})
        source = "last run"
    except Exception as e:
        source = f"built-in defaults (could not read last run: {e})"

# ── Fetch TC sheet tab names via Sheets API ───────────────────────
sprint_tabs = []
try:
    token_data   = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    access_token = token_data.get("access_token", "")
    _m = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', cfg.get("TC_SHEET_URL", ""))
    _file_id = _m.group(1) if _m else None
    if _file_id and access_token:
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{_file_id}?fields=sheets.properties.title"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
        resp = json.loads(urllib.request.urlopen(req, context=ctx).read())
        sprint_tabs = [s["properties"]["title"] for s in resp.get("sheets", [])]
except Exception:
    sprint_tabs = []   # silently fall back to manual entry

# ── Fetch JIRA sprint dates for the last 4 tabs ───────────────────
import base64, datetime
sprint_dates = {}   # tab_name → {"start": "Apr 25, 2026", "end": "May 8, 2026"}
try:
    _conf = (Path.home() / ".mcp.conf.yaml").read_text(encoding="utf-8")
    _ju = re.search(r'jira:.*?user:\s*([^\s\n]+)', _conf, re.DOTALL)
    _jt = re.search(r'jira:.*?token:\s*([^\s\n]+)', _conf, re.DOTALL)
    _js = re.search(r"jira:.*?url:\s*['\"]([^'\"]+)['\"]", _conf, re.DOTALL)
    JIRA_USER   = _ju.group(1).strip("'\"") if _ju else ""
    JIRA_TOKEN  = _jt.group(1).strip("'\"") if _jt else ""
    JIRA_SERVER = _js.group(1).strip("'\"") if _js else "https://rubrik.atlassian.net"
    _jira_b64   = base64.b64encode(f"{JIRA_USER}:{JIRA_TOKEN}".encode()).decode()

    _TC_FILE_PROJECT_MAP = {
        "1lBhXjFci29i-RAY1MkU5ljMF12lUg_uk3mgJhKhJPM8": "PRDOPS",
        "12xxjFEe2aeOk1X7z2vQalkOEp6fr9_5BMhKRy3C5hgw": "MKTG",
        "165DKk33NS-NqO-jciKBPM-ym0l6RtMV6QZc4o8pIRbw": "CS",
    }
    _tc_url = cfg.get("TC_SHEET_URL", "")
    _tc_fid_m = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', _tc_url)
    _tc_fid   = _tc_fid_m.group(1) if _tc_fid_m else ""
    _project  = _TC_FILE_PROJECT_MAP.get(_tc_fid, "PRDOPS")

    def _jira_get_0a(url):
        r = urllib.request.Request(url, headers={"Authorization": f"Basic {_jira_b64}", "Accept": "application/json"})
        return json.loads(urllib.request.urlopen(r, context=ctx).read())

    def _fmt_jira_date(d):
        try:
            import re as _re
            d_str = (d or "")
            if 'T' in d_str:
                d_clean = _re.sub(r'\.\d+', '', d_str).replace('Z', '+00:00')
                dt = datetime.datetime.fromisoformat(d_clean)
                if dt.tzinfo is not None:
                    dt = dt.astimezone()
                return dt.strftime("%b %-d, %Y")
            return datetime.datetime.strptime(d_str[:10], "%Y-%m-%d").strftime("%b %-d, %Y")
        except: return (d or "")[:10]

    _boards = _jira_get_0a(f"{JIRA_SERVER}/rest/agile/1.0/board?projectKeyOrId={_project}&maxResults=5")
    _board_id = (_boards.get("values") or [{}])[0].get("id")
    if _board_id:
        _sprints = _jira_get_0a(f"{JIRA_SERVER}/rest/agile/1.0/board/{_board_id}/sprint?state=closed,active&maxResults=30")
        _sp_by_num = {}
        for _sp in (_sprints.get("values") or []):
            _nm = re.search(r'SP(\d+)', _sp.get("name", ""), re.IGNORECASE)
            if _nm:
                _sp_by_num[int(_nm.group(1))] = _sp
        for _tab in sprint_tabs[-4:]:
            _tnm = re.search(r'Sprint\s+(\d+)', _tab, re.IGNORECASE)
            if _tnm:
                _sp = _sp_by_num.get(int(_tnm.group(1)))
                if _sp:
                    sprint_dates[_tab] = {
                        "start": _fmt_jira_date(_sp.get("startDate")),
                        "end":   _fmt_jira_date(_sp.get("endDate")),
                    }
except Exception:
    sprint_dates = {}   # silently fall back; user will be asked for dates

print(json.dumps({"source": source, "cfg": cfg, "tc_options": TC_OPTIONS,
                  "sprint_tabs": sprint_tabs, "sprint_dates": sprint_dates}))
```

### Step 0b — Present values and route user

Parse the JSON printed above. From `sprint_tabs`, take the **last 4 entries** reversed (newest first); these become options `[1]`–`[4]`. Option `[5]` is always "Other (enter manually)". If `sprint_tabs` is empty, show only the plain current value.

For each sprint tab, show its JIRA dates from `sprint_dates` if available (format: `Apr 25 – May 8`). Mark the currently selected sprint with `← current`.

Display:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Sprint QA Report — Configuration  [Source: {source}]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1.  SPRINT        :  {SPRINT_NAME}
        [1] F27-Sprint 7   Apr 25 – May 8, 2026    ← current
        [2] F27-Sprint 6   Apr 11 – Apr 24, 2026
        [3] F27-Sprint 5   Mar 29 – Apr 10, 2026
        [4] F27-Sprint 4   Mar 15 – Mar 28, 2026
        [5] Other (enter manually)
  2.  START_DATE    :  {START_DATE}   (auto-fetched from JIRA — not editable)
  3.  END_DATE      :  {END_DATE}     (auto-fetched from JIRA — not editable)
  4.  TC_SHEET_URL  :  {TC_SHEET_URL}
        [a] ProdOps    — https://docs.google.com/spreadsheets/d/1lBhXjFci29i-RAY1MkU5ljMF12lUg_uk3mgJhKhJPM8/...
        [b] Marketing  — https://docs.google.com/spreadsheets/d/12xxjFEe2aeOk1X7z2vQalkOEp6fr9_5BMhKRy3C5hgw/...
        [c] CS         — https://docs.google.com/spreadsheets/d/165DKk33NS-NqO-jciKBPM-ym0l6RtMV6QZc4o8pIRbw/...
  5.  FROM_EMAIL    :  {FROM_EMAIL}
  6.  TO_EMAILS     :  {TO_EMAILS}
  7.  CC_EMAILS     :  {CC_EMAILS}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  go    → proceed with values above
  date  → change sprint + dates (auto-filled from JIRA)
  all   → change all fields
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Wait for user reply.** Route based on response:

- **"go" / "yes" / blank** → keep all values as shown; jump to Step 0c.
- **"date"** → go to Step 0b-date below.
- **"all"** → go to Step 0b-all below.
- **User pastes `KEY=VALUE` pairs directly** → parse them, update only the supplied fields, jump to Step 0c.

---

### Step 0b-date — Select sprint (dates auto-fill from JIRA)

Show the sprint selection menu and wait for the user's reply:

```
Select sprint:
  [1] F27-Sprint 7   Apr 25 – May 8, 2026    ← current
  [2] F27-Sprint 6   Apr 11 – Apr 24, 2026
  [3] F27-Sprint 5   Mar 29 – Apr 10, 2026
  [4] F27-Sprint 4   Mar 15 – Mar 28, 2026
  [5] Other (enter manually)
```

**Map user's reply to SPRINT_NAME + dates:**

- User replies `1`–`4` → set SPRINT_NAME to that tab name; set START_DATE and END_DATE from `sprint_dates[tab]` (JIRA data).
- User replies `5` or "other" → ask `Sprint name:` then `START_DATE:` then `END_DATE:` as plain text, one at a time.
- User types a tab name directly → match it in the list; use its JIRA dates if found, otherwise ask for dates.
- If `sprint_tabs` was empty (API failed) → ask `Sprint name:`, `START_DATE:`, `END_DATE:` as plain-text questions.

**After sprint + dates are set**, show a one-line confirmation and ask to proceed:

```
✅ F27-Sprint 7  |  Apr 25, 2026 → May 8, 2026  (from JIRA)
Reply "go" to confirm, or enter different dates (start / end):
```

- User replies "go" / blank → proceed to Step 0c with these values.
- User enters one or two dates → override only what they provided; proceed to Step 0c.

Fields 4–7 keep their current values.

---

### Step 0b-all — Collect all 7 fields (one question at a time)

Ask all 7 fields one at a time, waiting for a reply after each. If the user pastes multiple values in a single message, parse them all and skip remaining questions.

**Question sequence:**

1. Show the same sprint selection menu as Step 0b-date. Map reply using the same rules (auto-fill dates from JIRA). After sprint selection, show the one-line `✅ sprint | dates` confirmation and ask for "go" or date override before continuing.
2. Ask: `TC sheet — a=ProdOps, b=Marketing, c=CS, or paste URL (current: {TC_SHEET_URL}):` → if `a`/`b`/`c`, replace with the corresponding full URL; blank keeps current.
3. Ask: `FROM_EMAIL (current: {FROM_EMAIL}):` → update if non-empty.
4. Ask: `TO_EMAILS — comma-separated (current: {TO_EMAILS}):` → update if non-empty.
5. Ask: `CC_EMAILS — comma-separated, or blank for none (current: {CC_EMAILS}):` → update if non-empty; blank clears.

> Note: START_DATE and END_DATE are set automatically when the sprint is selected in step 1; they are not asked again unless the user overrides in the confirmation prompt.

After all fields collected, proceed to Step 0c.

### Step 0c — Save confirmed config (merged into python3 call #2)

After the user confirms, **do NOT run Step 0c as a separate script**. Instead, prepend the save block below to the Steps 1–5 mega-script and run both as a **single python3 call** (call #2). Replace each `<<...>>` with the actual confirmed value at the top of the combined script:

```python
# ── Step 0c block — PREPEND THIS TO THE TOP OF THE Steps 1-5 mega-script ──
# Replace <<...>> with actual confirmed values before running.
import json
from pathlib import Path

import subprocess as _sp2, os as _os2
try:
    _gr2 = _sp2.check_output(["git","rev-parse","--show-toplevel"],text=True,cwd=_os2.getcwd()).strip()
    _sd2 = Path(_gr2) / ".claude" / "skills" / "sprint-qa-report"
    if not _sd2.exists(): raise FileNotFoundError
except Exception:
    _sd2 = Path.home() / ".claude" / "sprint-qa-report-config"; _sd2.mkdir(parents=True, exist_ok=True)
TEMP_FILE = _sd2 / ".last_run.json"

cfg = {
    "SPRINT_NAME":  "<<CONFIRMED_SPRINT_NAME>>",
    "START_DATE":   "<<CONFIRMED_START_DATE>>",
    "END_DATE":     "<<CONFIRMED_END_DATE>>",
    "TC_SHEET_URL": "<<CONFIRMED_TC_SHEET_URL>>",
    "FROM_EMAIL":   "<<CONFIRMED_FROM_EMAIL>>",
    "TO_EMAILS":    "<<CONFIRMED_TO_EMAILS>>",
    "CC_EMAILS":    "<<CONFIRMED_CC_EMAILS>>",
}

TEMP_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
print(f"✅ Config saved → {TEMP_FILE}")
# ── End of Step 0c block — the Steps 1-5 code follows immediately below ──
```

---

## STEPS 1–5 — Load Config, Query JIRA, Fetch TC Sheet, Parse & Compute (python3 call #2)

> **Combine with Step 0c above into ONE python3 call.** Prepend the Step 0c save block to the top of this script, replacing `<<...>>` with confirmed values. This saves config and immediately proceeds with all data gathering — no separate call needed.

> **PERFORMANCE: All data gathering runs in a single auto-approved python3 script — no MCP tool calls for Steps 1-5. JIRA credentials are read from `~/.mcp.conf.yaml`; Drive uses `~/.gdrive-mcp-token.json`. Results saved to `/tmp/sprint_data.json` for Scripts A and B.**

Run the following python3 mega-script verbatim (replacing nothing — all values come from .last_run.json / .env and APIs):

```python
import json, ssl, urllib.request, urllib.parse, datetime, csv, io, re, base64
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# ── 1: Load .env ──────────────────────────────────────────────────────────────
import subprocess as _sp3, os as _os3
try:
    _gr3 = _sp3.check_output(["git","rev-parse","--show-toplevel"],text=True,cwd=_os3.getcwd()).strip()
    _sd3 = Path(_gr3) / ".claude" / "skills" / "sprint-qa-report"
    if not _sd3.exists(): raise FileNotFoundError
except Exception:
    _sd3 = Path.home() / ".claude" / "sprint-qa-report-config"; _sd3.mkdir(parents=True, exist_ok=True)
ENV_FILE = _sd3 / ".env"

env_cfg = {}
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        if '=' in line:
            k, _, v = line.partition('=')
            env_cfg[k.strip().upper()] = v.strip().strip('"').strip("'")
    print(f"✅ Loaded .env from: {ENV_FILE}")
else:
    print(f"⚠ No .env file found — add one at {ENV_FILE}")

# ── 1b: Load .last_run.json (interactive config saved by Step 0) ─────────────
LAST_RUN_FILE = _sd3 / ".last_run.json"
last_run_cfg = {}
if LAST_RUN_FILE.exists():
    try:
        last_run_cfg = json.loads(LAST_RUN_FILE.read_text(encoding="utf-8"))
        print(f"✅ Loaded interactive config from: {LAST_RUN_FILE}")
    except Exception as e:
        print(f"⚠ Could not read {LAST_RUN_FILE}: {e}")

# ── 2: Parse $ARGUMENTS and resolve all config ───────────────────
_raw_args = "$ARGUMENTS"

def _parse_kv(args_str, key):
    m = re.search(rf'(?:^|[\s,]){key}=([^\s]+)', args_str, re.IGNORECASE)
    if not m: return None
    return [e.strip() for e in m.group(1).split(',') if e.strip()]

def _extract_sheet_file_id(raw):
    if not raw: return None
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', raw)
    if m: return m.group(1)
    if re.fullmatch(r'[a-zA-Z0-9_-]{20,60}', raw.strip()): return raw.strip()
    return None

# Strip key=value pairs, extract URL first, then sprint name (handles spaces in sprint names)
_no_kv = re.sub(r'\b\w+=[^\s]+', '', _raw_args).strip()
_url_match = re.search(r'https?://\S+', _no_kv)
_pos_tc_url = _url_match.group(0) if _url_match else None
_no_url = (_no_kv[:_url_match.start()] + _no_kv[_url_match.end():]).strip() if _url_match else _no_kv
_date_like = re.compile(r'^\d{4}-\d{2}-\d{2}$|^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', re.IGNORECASE)
_remaining = _no_url.split()
_sprint_tokens = [t for t in _remaining if not _date_like.match(t)]
_date_tokens   = [t for t in _remaining if _date_like.match(t)]
_pos_sprint = ' '.join(_sprint_tokens) if _sprint_tokens else None
_pos_start  = _date_tokens[0] if len(_date_tokens) > 0 else None
_pos_end    = _date_tokens[1] if len(_date_tokens) > 1 else None

def _env(key, default=None): return env_cfg.get(key) or default
def _last(key, default=None): return last_run_cfg.get(key) or default

# Priority: $ARGUMENTS > .last_run.json > .env > built-in defaults
SPRINT_NAME = _pos_sprint or _last("SPRINT_NAME") or _env("SPRINT_NAME")
START_DATE  = _pos_start  or _last("START_DATE")  or _env("START_DATE")
END_DATE    = _pos_end    or _last("END_DATE")    or _env("END_DATE")
_tc_url_raw = _pos_tc_url or _last("TC_SHEET_URL") or _env("TC_SHEET_URL")
_from_kv    = _parse_kv(_raw_args, "from")
_to_kv      = _parse_kv(_raw_args, "to")
_cc_kv      = _parse_kv(_raw_args, "cc")
FROM_EMAIL  = (_from_kv[0] if _from_kv else None) or _last("FROM_EMAIL") or _env("FROM_EMAIL") or None
TO_EMAILS   = _to_kv or ([e.strip() for e in (_last("TO_EMAILS") or _env("TO_EMAILS","")).split(',') if e.strip()] or None)
CC_EMAILS   = _cc_kv or ([e.strip() for e in (_last("CC_EMAILS") or _env("CC_EMAILS","")).split(',') if e.strip()] or None)

_DEFAULT_REPORT_FOLDER_ID = "1vdPP7M8QBA3Mj8qhSfSs_runBc8YBCQP"
_folder_raw = _env("REPORT_FOLDER_ID", "")
_folder_m   = re.search(r'/folders/([a-zA-Z0-9_-]{20,})', _folder_raw or "")
if _folder_m:
    REPORT_FOLDER_ID = _folder_m.group(1)
elif _folder_raw and re.fullmatch(r'[a-zA-Z0-9_-]{20,60}', _folder_raw.strip()):
    REPORT_FOLDER_ID = _folder_raw.strip()
else:
    REPORT_FOLDER_ID = _DEFAULT_REPORT_FOLDER_ID

missing = []
if not SPRINT_NAME: missing.append("SPRINT_NAME  : <e.g. F27-Sprint 7>")
if missing:
    print("\u26a0 Missing required inputs. Please provide (or add to .env):")
    for m in missing: print(f"   {m}")
    raise SystemExit(1)

_sn = SPRINT_NAME.upper()
_proj_m = re.search(r'PRODOPS|PRDOPS|SFCPQ|NPI|COLLECTOR|COUPA|MKTG|MARKETING|NETSUITE|CUSTOMERSUPPORT', _sn)
if _proj_m:
    PROJECT = _proj_m.group(0)
    PROJECT = {"PRODOPS":"PRDOPS","MARKETING":"MKTG","CUSTOMERSUPPORT":"CS"}.get(PROJECT, PROJECT)
else:
    # Derive project from TC sheet file ID (covers tab-name format like "F27-Sprint 7")
    _TC_FILE_PROJECT_MAP = {
        "1lBhXjFci29i-RAY1MkU5ljMF12lUg_uk3mgJhKhJPM8": "PRDOPS",
        "12xxjFEe2aeOk1X7z2vQalkOEp6fr9_5BMhKRy3C5hgw": "MKTG",
        "165DKk33NS-NqO-jciKBPM-ym0l6RtMV6QZc4o8pIRbw": "CS",
    }
    _tc_fid_raw = _extract_sheet_file_id(_tc_url_raw or "")
    PROJECT = _TC_FILE_PROJECT_MAP.get(_tc_fid_raw or "", _sn.split('_')[0].split('-')[0])
_no_m = re.search(r'SPRINT[\s_-]?(\d+)|SP(\d+)', _sn)
SPRINT_NO = (_no_m.group(1) or _no_m.group(2)) if _no_m else "?"

# ── Auto-fetch START_DATE / END_DATE from JIRA if not provided ────────────────
if not START_DATE or not END_DATE:
    try:
        _conf2 = (Path.home() / ".mcp.conf.yaml").read_text(encoding="utf-8")
        _ju2 = re.search(r'jira:.*?user:\s*([^\s\n]+)', _conf2, re.DOTALL)
        _jt2 = re.search(r'jira:.*?token:\s*([^\s\n]+)', _conf2, re.DOTALL)
        _js2 = re.search(r"jira:.*?url:\s*['\"]([^'\"]+)['\"]", _conf2, re.DOTALL)
        _ju2_val   = _ju2.group(1).strip("'\"") if _ju2 else ""
        _jt2_val   = _jt2.group(1).strip("'\"") if _jt2 else ""
        _js2_val   = _js2.group(1).strip("'\"") if _js2 else "https://rubrik.atlassian.net"
        _jb64_dates = base64.b64encode(f"{_ju2_val}:{_jt2_val}".encode()).decode()
        def _jira_get_dates(url):
            r = urllib.request.Request(url, headers={"Authorization": f"Basic {_jb64_dates}", "Accept": "application/json"})
            return json.loads(urllib.request.urlopen(r, context=ctx).read())
        def _fmt_date(d):
            try:
                import re as _re2
                d_str = (d or "")
                if 'T' in d_str:
                    d_clean = _re2.sub(r'\.\d+', '', d_str).replace('Z', '+00:00')
                    dt = datetime.datetime.fromisoformat(d_clean)
                    if dt.tzinfo is not None:
                        dt = dt.astimezone()
                    return dt.strftime("%b %-d, %Y")
                return datetime.datetime.strptime(d_str[:10], "%Y-%m-%d").strftime("%b %-d, %Y")
            except: return (d or "")[:10]
        _boards2 = _jira_get_dates(f"{_js2_val}/rest/agile/1.0/board?projectKeyOrId={PROJECT}&maxResults=5")
        _bid2 = (_boards2.get("values") or [{}])[0].get("id")
        if _bid2 and SPRINT_NO != "?":
            _sprints2 = _jira_get_dates(f"{_js2_val}/rest/agile/1.0/board/{_bid2}/sprint?state=closed,active&maxResults=50")
            for _sp2 in (_sprints2.get("values") or []):
                _nm2 = re.search(r'SP(\d+)', _sp2.get("name", ""), re.IGNORECASE)
                if _nm2 and int(_nm2.group(1)) == int(SPRINT_NO):
                    if not START_DATE: START_DATE = _fmt_date(_sp2.get("startDate"))
                    if not END_DATE:   END_DATE   = _fmt_date(_sp2.get("endDate"))
                    print(f"  Auto-fetched dates from JIRA: {START_DATE} → {END_DATE}")
                    break
    except Exception as _de:
        print(f"  ⚠ Could not auto-fetch dates from JIRA: {_de}")
    if not START_DATE: START_DATE = ""
    if not END_DATE:   END_DATE   = ""

DEFAULT_TC_SHEET_FILE_ID  = "1lBhXjFci29i-RAY1MkU5ljMF12lUg_uk3mgJhKhJPM8"
DEFAULT_TC_SHEET_BASE_URL = "https://docs.google.com/spreadsheets/d/1lBhXjFci29i-RAY1MkU5ljMF12lUg_uk3mgJhKhJPM8/edit"
_user_tc_id = _extract_sheet_file_id(_tc_url_raw)
if _user_tc_id:
    TC_SHEET_FILE_ID  = _user_tc_id
    TC_SHEET_BASE_URL = f"https://docs.google.com/spreadsheets/d/{_user_tc_id}/edit"
    _tc_src = "user-supplied"
else:
    TC_SHEET_FILE_ID  = DEFAULT_TC_SHEET_FILE_ID
    TC_SHEET_BASE_URL = DEFAULT_TC_SHEET_BASE_URL
    _tc_src = "default"

print(f"""
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
Sprint QA Report \u2014 resolved config
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
Sprint     : {SPRINT_NAME}
Dates      : {START_DATE} \u2192 {END_DATE}
Project    : {PROJECT}  |  Sprint No: {SPRINT_NO}
TC Sheet   : {TC_SHEET_BASE_URL}  [{_tc_src}]
Email From : {FROM_EMAIL or "(authenticated account)"}
Email To   : {", ".join(TO_EMAILS) if TO_EMAILS else "(will ask after upload)"}
Email CC   : {", ".join(CC_EMAILS) if CC_EMAILS else "(none)"}
Report Folder: https://drive.google.com/drive/folders/{REPORT_FOLDER_ID}
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
""")

# ── 3: Load JIRA credentials from ~/.mcp.conf.yaml (no yaml module needed) ──
_conf = (Path.home() / ".mcp.conf.yaml").read_text(encoding="utf-8")
_ju = re.search(r'jira:.*?user:\s*([^\s\n]+)', _conf, re.DOTALL)
_jt = re.search(r'jira:.*?token:\s*([^\s\n]+)', _conf, re.DOTALL)
_js = re.search(r"jira:.*?url:\s*['"]([^'"]+)['"]", _conf, re.DOTALL)
JIRA_USER   = _ju.group(1).strip("'\"") if _ju else ""
JIRA_TOKEN  = _jt.group(1).strip("'\"") if _jt else ""
JIRA_SERVER = _js.group(1).strip("'\"") if _js else "https://rubrik.atlassian.net"
_jira_b64   = base64.b64encode(f"{JIRA_USER}:{JIRA_TOKEN}".encode()).decode()

def jira_search(jql, max_results=100):
    body = json.dumps({"jql": jql, "maxResults": max_results,
        "fields": ["summary","status","priority","assignee","issuetype","issuelinks","parent","customfield_10014"]}).encode()
    req = urllib.request.Request(f"{JIRA_SERVER}/rest/api/3/search/jql", data=body, method="POST",
        headers={"Authorization": f"Basic {_jira_b64}",
                 "Content-Type": "application/json", "Accept": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, context=ctx).read()).get("issues", [])
    except urllib.error.HTTPError as e:
        print(f"  JIRA error: {e.code} — {e.read().decode()[:200]}")
        return []

def jira_get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {_jira_b64}", "Accept": "application/json"})
    return json.loads(urllib.request.urlopen(req, context=ctx).read())

# ── 4: Query JIRA stories ─────────────────────────────────────────
print(f"Querying JIRA stories for {PROJECT} sprint {SPRINT_NAME}...")
_proj_alt = PROJECT[:-1] if PROJECT.endswith("G") else PROJECT + "G"
RESOLVED_SPRINT_NAME = SPRINT_NAME  # may be updated by Board API fallback
story_issues = jira_search(f'project = {PROJECT} AND sprint = "{SPRINT_NAME}" AND issuetype = Story')
if not story_issues:
    print(f"  No results for {PROJECT}, trying {_proj_alt}...")
    story_issues = jira_search(f'project = {_proj_alt} AND sprint = "{SPRINT_NAME}" AND issuetype = Story')
if not story_issues:
    print("  Using Board API to discover actual sprint name...")
    try:
        def _jira_get(url):
            r2 = urllib.request.Request(url, headers={"Authorization": f"Basic {_jira_b64}", "Accept": "application/json"})
            return json.loads(urllib.request.urlopen(r2, context=ctx).read())
        _boards = _jira_get(f"{JIRA_SERVER}/rest/agile/1.0/board?projectKeyOrId={PROJECT}&maxResults=10")
        _board_id = _boards["values"][0]["id"] if _boards.get("values") else None
        if _board_id:
            print(f"  Board ID: {_board_id}")
            _sprints_data = _jira_get(f"{JIRA_SERVER}/rest/agile/1.0/board/{_board_id}/sprint?state=closed,active&maxResults=50")
            # Prefer ACTIVE sprint over closed; use sprint ID in JQL (avoids name-format mismatch)
            _best_name = None; _best_id = None; _best_active = False
            for _sp in (_sprints_data.get("values") or []):
                _sn_sp  = _sp.get("name", "")
                _sp_id  = _sp.get("id")
                _sp_state = _sp.get("state", "")
                _sn_norm  = _sn_sp.upper().replace("-","").replace("_","").replace(" ","")
                _has_num  = SPRINT_NO != "?" and (
                    f"SP{SPRINT_NO}" in _sn_norm or
                    f"SPRINT{SPRINT_NO}" in _sn_norm)
                if _has_num:
                    _is_active = _sp_state.lower() == "active"
                    # Always prefer active sprint; within same state, first match wins
                    if _best_id is None or (_is_active and not _best_active):
                        _best_name   = _sn_sp
                        _best_id     = _sp_id
                        _best_active = _is_active
            if _best_id:
                print(f"  Board API matched sprint: '{_best_name}' (id={_best_id}, state={'active' if _best_active else 'closed'})")
                RESOLVED_SPRINT_NAME = _best_name
                # Use sprint ID in JQL — immune to sprint name format variations
                story_issues = jira_search(f'project = {PROJECT} AND sprint = {_best_id} AND issuetype = Story')
                if not story_issues:
                    story_issues = jira_search(f'project = {_proj_alt} AND sprint = {_best_id} AND issuetype = Story')
    except Exception as _be:
        print(f"  Board API fallback failed: {_be}")
if not story_issues:
    print("  Trying openSprints() final fallback...")
    story_issues = jira_search(f'project = {PROJECT} AND sprint in openSprints() AND issuetype = Story')
print(f"  Found {len(story_issues)} stories")

# ── 5: Query JIRA bugs — use RESOLVED_SPRINT_NAME so stories and bugs are scoped to the same sprint ──
print(f"Querying JIRA bugs (sprint: '{RESOLVED_SPRINT_NAME}')...")
# Use sprint ID if available (set by Board API fallback above) — same reliability fix as stories
_resolved_sprint_id = locals().get("_best_id", None)
if _resolved_sprint_id:
    bug_issues = jira_search(f'project = {PROJECT} AND sprint = {_resolved_sprint_id} AND issuetype = Bug')
    if not bug_issues:
        bug_issues = jira_search(f'project = {_proj_alt} AND sprint = {_resolved_sprint_id} AND issuetype = Bug')
else:
    bug_issues = jira_search(f'project = {PROJECT} AND sprint = "{RESOLVED_SPRINT_NAME}" AND issuetype = Bug')
    if not bug_issues:
        bug_issues = jira_search(f'project = {_proj_alt} AND sprint = "{RESOLVED_SPRINT_NAME}" AND issuetype = Bug')
    if not bug_issues and RESOLVED_SPRINT_NAME != SPRINT_NAME:
        bug_issues = jira_search(f'project = {PROJECT} AND sprint = "{SPRINT_NAME}" AND issuetype = Bug')
if not bug_issues:
    from datetime import datetime as _dt
    def _to_jira_date(s):
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
            try: return _dt.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
            except: pass
        return s.strip()
    sd_jira = _to_jira_date(START_DATE); ed_jira = _to_jira_date(END_DATE)
    print(f"  No sprint-scoped bugs; trying date range {sd_jira}–{ed_jira}...")
    bug_issues = jira_search(f'project = {PROJECT} AND issuetype = Bug AND created >= "{sd_jira}" AND created <= "{ed_jira}"')
print(f"  Found {len(bug_issues)} bugs")

# ── 6: Parse fields ───────────────────────────────────────────────
PRIORITY_MAP = {"Highest":"P0","Blocker":"P0","High":"P1","Medium":"P2","Low":"P3","Lowest":"P3"}
STATUS_MAP = {
    "to do":"Not Started","open":"Not Started","backlog":"Not Started",
    "in progress":"In QA","in review":"In QA","ready for qa":"In QA","qa in progress":"In QA",
    "qa done":"QA Completed","qa passed":"QA Completed","qa completed":"QA Completed",
    "ready for uat":"Ready for UAT","ready for uat deployment":"Ready for UAT",
    "uat in progress":"UAT In Progress","uat testing":"UAT In Progress",
    "done":"UAT Completed / Done","closed":"UAT Completed / Done","resolved":"UAT Completed / Done",
    "uat completed":"UAT Completed / Done","released":"UAT Completed / Done",
    "business signed-off":"UAT Completed / Done","no action":"No Action",
}
raw_stories = []
for iss in story_issues:
    f = iss.get("fields", {})
    status_raw = (f.get("status") or {}).get("name", "")
    raw_stories.append({
        "key": iss["key"], "summary": f.get("summary",""),
        "status": status_raw, "qa_category": STATUS_MAP.get(status_raw.lower().strip(), "In QA"),
        "priority": PRIORITY_MAP.get((f.get("priority") or {}).get("name",""), "P2"),
        "assignee": ((f.get("assignee") or {}).get("displayName") or "Unassigned"),
    })
raw_bugs = []
for iss in bug_issues:
    f = iss.get("fields", {}); summary = f.get("summary","")
    status_raw = (f.get("status") or {}).get("name","")
    raw_bugs.append({
        "key": iss["key"], "summary": summary, "status": status_raw,
        "priority": PRIORITY_MAP.get((f.get("priority") or {}).get("name",""), "P2"),
        "leaked": "uat bug" in summary.lower() or "uat defect" in summary.lower(),
    })

# ── 7: Load Drive OAuth token ──────────────────────────────────────
with open(Path.home() / ".gdrive-mcp-token.json") as f:
    _dtok = json.load(f)
if _dtok.get("expires_at", 0) < datetime.datetime.now().timestamp() + 60:
    _tr = urllib.request.Request("https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode({"client_id":_dtok["client_id"],"client_secret":_dtok["client_secret"],
            "refresh_token":_dtok["refresh_token"],"grant_type":"refresh_token"}).encode(), method="POST",
        headers={"Content-Type":"application/x-www-form-urlencoded"})
    _tv = json.loads(urllib.request.urlopen(_tr, context=ctx).read())
    _dtok["access_token"] = _tv["access_token"]
    _dtok["expires_at"] = datetime.datetime.now().timestamp() + _tv.get("expires_in", 3600)
    open(Path.home() / ".gdrive-mcp-token.json","w").write(json.dumps(_dtok))
DRIVE_TOKEN = _dtok["access_token"]

# ── 8: Find matching TC sheet tab via Sheets REST API ─────────────
print(f"Listing TC sheet tabs...")
_tabs_req = urllib.request.Request(
    f"https://sheets.googleapis.com/v4/spreadsheets/{TC_SHEET_FILE_ID}?fields=sheets.properties",
    headers={"Authorization": f"Bearer {DRIVE_TOKEN}"})
try:
    _tabs = [(s["properties"]["title"], str(s["properties"]["sheetId"]))
             for s in json.loads(urllib.request.urlopen(_tabs_req, context=ctx).read()).get("sheets",[])]
except Exception as e:
    print(f"  Could not list tabs: {e}"); _tabs = []

FOUND_TAB = None; FOUND_GID = None; _sn_lower = SPRINT_NAME.lower()
for _title, _gid in _tabs:
    if _title == SPRINT_NAME: FOUND_TAB, FOUND_GID = _title, _gid; break
if not FOUND_TAB:
    for _title, _gid in _tabs:
        if _title.lower() == _sn_lower: FOUND_TAB, FOUND_GID = _title, _gid; break
if not FOUND_TAB:
    for _title, _gid in _tabs:
        if _sn_lower in _title.lower() or _title.lower() in _sn_lower:
            FOUND_TAB, FOUND_GID = _title, _gid; break
if not FOUND_TAB and SPRINT_NO != "?":
    _fy_m = re.search(r'FY(\d+)', _sn_lower); _fy = _fy_m.group(1) if _fy_m else ""
    for _title, _gid in _tabs:
        _tl = _title.lower()
        if SPRINT_NO in _tl and (_fy in _tl or not _fy): FOUND_TAB, FOUND_GID = _title, _gid; break
TC_SPRINT_TAB_URL = f"{TC_SHEET_BASE_URL}#gid={FOUND_GID}" if FOUND_GID else TC_SHEET_BASE_URL
if FOUND_TAB: print(f"  Matched tab: '{FOUND_TAB}' (gid={FOUND_GID})")
else: print(f"  \u26a0 No matching tab for '{SPRINT_NAME}' \u2014 TC counts will be 0")

# ── 9: Download and parse TC sheet tab as CSV ─────────────────────
story_tcs = {}; tc_rows = []
if FOUND_GID:
    print(f"Downloading TC data...")
    _csv_url = f"https://docs.google.com/spreadsheets/d/{TC_SHEET_FILE_ID}/export?format=csv&gid={FOUND_GID}"
    _csv_req = urllib.request.Request(_csv_url, headers={"Authorization": f"Bearer {DRIVE_TOKEN}"})
    try:
        _csv_content = urllib.request.urlopen(_csv_req, context=ctx).read().decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(_csv_content, newline=""))
        next(reader)
        for row in reader:
            if len(row) < 12: continue
            ticket = row[1].strip(); status = row[11].strip()
            if not ticket: continue
            story_tcs.setdefault(ticket, {"total":0,"pass":0,"fail":0,"blocked":0,"in_progress":0})
            story_tcs[ticket]["total"] += 1
            sl = status.lower()
            if sl == "pass":     story_tcs[ticket]["pass"] += 1
            elif sl == "fail":   story_tcs[ticket]["fail"] += 1
            elif "block" in sl:  story_tcs[ticket]["blocked"] += 1
            else:                story_tcs[ticket]["in_progress"] += 1
            tc_rows.append({
                "story":     ticket,
                "tc_id":     row[3].strip() if len(row) > 3 else "",
                "tc_name":   (row[4].strip() if len(row) > 4 else "")[:200],
                "tc_desc":   (row[5].strip() if len(row) > 5 else "")[:300],
                "expected":  (row[9].strip() if len(row) > 9 else "")[:200],
                "status":    status,
                "tested_by": row[12].strip() if len(row) > 12 else "",
            })
        print(f"  Parsed {len(tc_rows)} TC rows across {len(story_tcs)} stories")
    except Exception as e:
        print(f"  \u26a0 Could not download TC data: {e}")

# ── 10: Build STORY_DATA and classify ────────────────────────────
STORY_DATA = []
for s in raw_stories:
    if s["qa_category"] == "No Action": continue
    tcs = story_tcs.get(s["key"], {"total":0,"pass":0,"fail":0,"blocked":0,"in_progress":0})
    STORY_DATA.append({
        "key": s["key"], "summary": s["summary"],
        "status": s["status"], "qa_category": s["qa_category"],
        "priority": s["priority"], "assignee": s["assignee"],
        "total_tcs": tcs["total"], "pass": tcs["pass"], "fail": tcs["fail"],
        "blocked": tcs["blocked"], "in_progress": tcs["in_progress"],
    })
STORY_DATA.sort(key=lambda x: x["key"])

# ── 11: Compute metrics ───────────────────────────────────────────
TOTAL_STORIES = len(STORY_DATA)
TOTAL_TCS     = sum(s["total_tcs"] for s in STORY_DATA)
TOTAL_PASS    = sum(s["pass"]      for s in STORY_DATA)
TOTAL_FAIL    = sum(s["fail"]      for s in STORY_DATA)
TOTAL_BLOCKED = sum(s["blocked"]   for s in STORY_DATA)
TOTAL_IN_PROG = sum(s["in_progress"] for s in STORY_DATA)

NOT_STARTED   = sum(1 for s in STORY_DATA if s["qa_category"] == "Not Started")
IN_QA         = sum(1 for s in STORY_DATA if s["qa_category"] == "In QA")
QA_COMPLETED  = sum(1 for s in STORY_DATA if s["qa_category"] == "QA Completed")
READY_UAT     = sum(1 for s in STORY_DATA if s["qa_category"] == "Ready for UAT")
UAT_COMPLETED = sum(1 for s in STORY_DATA if s["qa_category"] == "UAT Completed / Done")
QA_QUALIFIED  = TOTAL_STORIES

REJECTED_BUGS = sum(1 for b in raw_bugs if b["status"].lower() == "no action")
_active_bugs  = [b for b in raw_bugs if b["status"].lower() != "no action"]
TOTAL_BUGS    = len(_active_bugs)
LEAKED_BUGS   = sum(1 for b in _active_bugs if b["leaked"])

EXEC_PCT       = TOTAL_PASS / TOTAL_TCS * 100 if TOTAL_TCS else 0.0
DEFECT_DENSITY = TOTAL_BUGS / TOTAL_TCS * 100 if TOTAL_TCS else 0.0
DEFECT_LEAKAGE = LEAKED_BUGS / TOTAL_BUGS * 100 if TOTAL_BUGS else 0.0
REJECTION_RATE = REJECTED_BUGS / TOTAL_BUGS * 100 if TOTAL_BUGS else 0.0

if DEFECT_DENSITY < 15 and DEFECT_LEAKAGE == 0:   OVERALL_STATUS = "GREEN"
elif DEFECT_DENSITY <= 25 or DEFECT_LEAKAGE <= 5: OVERALL_STATUS = "YELLOW"
else:                                               OVERALL_STATUS = "RED"

_pmap = {p:{"total":0,"closed":0,"leaked":0} for p in ("P0","P1","P2","P3")}
for b in _active_bugs:
    p = b.get("priority","P2")
    if p not in _pmap: p = "P2"
    _pmap[p]["total"] += 1
    if b["status"].lower() in ("resolved","closed","done"): _pmap[p]["closed"] += 1
    if b["leaked"]: _pmap[p]["leaked"] += 1
P0=_pmap["P0"]; P1=_pmap["P1"]; P2=_pmap["P2"]; P3=_pmap["P3"]
P0_o=P0["total"]-P0["closed"]; P0_c=P0["closed"]
P1_o=P1["total"]-P1["closed"]; P1_c=P1["closed"]
P2_o=P2["total"]-P2["closed"]; P2_c=P2["closed"]
P3_o=P3["total"]-P3["closed"]; P3_c=P3["closed"]

bug_by_story = {}
_seen_bugs   = set()  # global dedup — each bug key counted at most once across all stories
# Query JIRA per story for linked bugs — parallel with ThreadPoolExecutor for speed
def _fetch_story_bugs(story_key):
    bug_keys = set()
    try:
        _issue_data = jira_get(f"{JIRA_SERVER}/rest/api/2/issue/{story_key}?fields=issuelinks,subtasks")
        _f = _issue_data.get("fields", {})
        for _link in (_f.get("issuelinks") or []):
            for _dir in ("inwardIssue", "outwardIssue"):
                _linked = _link.get(_dir)
                if _linked:
                    _lt = (_linked.get("fields", {}).get("issuetype", {}).get("name", "")).lower()
                    if "bug" in _lt or "defect" in _lt:
                        bug_keys.add(_linked["key"])
        for _sub in (_f.get("subtasks") or []):
            _st = (_sub.get("fields", {}).get("issuetype", {}).get("name", "")).lower()
            if "bug" in _st or "defect" in _st:
                bug_keys.add(_sub["key"])
    except Exception:
        pass
    return story_key, bug_keys

_bug_results = {}
with ThreadPoolExecutor(max_workers=8) as _executor:
    _futures = {_executor.submit(_fetch_story_bugs, s["key"]): s["key"] for s in STORY_DATA}
    for _future in as_completed(_futures):
        _sk, _bk = _future.result()
        _bug_results[_sk] = _bk

# Apply global dedup in story-key order (deterministic)
for _story in sorted(STORY_DATA, key=lambda x: x["key"]):
    _sk = _story["key"]
    _new = sorted(_bug_results.get(_sk, set()) - _seen_bugs)
    if _new:
        bug_by_story[_sk] = len(_new)
        _seen_bugs.update(_new)

print(f"Stories: {TOTAL_STORIES} | TCs: {TOTAL_TCS} Pass:{TOTAL_PASS} Fail:{TOTAL_FAIL}")
print(f"Bugs: {TOTAL_BUGS} (P0:{P0['total']} P1:{P1['total']} P2:{P2['total']} P3:{P3['total']}) | Rejected:{REJECTED_BUGS}")
print(f"Exec: {EXEC_PCT:.1f}% | Density: {DEFECT_DENSITY:.1f}% | Leakage: {DEFECT_LEAKAGE:.1f}% | Status: {OVERALL_STATUS}")

# ── 12: Save all data to /tmp/sprint_data.json ────────────────────
_sprint_data = {
    "SPRINT_NAME": SPRINT_NAME, "START_DATE": START_DATE, "END_DATE": END_DATE,
    "SPRINT_NO": SPRINT_NO, "PROJECT": PROJECT,
    "TC_SHEET_BASE_URL": TC_SHEET_BASE_URL, "TC_SPRINT_TAB_URL": TC_SPRINT_TAB_URL,
    "FOUND_TAB": FOUND_TAB or "", "REPORT_FOLDER_ID": REPORT_FOLDER_ID,
    "FROM_EMAIL": FROM_EMAIL, "TO_EMAILS": TO_EMAILS, "CC_EMAILS": CC_EMAILS,
    "TOTAL_STORIES": TOTAL_STORIES, "TOTAL_TCS": TOTAL_TCS,
    "TOTAL_PASS": TOTAL_PASS, "TOTAL_FAIL": TOTAL_FAIL,
    "TOTAL_BLOCKED": TOTAL_BLOCKED, "TOTAL_IN_PROG": TOTAL_IN_PROG,
    "NOT_STARTED": NOT_STARTED, "IN_QA": IN_QA, "QA_COMPLETED": QA_COMPLETED,
    "READY_UAT": READY_UAT, "UAT_COMPLETED": UAT_COMPLETED, "QA_QUALIFIED": QA_QUALIFIED,
    "TOTAL_BUGS": TOTAL_BUGS, "LEAKED_BUGS": LEAKED_BUGS, "REJECTED_BUGS": REJECTED_BUGS,
    "EXEC_PCT": EXEC_PCT, "DEFECT_DENSITY": DEFECT_DENSITY,
    "DEFECT_LEAKAGE": DEFECT_LEAKAGE, "REJECTION_RATE": REJECTION_RATE,
    "OVERALL_STATUS": OVERALL_STATUS,
    "P0": P0, "P1": P1, "P2": P2, "P3": P3,
    "P0_o": P0_o, "P0_c": P0_c, "P1_o": P1_o, "P1_c": P1_c,
    "P2_o": P2_o, "P2_c": P2_c, "P3_o": P3_o, "P3_c": P3_c,
    "STORY_DATA": STORY_DATA, "tc_rows": tc_rows, "bug_by_story": bug_by_story,
}
Path("/tmp/sprint_data.json").write_text(json.dumps(_sprint_data, indent=2))
print("\u2705 Sprint data saved to /tmp/sprint_data.json \u2014 ready for Script A and B")
```

---

## STEP 6 — Generate xlsx Report + Upload to Drive

> **Clones the master template xlsx (`~/.claude/sprint_qa_master_template.xlsx`) and populates it with sprint data using openpyxl. Output: a properly formatted `.xlsx` file matching the exact Rubrik QA report template.**
> **PERFORMANCE: Step 6 = exactly 2 python3 calls: Script A (ensure template cached + copy working file) + Script B (populate xlsx + upload to Drive). Never split into more calls.**

### Script A — Ensure template + copy working file (python3 call #3)

> Loads master template in priority order: (1) repo skill directory `sprint_qa_master_template.xlsx`, (2) `~/.claude/sprint_qa_master_template.xlsx` cache, (3) download from Drive (`TEMPLATE_DRIVE_FILE_ID`). Then copy to `/tmp/sprint_qa_working.xlsx`.

```python
# Script A — ensure master template cached locally, copy to working path
import json, ssl, urllib.request, urllib.parse, shutil, datetime
from pathlib import Path

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode    = ssl.CERT_NONE

# ── Refresh Drive token ──────────────────────────────────────────
td = json.loads(Path.home().joinpath(".gdrive-mcp-token.json").read_text("utf-8"))
body = urllib.parse.urlencode({
    "client_id": td["client_id"], "client_secret": td["client_secret"],
    "refresh_token": td["refresh_token"], "grant_type": "refresh_token",
}).encode()
rv = json.loads(urllib.request.urlopen(
    urllib.request.Request(td.get("token_uri","https://oauth2.googleapis.com/token"),
        data=body, headers={"Content-Type":"application/x-www-form-urlencoded"}, method="POST"),
    context=ctx).read())
ACCESS_TOKEN = rv.get("access_token", td.get("access_token",""))
td["access_token"] = td["token"] = ACCESS_TOKEN
td["expires_at"] = datetime.datetime.now().timestamp() + rv.get("expires_in", 3600)
Path.home().joinpath(".gdrive-mcp-token.json").write_text(json.dumps(td))

TEMPLATE_DRIVE_FILE_ID = "1Xa6eoVU4hXgZAaeApuOIXhK2lC5YG-Pr"
TEMPLATE_LOCAL = Path.home() / ".claude" / "sprint_qa_master_template.xlsx"
WORKING_PATH   = Path("/tmp/sprint_qa_working.xlsx")

# Resolve skill directory (repo-bundled template takes priority)
import subprocess as _sp_a, os as _os_a
try:
    _gr_a = _sp_a.check_output(["git","rev-parse","--show-toplevel"],text=True,cwd=_os_a.getcwd()).strip()
    SKILL_DIR_A = Path(_gr_a) / ".claude" / "skills" / "sprint-qa-report"
    if not SKILL_DIR_A.exists(): raise FileNotFoundError
except Exception:
    SKILL_DIR_A = None

SKILL_TEMPLATE = (SKILL_DIR_A / "sprint_qa_master_template.xlsx") if SKILL_DIR_A else None

if SKILL_TEMPLATE and SKILL_TEMPLATE.exists():
    shutil.copy2(SKILL_TEMPLATE, WORKING_PATH)
    print(f"  Template loaded from repo: {SKILL_TEMPLATE} ({SKILL_TEMPLATE.stat().st_size:,} bytes)")
elif TEMPLATE_LOCAL.exists():
    shutil.copy2(TEMPLATE_LOCAL, WORKING_PATH)
    print(f"  Template loaded from cache: {TEMPLATE_LOCAL} ({TEMPLATE_LOCAL.stat().st_size:,} bytes)")
else:
    print("Downloading master template from Drive...")
    data = urllib.request.urlopen(
        urllib.request.Request(
            f"https://www.googleapis.com/drive/v3/files/{TEMPLATE_DRIVE_FILE_ID}?alt=media",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}),
        context=ctx).read()
    TEMPLATE_LOCAL.write_bytes(data)
    shutil.copy2(TEMPLATE_LOCAL, WORKING_PATH)
    print(f"  Downloaded {len(data):,} bytes → {TEMPLATE_LOCAL}")

print(f"✅ Working copy: {WORKING_PATH}")

sd = json.loads(Path("/tmp/sprint_data.json").read_text())
print(f"   Sprint: {sd['SPRINT_NAME']} | Stories: {len(sd['STORY_DATA'])} | TCs: {len(sd['tc_rows'])}")
```

### Script B — Populate xlsx + upload to Drive (python3 call #4)

> Load `/tmp/sprint_qa_working.xlsx`, populate all 4 tabs with sprint data using openpyxl, save final file, upload to Drive. Saves `xlsx_file_id`, `xlsx_link`, `xlsx_local_path` to `/tmp/sprint_data.json`.

**Template structure constants (Sprint 3 master — do not change):**
- Story rows start at row 4; master had 8 story rows (rows 4–11), totals at row 12, TC header at row 14, TC data from row 15.
- Sheet1 had 6 story rows (rows 12–17), totals at row 18.
- Script inserts extra rows dynamically if the current sprint has more stories than the master.

```python
# Script B — populate xlsx with openpyxl + upload to Drive
import json, ssl, urllib.request, urllib.parse, copy, datetime, re
from pathlib import Path
from collections import OrderedDict
import openpyxl
from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode    = ssl.CERT_NONE

# ── Load sprint data ──────────────────────────────────────────────
sd           = json.loads(Path("/tmp/sprint_data.json").read_text("utf-8"))
SPRINT_NAME  = sd["SPRINT_NAME"]
START_DATE   = sd["START_DATE"]
END_DATE     = sd["END_DATE"]
SPRINT_NO    = sd.get("SPRINT_NO", "?")
PROJECT      = sd.get("PROJECT", "PRDOPS")
story_data   = sd.get("STORY_DATA", [])
tc_rows      = sd.get("tc_rows", [])
REPORT_FOLDER_ID = sd.get("REPORT_FOLDER_ID", "1vdPP7M8QBA3Mj8qhSfSs_runBc8YBCQP")
FROM_EMAIL   = sd.get("FROM_EMAIL", "")
TO_EMAILS    = sd.get("TO_EMAILS", [])
CC_EMAILS    = sd.get("CC_EMAILS", [])

# ── Style helpers ─────────────────────────────────────────────────
def mk_fill(h): return PatternFill("solid", fgColor=h)
def mk_font(bold=False, color="000000", size=10): return Font(bold=bold, color=color, size=size)
def mk_align(h="left", v="center", wrap=False): return Alignment(horizontal=h, vertical=v, wrap_text=wrap)
def safe_set(cell, value):
    if not isinstance(cell, MergedCell): cell.value = value

GREY_FILL  = "D0CECE"
ODD_ROW    = "F6F8F9"
LIGHT_BLUE = "9DC3E6"
PASS_GREEN = "6AA84F"

# ── Load workbook ─────────────────────────────────────────────────
wb = load_workbook("/tmp/sprint_qa_working.xlsx")

# ═══════════════════════════════════════════════════════════════════
# TAB: TestCase Coverage
# ═══════════════════════════════════════════════════════════════════
ws_tc = wb["TestCase Coverage"]
N = len(story_data)

# Template row positions (Sprint 3 master — do not change)
ORIG_STORY_COUNT   = 8
ORIG_TOTALS_ROW    = 12
ORIG_TC_HDR_ROW    = 14
ORIG_TC_DATA_START = 15

# ── Capture TC header row styles before clearing ──────────────────
tc_hdr_styles = {}
for ci in range(1, 11):
    cell = ws_tc.cell(ORIG_TC_HDR_ROW, ci)
    if not isinstance(cell, MergedCell):
        tc_hdr_styles[ci] = {
            "font":      copy.copy(cell.font),
            "fill":      copy.copy(cell.fill),
            "alignment": copy.copy(cell.alignment),
            "value":     cell.value,
        }

# ── Remove merges from rows 4+ ────────────────────────────────────
merges_rm = [str(m) for m in list(ws_tc.merged_cells.ranges) if m.min_row >= 4]
for m in merges_rm:
    ws_tc.merged_cells.remove(m)

# ── Clear all rows 4 to max_row ───────────────────────────────────
for ri in range(4, ws_tc.max_row + 1):
    for ci in range(1, 15):
        cell = ws_tc.cell(ri, ci)
        if not isinstance(cell, MergedCell):
            cell.value = None
            cell.fill  = PatternFill(fill_type=None)

# ── Insert rows if N > original story count ───────────────────────
if N > ORIG_STORY_COUNT:
    ws_tc.insert_rows(ORIG_TOTALS_ROW, amount=N - ORIG_STORY_COUNT)

# ── Dynamic row positions ─────────────────────────────────────────
TOTALS_ROW    = 4 + N
TC_HDR_ROW    = TOTALS_ROW + 2
TC_DATA_START = TC_HDR_ROW + 1

# ── Write story summary rows ──────────────────────────────────────
for idx, story in enumerate(story_data):
    ri       = 4 + idx
    row_fill = mk_fill(ODD_ROW) if idx % 2 == 0 else PatternFill(fill_type=None)
    total    = story.get("total_tcs", 0)
    p        = story.get("pass", 0)
    f        = story.get("fail", 0)
    b        = story.get("blocked", 0)
    ip       = story.get("in_progress", 0)
    nr       = max(0, total - p - f - b - ip)
    vals     = [story.get("key",""), float(total), float(p), float(f), float(b),
                0.0, float(ip), float(nr), 0.0, 0.0, 0.0, 0.0, 0.0]
    for ci, val in enumerate(vals, 1):
        cell = ws_tc.cell(ri, ci)
        if isinstance(cell, MergedCell): continue
        cell.value     = val
        cell.fill      = row_fill
        cell.font      = mk_font(size=10, bold=(ci == 1))
        cell.alignment = mk_align(h="center" if ci > 1 else "left", v="center")

# ── Totals row ────────────────────────────────────────────────────
LAST = 3 + N
ws_tc.cell(TOTALS_ROW, 1).value = f"=COUNTA(A4:A{LAST})"
for ci in range(2, 14):
    col = chr(64 + ci)
    ws_tc.cell(TOTALS_ROW, ci).value = f"=SUM({col}4:{col}{LAST})"
for ci in range(1, 14):
    cell = ws_tc.cell(TOTALS_ROW, ci)
    if not isinstance(cell, MergedCell):
        cell.fill = mk_fill(GREY_FILL)
        cell.font = mk_font(bold=True, size=10)
        cell.alignment = mk_align(h="center" if ci > 1 else "left", v="center")

# ── Update coverage formulas (row 2) ─────────────────────────────
cov = ws_tc.cell(2, 2)
if not isinstance(cov, MergedCell):
    cov.value = f"=SUM(C{TOTALS_ROW}:F{TOTALS_ROW})/B{TOTALS_ROW}"
cov2 = ws_tc.cell(2, 13)
if not isinstance(cov2, MergedCell):
    cov2.value = f"=K{TOTALS_ROW}/I{TOTALS_ROW}"

# ── TC detail header row ──────────────────────────────────────────
TC_HDR_VALS = ["Story","Module","Test Case ID","Test Case","Test Case Description",
               "Expected Result","Status","Tested by","Identified for Automation","Automated"]
for ci, val in enumerate(TC_HDR_VALS, 1):
    cell = ws_tc.cell(TC_HDR_ROW, ci)
    if not isinstance(cell, MergedCell):
        cell.value = val
        s = tc_hdr_styles.get(ci, {})
        cell.font      = copy.copy(s["font"])      if s.get("font")      else mk_font(bold=True, size=10)
        cell.fill      = copy.copy(s["fill"])      if s.get("fill")      else mk_fill(LIGHT_BLUE)
        cell.alignment = copy.copy(s["alignment"]) if s.get("alignment") else mk_align(h="center", v="center")

# ── TC detail rows ────────────────────────────────────────────────
story_tcs = OrderedDict()
for tc in tc_rows:
    key = tc.get("story", tc.get("ticket", ""))
    story_tcs.setdefault(key, []).append(tc)

ri = TC_DATA_START
for story_key, tcs in story_tcs.items():
    for idx2, tc in enumerate(tcs):
        status = (tc.get("status") or "").strip()
        cell_a = ws_tc.cell(ri, 1)
        if not isinstance(cell_a, MergedCell):
            cell_a.value = story_key if idx2 == 0 else None
            cell_a.font  = mk_font(bold=(idx2 == 0), size=10)
        safe_set(ws_tc.cell(ri, 2), tc.get("module", ""))
        safe_set(ws_tc.cell(ri, 3), tc.get("tc_id", ""))
        for ci, key2 in [(4,"tc_name"),(5,"tc_desc"),(6,"expected")]:
            cell = ws_tc.cell(ri, ci)
            if not isinstance(cell, MergedCell):
                cell.value = tc.get(key2, "")
                cell.alignment = mk_align(wrap=True)
        cell_g = ws_tc.cell(ri, 7)
        if not isinstance(cell_g, MergedCell):
            cell_g.value = status
            cell_g.alignment = mk_align(h="center")
            if   status.lower() == "pass":
                cell_g.fill = mk_fill(PASS_GREEN); cell_g.font = mk_font(bold=True, color="FFFFFF", size=10)
            elif status.lower() == "fail":
                cell_g.fill = mk_fill("FF0000");   cell_g.font = mk_font(bold=True, color="FFFFFF", size=10)
            elif status.lower() == "blocked":
                cell_g.fill = mk_fill("FFC000");   cell_g.font = mk_font(bold=True, size=10)
        safe_set(ws_tc.cell(ri, 8), tc.get("tested_by", ""))
        ri += 1
print(f"TestCase Coverage: {N} stories, {ri - TC_DATA_START} TC rows, TC data starts row {TC_DATA_START}")

# ── Add borders to TestCase Coverage ─────────────────────────────
_thin = Side(style='thin', color='000000')
def _tb(): return Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
def _apply_border(ws, row, c1, c2):
    for ci in range(c1, c2 + 1):
        cell = ws.cell(row, ci)
        if not isinstance(cell, MergedCell): cell.border = _tb()
for _ri in range(4, TOTALS_ROW + 1):       # story summary rows + totals
    _apply_border(ws_tc, _ri, 1, 13)
_apply_border(ws_tc, TC_HDR_ROW, 1, 10)    # TC header row
for _ri in range(TC_DATA_START, ws_tc.max_row + 1):  # TC detail rows
    if not any(ws_tc.cell(_ri, ci).value is not None
               for ci in range(1, 11)
               if not isinstance(ws_tc.cell(_ri, ci), MergedCell)):
        break
    _apply_border(ws_tc, _ri, 1, 10)

# ═══════════════════════════════════════════════════════════════════
# TAB: Overall Summary — sprint number (D4) and dates (D5)
# ═══════════════════════════════════════════════════════════════════
ws_os = wb["Overall Summary"]

cell_d4 = ws_os.cell(4, 4)
if not isinstance(cell_d4, MergedCell):
    try:    cell_d4.value = float(SPRINT_NO)
    except: cell_d4.value = SPRINT_NO

def ord_date(s):
    import datetime as _dt
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            d   = _dt.datetime.strptime(s.strip(), fmt)
            sfx = {1:"st",2:"nd",3:"rd"}.get(d.day if d.day < 20 else d.day % 10, "th")
            return f"{d.day}{sfx} {d.strftime('%b')}"
        except: pass
    return s

import datetime as _dt2
end_yr = ""
for fmt in ("%b %d, %Y", "%B %d, %Y"):
    try: end_yr = _dt2.datetime.strptime(END_DATE.strip(), fmt).strftime("%Y"); break
    except: pass

date_str = f"{ord_date(START_DATE)} - {ord_date(END_DATE)} {end_yr}".strip()
cell_d5 = ws_os.cell(5, 4)
if not isinstance(cell_d5, MergedCell):
    cell_d5.value = date_str
print(f"Overall Summary: Sprint={SPRINT_NO}, Dates={date_str}")

# ── O1: today's date ─────────────────────────────────────────────
import datetime as _dt3
_today = _dt3.date.today().strftime("%d/%m/%Y")
_cell_o1 = ws_os.cell(1, 15)
if not isinstance(_cell_o1, MergedCell):
    _cell_o1.value = f"Date :{_today}"

# ── Fix formula row refs: TC Coverage ORIG_TOTALS_ROW(12) → TOTALS_ROW ──
# L6:R6 = QA Execution Progress data row; D31/F31/H31/J31 = Automation Coverage
import re as _re_os
def _fix_row_ref(formula, old, new):
    return _re_os.sub(rf"(!(?:[A-Z]+)){old}\b", rf"\g<1>{new}", formula)
for _col in range(12, 19):                  # cols L-R (12-18) = QA Exec Progress
    _c = ws_os.cell(6, _col)
    if not isinstance(_c, MergedCell) and isinstance(_c.value, str) and _c.value.startswith("="):
        _c.value = _fix_row_ref(_c.value, ORIG_TOTALS_ROW, TOTALS_ROW)
for _col in [4, 6, 8, 10]:                  # cols D/F/H/J = Automation Coverage
    _c = ws_os.cell(31, _col)
    if not isinstance(_c, MergedCell) and isinstance(_c.value, str) and _c.value.startswith("="):
        _c.value = _fix_row_ref(_c.value, ORIG_TOTALS_ROW, TOTALS_ROW)

# ── Defects Trend: hardcode actual open/closed by priority ───────
def _sn(ws, row, col, val):
    cell = ws.cell(row, col)
    if not isinstance(cell, MergedCell): cell.value = float(val)
_sn(ws_os, 22, 4, sd["P0_o"]); _sn(ws_os, 22, 5, sd["P1_o"])
_sn(ws_os, 22, 6, sd["P2_o"]); _sn(ws_os, 22, 7, sd["P3_o"])   # Open
_sn(ws_os, 23, 4, sd["P0_c"]); _sn(ws_os, 23, 5, sd["P1_c"])
_sn(ws_os, 23, 6, sd["P2_c"]); _sn(ws_os, 23, 7, sd["P3_c"])   # Closed

# ── Progress This Cycle: story pipeline counts + totals ──────────
_sn(ws_os, 22, 14, sd["NOT_STARTED"])   # N22 stories ready for QA
_sn(ws_os, 22, 15, sd["IN_QA"])         # O22 stories QA In-Progress
_sn(ws_os, 22, 16, sd["QA_COMPLETED"])  # P22 stories QA Completed
_sn(ws_os, 22, 17, sd["READY_UAT"])     # Q22 stories ready for UAT
_sn(ws_os, 22, 18, sd["UAT_COMPLETED"]) # R22 UAT Completed
_sn(ws_os, 25, 14, sd["TOTAL_STORIES"]) # N25 Total Stories Planned
_sn(ws_os, 26, 14, sd["QA_QUALIFIED"])  # N26 QA Qualified
print(f"Overall Summary extra: Date={_today} | "
      f"P2 Open={sd['P2_o']} Closed={sd['P2_c']} | "
      f"Pipeline: NotStarted={sd['NOT_STARTED']} InQA={sd['IN_QA']} "
      f"QADone={sd['QA_COMPLETED']} ReadyUAT={sd['READY_UAT']} UATDone={sd['UAT_COMPLETED']}")

# ═══════════════════════════════════════════════════════════════════
# TAB: Sheet1 — story card counts (row 6) + TC summary rows (12+)
# ═══════════════════════════════════════════════════════════════════
ws_s1 = wb["Sheet1"]

# ── Clear defects side table (cols 13-19) from the template ──────
# Template carries a "Defects | P0 | P1 | P2 | P3 | No Action" table at
# cols 13-19 (rows 11+) which is not used in the generated report.
for _ri in range(11, ws_s1.max_row + 1):
    for _ci in range(13, 20):
        _c = ws_s1.cell(_ri, _ci)
        if not isinstance(_c, MergedCell):
            _c.value  = None
            _c.fill   = PatternFill(fill_type=None)
            _c.border = Border()

safe_set(ws_s1.cell(6, 2), float(sd.get("QA_QUALIFIED", N)))
safe_set(ws_s1.cell(6, 3), float(sd.get("QA_QUALIFIED", N)))   # QA Completed = QA Qualified
safe_set(ws_s1.cell(6, 4), float(sd.get("READY_UAT", 0)))
safe_set(ws_s1.cell(6, 5), float(sd.get("UAT_COMPLETED", 0)))
# Savings due to Test Automation in Hrs/Sprint = SUM(QA Automation Savings col J) / 24
# Formula refs story rows 12 to 11+N; updates automatically when Excel opens the file.
ws_s1.cell(6, 6).value = f"=SUM(J12:J{11+N})/24"

ORIG_S1_STORY_COUNT = 6
ORIG_S1_TOTALS_ROW  = 18
if N > ORIG_S1_STORY_COUNT:
    ws_s1.insert_rows(ORIG_S1_TOTALS_ROW, amount=N - ORIG_S1_STORY_COUNT)
S1_TOTALS_ROW = 12 + N

# ── Unmerge any cells overlapping the story-data rows so every cell is writable ──
def _safe_unmerge(ws, range_str):
    """Unmerge a range, pre-initializing cells first (required for inserted blank rows)."""
    try:
        from openpyxl.utils import range_boundaries
        min_col, min_row, max_col, max_row = range_boundaries(range_str)
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                _ = ws._cells.get((r, c)) or ws.cell(r, c)
        ws.unmerge_cells(range_str)
    except Exception:
        try: ws.merged_cells.remove(range_str)
        except: pass

_s1_story_merges = [str(m) for m in list(ws_s1.merged_cells.ranges)
                    if m.max_row >= 12 and m.min_row < S1_TOTALS_ROW]
for _m in _s1_story_merges:
    _safe_unmerge(ws_s1, _m)

_thin_s1 = Side(style='thin', color='000000')
def _s1_border(): return Border(left=_thin_s1, right=_thin_s1, top=_thin_s1, bottom=_thin_s1)

_bug_by_story = sd.get("bug_by_story", {})
for idx, story in enumerate(story_data):
    ri        = 12 + idx
    total_tcs = story.get("total_tcs", 0)
    pass_tcs  = story.get("pass", 0)
    _bugs_s   = _bug_by_story.get(story["key"], 0)
    _density  = (_bugs_s / total_tcs * 100) if total_tcs else 0.0
    exec_val  = 1.0 if (total_tcs > 0 and pass_tcs >= total_tcs) else (pass_tcs / total_tcs if total_tcs else 0.0)
    row_fill  = mk_fill(ODD_ROW) if idx % 2 == 0 else PatternFill(fill_type=None)
    # Write all columns directly — no cross-sheet formulas, works for any N stories
    _s1_row_vals = [
        (1, float(idx + 1)),        # SI No
        (2, story.get("key", "")), # Story Cards — written directly, not as formula
        (3, float(total_tcs)),     # Total no. of Test Cases
        (4, float(pass_tcs)),      # Pass
        (5, exec_val),             # Execution %
        (6, float(_bugs_s)),       # Defects
        (7, _density),             # Defect Density (%)
        (8, 0.0),                  # Defect Leakage (%) — default 0, user can edit
        (9, 0.0),                  # Defect Rejection Rate (%) — default 0, user can edit
        (10, None),                # QA Automation Savings in (hrs) — user fills post-generation
        (11, None),                # Comments — user fills post-generation
    ]
    for ci, val in _s1_row_vals:
        cell = ws_s1.cell(ri, ci)
        cell.value     = val
        cell.alignment = mk_align(h="center", v="center")
        cell.font      = mk_font(bold=(ci == 1), size=10)
        cell.fill      = row_fill
        cell.border    = _s1_border()

# Update totals row formulas to span new story range (cols 1-11 only) + apply borders
for ci in range(1, 12):
    cell = ws_s1.cell(S1_TOTALS_ROW, ci)
    if not isinstance(cell, MergedCell) and isinstance(cell.value, str) and cell.value.startswith("="):
        cell.value = re.sub(r'([A-Z]+\d+:[A-Z]+)\d+', rf'\g<1>{S1_TOTALS_ROW - 1}', cell.value)
    if not isinstance(cell, MergedCell):
        cell.border = _s1_border()

# Clear leftover template story rows only when sprint has FEWER stories than the template
if N < ORIG_S1_STORY_COUNT:
    for ri in range(S1_TOTALS_ROW + 1, ORIG_S1_TOTALS_ROW + 1):
        for ci in range(1, 12):
            cell = ws_s1.cell(ri, ci)
            if not isinstance(cell, MergedCell) and cell.value is not None:
                cell.value = None

# Populate bug table (P0/P1/P2 rows) with actual sprint defect data
# Bug table rows shift down by (N - ORIG_S1_STORY_COUNT) when N > ORIG_S1_STORY_COUNT
_bug_shift = max(0, N - ORIG_S1_STORY_COUNT)
_P0_row = 23 + _bug_shift
_P1_row = 24 + _bug_shift
_P2_row = 25 + _bug_shift
_P0_t = sd.get("P0_o", 0) + sd.get("P0_c", 0)
_P1_t = sd.get("P1_o", 0) + sd.get("P1_c", 0)
_P2_t = sd.get("P2_o", 0) + sd.get("P2_c", 0)
for (_pr, _tot, _cl, _lk) in [
    (_P0_row, _P0_t, sd.get("P0_c", 0), sd.get("P0_o", 0)),
    (_P1_row, _P1_t, sd.get("P1_c", 0), sd.get("P1_o", 0)),
    (_P2_row, _P2_t, sd.get("P2_c", 0), sd.get("P2_o", 0)),
]:
    _pct = (_lk / _tot) if _tot else 0.0
    for (ci, val) in [(2, float(_tot)), (3, float(_cl)), (4, float(_lk)), (5, _pct)]:
        _bc = ws_s1.cell(_pr, ci)
        if not isinstance(_bc, MergedCell):
            _bc.value = val
            if ci == 5:
                _bc.number_format = '0.00%'
print(f"Sheet1 updated: {N} story rows, totals at row {S1_TOTALS_ROW}, bug table at rows {_P0_row}-{_P2_row}, borders+alignment applied dynamically")

# ═══════════════════════════════════════════════════════════════════
# Save + Upload to Drive
# ═══════════════════════════════════════════════════════════════════
try:
    sprint_slug  = re.sub(r'[^A-Za-z0-9]+', '_', SPRINT_NAME).strip('_')
    OUT_FILENAME = f"Test_Status_Report_{PROJECT} _{sprint_slug}.xlsx"
except:
    OUT_FILENAME = "Test_Status_Report_Sprint.xlsx"

OUT_PATH = f"/tmp/{OUT_FILENAME}"
wb.save(OUT_PATH)
print(f"✅ Saved: {OUT_PATH} ({Path(OUT_PATH).stat().st_size:,} bytes)")

# ── Refresh token for upload ──────────────────────────────────────
td = json.loads(Path.home().joinpath(".gdrive-mcp-token.json").read_text("utf-8"))
rv2 = json.loads(urllib.request.urlopen(
    urllib.request.Request(
        td.get("token_uri","https://oauth2.googleapis.com/token"),
        data=urllib.parse.urlencode({"client_id":td["client_id"],"client_secret":td["client_secret"],
            "refresh_token":td["refresh_token"],"grant_type":"refresh_token"}).encode(),
        headers={"Content-Type":"application/x-www-form-urlencoded"}, method="POST"),
    context=ctx).read())
ACCESS_TOKEN = rv2.get("access_token", td.get("access_token",""))
td["access_token"] = td["token"] = ACCESS_TOKEN
Path.home().joinpath(".gdrive-mcp-token.json").write_text(json.dumps(td))

MIME  = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BNDRY = "sprint_report_boundary"
fdata = Path(OUT_PATH).read_bytes()
file_id = ""; web_link = ""

for folder in [REPORT_FOLDER_ID, ""]:   # try report folder first, fall back to root
    meta = json.dumps({"name": OUT_FILENAME, **({"parents": [folder]} if folder else {})}).encode()
    body = (
        f"--{BNDRY}\r\n".encode() + b"Content-Type: application/json; charset=UTF-8\r\n\r\n" +
        meta + b"\r\n" + f"--{BNDRY}\r\n".encode() +
        f"Content-Type: {MIME}\r\n\r\n".encode() + fdata + b"\r\n" +
        f"--{BNDRY}--".encode()
    )
    req_up = urllib.request.Request(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,webViewLink",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}",
                 "Content-Type": f"multipart/related; boundary={BNDRY}",
                 "Content-Length": str(len(body))})
    try:
        resp     = json.loads(urllib.request.urlopen(req_up, context=ctx).read())
        file_id  = resp.get("id","")
        web_link = resp.get("webViewLink","")
        loc = "report folder" if folder else "Drive root (move manually to report folder)"
        print(f"✅ Uploaded to {loc}: {web_link}")
        break
    except urllib.error.HTTPError as e:
        if e.code == 403 and folder:
            print("  Report folder 403 → retrying to Drive root...")
            continue
        print(f"❌ Upload failed: {e.code} — {e.read().decode()[:200]}")
        break

sd.update({
    "xlsx_file_id":   file_id,
    "xlsx_link":      web_link,
    "xlsx_filename":  OUT_FILENAME,
    "xlsx_local_path": OUT_PATH,
})
Path("/tmp/sprint_data.json").write_text(json.dumps(sd, indent=2))
print(f"\nFILE_ID={file_id}\nURL: {web_link}")
```
---

### 6e — Output and wait for user review

```
✅ Sprint QA Report (.xlsx) uploaded to Google Drive:
   {web_view_link}

👆 Please open the link above, review and fill in any additional details
   (e.g. progress notes, QA sign-off notes, reviewer names, comments).
   When you are ready to send the email, reply with:

   send to user1@rubrik.com, user2@rubrik.com
   (list all To: recipients comma-separated)
```

If `TO_EMAILS` was already provided as an argument, show instead:
```
✅ Sprint QA Report (.xlsx) uploaded to Google Drive:
   {web_view_link}

📧 Email will be sent to: {", ".join(TO_EMAILS)}
   {f"CC: {', '.join(CC_EMAILS)}" if CC_EMAILS else ""}
   {f"From: {FROM_EMAIL}" if FROM_EMAIL else ""}

👆 Please open the link, review the report, and reply "send" when ready.
   (Or reply with different addresses to override.)
```

**STOP here — wait for the user to reply.**

---

## STEPS 7–8b — Re-read Sheet + Build Email + Send (python3 call #5 — ONE script)

> **Steps 7, 8a, and 8b are a single python3 call.** Do NOT split them into multiple scripts. All variables from `/tmp/sprint_data.json` are loaded at the top; the script re-reads Sheet1, builds the HTML email, exports XLSX, and sends via Gmail API — in sequence, in one script.

When the user replies (e.g. `send to a@rubrik.com, b@rubrik.com` or just `send`):

1. **Parse From/To/CC from the reply** — override argument-supplied values if the user provides new ones in their reply. If the reply contains addresses without explicit `to=`/`cc=`/`from=` keys, treat them as To recipients. Fall back to the values parsed in Step 1 if none are given in the reply.

   ```python
   def _parse_email_param(text, key):
       m = re.search(rf'(?:^|[\s,]){key}\s*=\s*([^\s]+(?:\s*,\s*[^\s]+)*)', text, re.IGNORECASE)
       if not m: return None
       return [e.strip() for e in m.group(1).split(',') if e.strip()]

   # Merge reply addresses with Step 1 values (reply takes precedence)
   reply_text = "<user reply>"

   # Check for explicit key=value overrides in reply
   reply_from = _parse_email_param(reply_text, "from")
   reply_to   = _parse_email_param(reply_text, "to")
   reply_cc   = _parse_email_param(reply_text, "cc")

   # Fall back to bare email addresses in reply as To if no explicit to= given
   if not reply_to:
       bare_emails = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', reply_text)
       if bare_emails:
           reply_to = bare_emails

   FINAL_FROM = (reply_from[0] if reply_from else None) or FROM_EMAIL   # None = send as authenticated account
   FINAL_TO   = reply_to or TO_EMAILS or []
   FINAL_CC   = (reply_cc if reply_cc is not None else CC_EMAILS) or []
   ```

   If `FINAL_TO` is still empty after merging, ask the user for To addresses before continuing.
2. **Load sprint data** from `/tmp/sprint_data.json` and **re-read Sheet1 from the local xlsx** to capture any user edits (QA Automation Savings, Comments, Sprint Automation table) made after the report was uploaded.

   ```python
   sd = json.loads(Path("/tmp/sprint_data.json").read_text("utf-8"))
   STORY_DATA   = sd.get("STORY_DATA", [])
   bug_by_story = sd.get("bug_by_story", {})
   s1_images_html = ""
   FILE_ID      = sd.get("xlsx_file_id", "")
   web_view_link = sd.get("xlsx_link", "")

   # ── Download latest xlsx from Drive (captures user edits post-upload) ──
   # ALWAYS download fresh from Drive — never use a cached /tmp file.
   import openpyxl as _opxl, datetime as _dt_e
   from openpyxl.cell.cell import MergedCell as _MC_e
   _drive_file_id_e = sd.get("xlsx_file_id", "")
   _xlsx_for_email  = sd.get("xlsx_local_path", "")
   if _drive_file_id_e:
       try:
           _dl_bytes_e = urllib.request.urlopen(
               urllib.request.Request(
                   f"https://www.googleapis.com/drive/v3/files/{_drive_file_id_e}?alt=media",
                   headers={"Authorization": f"Bearer {DRIVE_TOKEN}"}), context=ctx).read()
           _xlsx_for_email = "/tmp/sprint_drive_for_email.xlsx"
           Path(_xlsx_for_email).write_bytes(_dl_bytes_e)
           print(f"  Drive xlsx downloaded fresh: {len(_dl_bytes_e):,} bytes")
       except Exception as _dl_e2:
           print(f"  Drive download failed ({_dl_e2}) — using local file")

   # ── Read Sheet1 from the Drive xlsx into s1_rows ──────────────────
   s1_rows = []
   _wb_e = None
   if _xlsx_for_email and Path(_xlsx_for_email).exists():
       _wb_e = _opxl.load_workbook(_xlsx_for_email, data_only=True)
       _ws_e = _wb_e["Sheet1"]
       _max_col_e = max(_ws_e.max_column or 1, 12)
       for _ri_e in range(1, _ws_e.max_row + 1):
           _row_e = []
           for _ci_e in range(1, _max_col_e + 1):
               _c_e = _ws_e.cell(_ri_e, _ci_e)
               if isinstance(_c_e, _MC_e):
                   _v_e = ""
               else:
                   _raw_e = _c_e.value
                   if isinstance(_raw_e, _dt_e.datetime):
                       _v_e = _raw_e.strftime("%m/%d/%Y")
                   elif _raw_e is None:
                       _v_e = ""
                   else:
                       _v_e = str(_raw_e)
               _row_e.append(_v_e)
           s1_rows.append(_row_e)

   # ── Extract embedded images from Sheet1 (e.g. automation screenshots) ──
   if _wb_e is not None:
       try:
           for _img_obj in getattr(_wb_e["Sheet1"], '_images', []):
               try:
                   _img_data = _img_obj._data()
                   if _img_data:
                       _mime = ('image/png' if _img_data[:8] == b'\x89PNG\r\n\x1a\n'
                                else 'image/jpeg' if _img_data[:2] == b'\xff\xd8'
                                else 'image/png')
                       _img_b64 = base64.b64encode(_img_data).decode()
                       s1_images_html += (
                           f'<img src="data:{_mime};base64,{_img_b64}" '
                           f'style="max-width:800px;display:block;margin:4px 0"/><br>')
               except Exception as _ei:
                   print(f"  Image extract warning: {_ei}")
           if s1_images_html:
               print(f"  Extracted {s1_images_html.count('<img')} embedded image(s) from Sheet1")
       except Exception as _e_img:
           print(f"  Image extraction skipped: {_e_img}")
   ```

> **IMPORTANT:** The Drive token (`DRIVE_TOKEN`) must be refreshed **before** this code block runs. Structure call #5 to refresh both tokens at the top of the script, then download the xlsx here.

3. **Reconstruct metrics** from `sprint_data.json`. Use the cached data as the authoritative source for the email body.
4. **Generate email body** (format below) using the metrics from sprint_data.json.

---

## STEP 8 — Send Email (with xlsx attachment)

Build an HTML email body from the metrics in STEP 7, download the uploaded xlsx from Drive, and send via the Gmail API directly (multipart MIME) so the report is attached. **Do NOT use `mcp__gmail__send_email`** — it does not support attachments. Use `Bash(python3 *)` instead.

```python
# ── Build story→automation savings & comments lookup from re-read Sheet1 ─
# Sheet1 col layout (0-based): 0=Sl No, 1=Story, 2=Total TCs, 3=Pass, 4=Exec%,
#   5=Defects, 6=Defect Density%, 7=Defect Leakage%, 8=Defect Rejection Rate%,
#   9=QA Automation Savings (hrs), 10=Comments
# Story data rows start at xlsx row 12 → s1_rows index 11; run for len(STORY_DATA) rows.
s1_story_extras = {}  # story_key → {"savings": "...", "comments": "..."}
_n_stories = len(STORY_DATA)
for _ri_x in range(11, 11 + _n_stories):
    if _ri_x >= len(s1_rows): break
    _row_x = s1_rows[_ri_x]
    _key_x = _row_x[1].strip() if len(_row_x) > 1 else ""
    if not _key_x or not re.match(r'^[A-Z]+-\d+$', _key_x):
        continue
    _sv_x  = _row_x[9].strip()  if len(_row_x) > 9  else ""   # col 10 — QA Automation Savings
    _cm_x  = _row_x[10].strip() if len(_row_x) > 10 else ""   # col 11 — Comments
    s1_story_extras[_key_x] = {"savings": _sv_x, "comments": _cm_x}

# ── Build per-story TC summary rows — Sprint 3 format (11 columns) ─
# Columns: Sl No | Story Cards (JIRA link) | Total TCs | Pass | Execution % |
#          Defects | Defect Density % | Defect Leakage % | Defect Rejection Rate % |
#          QA Automation Savings (hrs) | Comments
# Last 2 columns read from Sheet1 so user edits made after upload are captured.
# Comments column: consecutive empty-comment rows are merged with rowspan to avoid
# a wall of empty cells; rows with comment text each get their own cell.
_sc = []  # precompute per-story cell data
for i, s in enumerate(STORY_DATA):
    exec_pct  = f"{s['pass']/s['total_tcs']*100:.0f}%" if s['total_tcs'] else "0%"
    bugs_s    = bug_by_story.get(s["key"], 0)
    density   = f"{(bugs_s/s['total_tcs']*100):.2f}" if s['total_tcs'] else "0.00"
    jira_url  = f"https://rubrik.atlassian.net/browse/{s['key']}"
    _extras   = s1_story_extras.get(s["key"], {})
    _savings  = _extras.get("savings", "")
    _comments = _extras.get("comments", "")
    _sc.append({"i": i, "key": s["key"], "total_tcs": s["total_tcs"], "pass": s["pass"],
                "exec_pct": exec_pct, "bugs_s": bugs_s, "density": density,
                "jira_url": jira_url, "_savings": _savings, "_comments": _comments})

# Compute rowspan groups: each non-empty comment absorbs the following empty-comment
# rows into its cell (matching xlsx merged-cell behaviour). Stories before the first
# non-empty comment each get their own individual empty cell.
_cmt_span = {}   # index → rowspan (anchor row of a comment group)
_cmt_skip = set()  # indices covered by a preceding rowspan
_ci = 0
while _ci < len(_sc):
    if _sc[_ci]["_comments"]:
        # Absorb all following empty-comment rows into this cell
        _cj = _ci + 1
        while _cj < len(_sc) and not _sc[_cj]["_comments"]:
            _cj += 1
        if _cj - _ci > 1:
            _cmt_span[_ci] = _cj - _ci
            for _ck in range(_ci + 1, _cj):
                _cmt_skip.add(_ck)
        _ci = _cj
    else:
        _ci += 1  # leading/isolated empty story → individual empty cell

story_rows_html = ""
for c in _sc:
    i = c["i"]
    _cm_html = c["_comments"].replace(chr(10), '<br>').replace('\\n', '<br>')
    if i in _cmt_skip:
        _comment_td = ""  # covered by rowspan of a previous row
    elif i in _cmt_span:
        _rs = _cmt_span[i]
        _comment_td = (f'<td style="border:1px solid #000;padding:6px;vertical-align:middle;'
                       f'text-align:center" rowspan="{_rs}">{_cm_html}</td>')
    else:
        _comment_td = (f'<td style="border:1px solid #000;padding:3px 6px;vertical-align:top">'
                       f'{_cm_html}</td>')
    story_rows_html += f"""
        <tr>
          <td style="border:1px solid #000;text-align:center;padding:3px 6px">{i+1}</td>
          <td style="border:1px solid #000;padding:3px 6px;white-space:nowrap"><a href="{c['jira_url']}" style="color:#1155CC;text-decoration:underline">{c['key']}</a></td>
          <td style="border:1px solid #000;text-align:center;padding:3px 6px">{c['total_tcs']}</td>
          <td style="border:1px solid #000;text-align:center;padding:3px 6px">{c['pass']}</td>
          <td style="border:1px solid #000;text-align:center;padding:3px 6px">{c['exec_pct']}</td>
          <td style="border:1px solid #000;text-align:center;padding:3px 6px">{c['bugs_s']}</td>
          <td style="border:1px solid #000;text-align:center;padding:3px 6px">{c['density']}</td>
          <td style="border:1px solid #000;text-align:center;padding:3px 6px">0</td>
          <td style="border:1px solid #000;text-align:center;padding:3px 6px">0</td>
          <td style="border:1px solid #000;text-align:center;padding:3px 6px">{c['_savings']}</td>
          {_comment_td}
        </tr>"""

# ── Build bug priority rows — format: Total Number of Defects | Open | Close | Defect Leaked to UAT | Defect Leakage to UAT (%)
# Priority label is a cyan row-header in the first column; Leakage % spans all 4 rows via rowspan
_bug_priorities = [("P0", P0), ("P1", P1), ("P2", P2), ("P3", P3)]
total_bugs_all = 0; total_leaked_all = 0
for _, bd in _bug_priorities:
    total_bugs_all += bd["total"]; total_leaked_all += bd.get("leaked", 0)
leakage_rowspan_pct = f"0%({total_leaked_all}/{total_bugs_all})" if total_bugs_all else "0%(0/0)"

bug_rows_html = ""
for i, (p_label, bd) in enumerate(_bug_priorities):
    total  = bd["total"]; closed = bd["closed"]; open_count = total - closed; leaked = bd.get("leaked", 0)
    leakage_cell = f'<td style="border:1px solid #000;text-align:center;padding:4px 8px;font-weight:bold" rowspan="4">{leakage_rowspan_pct}</td>' if i == 0 else ""
    bug_rows_html += f"""
        <tr>
          <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 8px">{p_label}</td>
          <td style="border:1px solid #000;text-align:center;padding:4px 8px">{open_count}</td>
          <td style="border:1px solid #000;text-align:center;padding:4px 8px">{closed}</td>
          <td style="border:1px solid #000;text-align:center;padding:4px 8px">{leaked}</td>
          {leakage_cell}
        </tr>"""

# ── Compute formula strings ───────────────────────────────────────
defect_density_pct  = f"{(TOTAL_BUGS/TOTAL_TCS*100):.2f}"  if TOTAL_TCS  else "0.00"
defect_leakage_pct  = f"{(LEAKED_BUGS/TOTAL_BUGS*100):.2f}" if TOTAL_BUGS else "0.00"
density_inline      = f"{defect_density_pct}%({TOTAL_BUGS}/{TOTAL_TCS})" if TOTAL_TCS else "0.00%(0/0)"
leakage_inline      = f"{defect_leakage_pct}%"
rejection_rate_pct  = f"{(REJECTED_BUGS/TOTAL_BUGS*100):.0f}" if TOTAL_BUGS else "0"

# ── Ordinal date helper ───────────────────────────────────────────
def _ord(date_str):
    from datetime import datetime
    try:
        dt = datetime.strptime(date_str.strip(), "%b %d, %Y")
        d = dt.day
        sfx = "th" if 11 <= d <= 13 else {1:"st",2:"nd",3:"rd"}.get(d%10,"th")
        return f"{d}{sfx} {dt.strftime('%b')}"
    except: return date_str
_start_ord = _ord(START_DATE)
_end_ord   = _ord(END_DATE)

# ── Build Sprint Automation HTML from Sheet1 ──────────────────────
# Strategy: first scan the entire sheet for a row containing "automation"
# or a known automation column header ("Total TC", "Passed TC", "Broken TC").
# If found, build the table from there.  Fall back to a position-based scan
# starting at (11+N+4) if keyword search finds nothing.
auto_html = ""
_auto_tbl_rows = []

_AUTO_KEYWORDS = ("sprint automation", "total tc", "passed tc", "broken tc",
                  "failed tc", "skipped tc", "test automation coverage")

# Pass 1 — keyword search across full sheet (start after story rows)
_kw_start = -1
for _ri_a in range(11 + _n_stories, len(s1_rows)):
    _row_vals = [v.strip().lower() for v in s1_rows[_ri_a]]
    if any(any(kw in cell for kw in _AUTO_KEYWORDS) for cell in _row_vals if cell):
        # found the automation header row (or a label row before it)
        # skip single-cell label rows like "Sprint Automation:"
        _ne_cnt = sum(1 for v in _row_vals if v)
        if _ne_cnt >= 2:
            _kw_start = _ri_a   # this is the table header
        else:
            _kw_start = _ri_a + 1  # next row is the real header
        break

# Pass 2 — collect contiguous rows from header onward
_scan_from = _kw_start if _kw_start != -1 else (11 + _n_stories + 4)
_in_auto_tbl = False
for _ri_a in range(_scan_from, len(s1_rows)):
    _row_a = s1_rows[_ri_a]
    _ne_a  = [v.strip() for v in _row_a if v.strip()]
    if len(_ne_a) >= 2:
        _auto_tbl_rows.append(_row_a)
        _in_auto_tbl = True
    elif _in_auto_tbl and not _ne_a:
        break   # first empty row after table signals end

if _auto_tbl_rows:
    _hdr_row_a = _auto_tbl_rows[0]
    _hdr_cells_a = "".join(
        f'<td style="background-color:#00FFFF;border:1px solid black;'
        f'padding:4px;font-weight:bold;text-align:center">{h.strip().replace(chr(10), "<br>")}</td>'
        for h in _hdr_row_a if h.strip())
    _data_html_a = ""
    for _drow_a in _auto_tbl_rows[1:]:
        _ne_idx_a = [k for k, h in enumerate(_hdr_row_a) if h.strip()]
        _cells_a  = ""
        for _ci_a, _idx_a in enumerate(_ne_idx_a):
            _v_a = (_drow_a[_idx_a].strip() if _idx_a < len(_drow_a) else "").replace('\n', '<br>')
            try:  # strip .0 for whole-number floats (e.g. 98.0 → 98)
                _vf_a = float(_v_a)
                if _vf_a == int(_vf_a): _v_a = str(int(_vf_a))
            except: pass
            _align_a = "center" if _ci_a < 7 else "left"
            _cells_a += (f'<td style="border:1px solid black;padding:4px;'
                         f'text-align:{_align_a};vertical-align:top">{_v_a}</td>')
        _data_html_a += f'<tr>{_cells_a}</tr>'
    auto_html = (f'<table border="1" cellpadding="4" cellspacing="0" '
                 f'style="border-collapse:collapse;font-size:11px">'
                 f'<tr>{_hdr_cells_a}</tr>{_data_html_a}</table><br>')

if not auto_html:
    auto_html = "<ul><li>Sprint Automation &ndash; In Progress</li></ul>"

# ── Parse QA Summary of Story Cards from Sheet1 ──────────────────
# Read the data row (2 rows below the header) so user edits are captured.
qa_summary = {
    "track": PROJECT, "qualified": str(QA_QUALIFIED),
    "completed": str(QA_COMPLETED), "ready_uat": str(READY_UAT),
    "uat_completed": str(UAT_COMPLETED), "savings": "-"
}
for _si, _srow in enumerate(s1_rows):
    _scv = _srow[0].strip() if _srow else ""
    if "qa summary of story cards" in _scv.lower():
        if _si + 2 < len(s1_rows):
            _dr = s1_rows[_si + 2]
            if len(_dr) > 0 and _dr[0].strip(): qa_summary["track"]        = _dr[0].strip()
            if len(_dr) > 1 and _dr[1].strip(): qa_summary["qualified"]    = _dr[1].strip()
            if len(_dr) > 2 and _dr[2].strip(): qa_summary["completed"]    = _dr[2].strip()
            if len(_dr) > 3 and _dr[3].strip(): qa_summary["ready_uat"]    = _dr[3].strip()
            if len(_dr) > 4 and _dr[4].strip(): qa_summary["uat_completed"]= _dr[4].strip()
            if len(_dr) > 5 and _dr[5].strip(): qa_summary["savings"]      = _dr[5].strip()
        break

# ── Fallback: compute savings from story extras when formula result isn't cached ──
if qa_summary["savings"] in ("-", ""):
    try:
        _raw_sum = sum(float(v["savings"]) for v in s1_story_extras.values() if v.get("savings"))
        if _raw_sum > 0:
            qa_summary["savings"] = f"{_raw_sum/24:.2f} days"
    except Exception:
        pass

# ── Format QA Sprint Summary numbers — strip .0 for whole numbers ──
def _fmt_whole(v):
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else v
    except:
        return v

_qs_track         = _fmt_whole(qa_summary["track"])
_qs_qualified     = _fmt_whole(qa_summary["qualified"])
_qs_completed     = _fmt_whole(qa_summary["completed"])
_qs_ready_uat     = _fmt_whole(qa_summary["ready_uat"])
_qs_uat_completed = _fmt_whole(qa_summary["uat_completed"])
_qs_savings_raw   = qa_summary["savings"]
if _qs_savings_raw not in ("-", "") and "day" not in _qs_savings_raw.lower() and "hr" not in _qs_savings_raw.lower():
    try:
        _qs_savings = f"{float(_qs_savings_raw):.2f} days"
    except:
        _qs_savings = _qs_savings_raw
else:
    _qs_savings = _qs_savings_raw

# ── Assemble full HTML — confirmed format ─────────────────────────
# Font: sans-serif | Cyan headers: rgb(0,255,255) | GREEN badge: rgb(0,255,0)
# Sections: Highlights → QA Sprint Summary → QA Summary of Story Cards → Bug Report
#           → Defect formulas → Sprint Automation → Reference Links
email_html = f"""<div dir="ltr"><font face="sans-serif">
<div>Hi All,</div>
<div>We have successfully completed the <b>{SPRINT_NAME}</b> QA test execution.</div>
<div>The details are as follows:</div><br>
<div>Overall Status of the Project: <span style="background-color:rgb(0,255,0)"><b>{OVERALL_STATUS}</b></span></div><br>
<div>A small summary is given below:-</div><br>
<div><b><u>Highlights:</u></b></div>
<ul>
  <li>Total story cards considered for the Sprint {SPRINT_NO} - <span style="background-color:rgb(0,255,255)"><b>{TOTAL_STORIES}</b></span></li>
  <li>Total number of test cases executed in the QA sandbox - <span style="background-color:rgb(0,255,255)"><b>{TOTAL_TCS}</b></span></li>
  <li>Total number of bugs found by QA - <span style="background-color:rgb(0,255,255)"><b>{total_bugs_all}</b></span></li>
  <li>Defect Density - <span style="background-color:rgb(0,255,255)"><b>{density_inline}</b></span></li>
  <li>Defect Leakage - <span style="background-color:rgb(0,255,255)"><b>{leakage_inline}</b></span></li>
  <li>QA Planned Date - {_start_ord} - {_end_ord}</li>
</ul>
<br>
<div><b><u>QA Sprint Summary :</u></b></div><br>
<table cellspacing="0" cellpadding="4" border="1" style="border-collapse:collapse">
  <tr>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 8px">QA Track</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 8px">QA Qualified</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 8px">QA Completed</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 8px">Ready for UAT</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 8px">UAT Completed</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 8px">Savings due to Test Automation in Days / Sprint</td>
  </tr>
  <tr>
    <td style="border:1px solid #000;text-align:center;padding:4px 8px">{_qs_track}</td>
    <td style="border:1px solid #000;text-align:center;padding:4px 8px">{_qs_qualified}</td>
    <td style="border:1px solid #000;text-align:center;padding:4px 8px">{_qs_completed}</td>
    <td style="border:1px solid #000;text-align:center;padding:4px 8px">{_qs_ready_uat}</td>
    <td style="border:1px solid #000;text-align:center;padding:4px 8px">{_qs_uat_completed}</td>
    <td style="border:1px solid #000;text-align:center;padding:4px 8px">{_qs_savings}</td>
  </tr>
</table><br>
<br>
<div><b><u>QA Summary of Story Cards :</u></b></div><br>
<table cellspacing="0" cellpadding="4" border="1" style="border-collapse:collapse;font-size:12px">
  <tr>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 6px">Sl No</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 6px">Story Cards</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 6px">Total no. of Test Cases</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 6px">Pass</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 6px">Execution %</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 6px">Defects</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 6px">Defect Density (%)</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 6px">Defect Leakage (%)</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 6px">Defect Rejection Rate (%)</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 6px">QA Automation Savings in (hrs)</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 6px">Comments</td>
  </tr>
  {story_rows_html}
</table><br>
<br>
<div><b><u>Bug Report :</u></b></div>
<div>While testing the above execution, we found the following defects in the QA Sandbox</div><br>
<table cellspacing="0" cellpadding="4" border="1" style="border-collapse:collapse;font-size:13px">
  <tr>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 8px">Total Number of Defects</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 8px">Open</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 8px">Close</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 8px">Defect Leaked to UAT</td>
    <td style="background-color:rgb(0,255,255);font-weight:bold;text-align:center;border:1px solid #000;padding:4px 8px">Defect Leakage to UAT (%)</td>
  </tr>
  {bug_rows_html}
</table><br>
<br>
<div>Defect Density% = <b>({total_bugs_all}/{TOTAL_TCS})*100 = {defect_density_pct}%</b> <i>(Total Number of defects found in QA / Total number of Test cases designed by QA)*100</i></div>
<div>Defect Leakage % = <b>(0/0)*100 = {defect_leakage_pct}%</b> <i>(Total Number of defects found in UAT /[(Total number of defects found in QA +Total number of defects found in UAT)]*100</i></div>
<div>Defect Rejection Rate - <b>{REJECTED_BUGS}/{total_bugs_all + REJECTED_BUGS} - {rejection_rate_pct}%</b> <i>(Total no. of defects Rejected by Dev/Total no. of defects reported by QA)*100</i></div><br>
<br>
<div><b><u>Sprint Automation:</u></b></div><br>
<div style="text-align:left">{s1_images_html}</div>{auto_html}<br>
<div><b><u>Reference Links: </u></b></div>
<div>Automation Link: &nbsp;<a href="https://docs.google.com/spreadsheets/d/1pPGbmCjh-mPEu4pNvCKDtzhMEylFUPiG/edit#gid=1772547475">QA Automation Results</a></div>
<div><b>QA - Regression Test Cases across all the tracks</b>: <a href="https://docs.google.com/spreadsheets/d/1ot9t0gzC0BRY_DBQongaf4mvAi7JwHI6acK5yrCKgGI/edit?gid=393341500#gid=393341500">TC Sheet</a></div>
<div>CAB: <b>Yet To Create</b></div>
<div>Status report: <a href="https://drive.google.com/drive/u/0/folders/1vdPP7M8QBA3Mj8qhSfSs_runBc8YBCQP"><b>QA Sprint Status Reports</b></a></div>
<div>QA Metrics: <a href="https://rubrik.atlassian.net/wiki/spaces/IS/pages/2729771113/Software+Testing+Metrics+QA+Metrics"><b>QA Metrics</b></a></div><br>
<div>Please find the attached &quot;<b>Test_Status_Report_{SPRINT_NAME}</b>&quot; document containing</div>
<ul>
  <li>Test summary</li>
  <li>Test Case Coverage</li>
  <li>Defect report</li>
</ul>
<div>Since all the open issues in QA have been addressed, we have provided the <span style="background-color:#00FF00;font-weight:bold">QA sign-off for Sprint {SPRINT_NO}.</span></div><br>
<div>In case you are not able to access the file, I have added it to the attached file section of this email for your reference. Please find the attachment.</div><br>
<div>Thanks &amp; Regards</div>
</font></div>"""
```

### 8b — Download xlsx from Drive and send via Gmail API with attachment

Two separate tokens are required — use each for its purpose:
- **Drive token** (`~/.gdrive-mcp-token.json`) → export XLSX via Drive API
- **Gmail token** (`~/.gmail-mcp-token.json`) → send email via Gmail API

```python
import base64, email.mime.multipart, email.mime.text, email.mime.application

# ── Load and refresh both tokens ──────────────────────────────────
def refresh_token(d, path):
    if d.get('expires_at', 0) < datetime.datetime.now().timestamp() + 60:
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=urllib.parse.urlencode({
                "client_id": d["client_id"], "client_secret": d["client_secret"],
                "refresh_token": d["refresh_token"], "grant_type": "refresh_token"
            }).encode(), method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        resp = json.loads(urllib.request.urlopen(req, context=ctx).read())
        d['access_token'] = resp['access_token']
        d['expires_at'] = datetime.datetime.now().timestamp() + resp.get('expires_in', 3600)
        with open(path, 'w') as f2:
            json.dump(d, f2)
    return d['access_token']

with open(Path.home() / ".gdrive-mcp-token.json") as f:
    dd = json.load(f)
with open(Path.home() / ".gmail-mcp-token.json") as f:
    gd = json.load(f)

DRIVE_TOKEN = refresh_token(dd, str(Path.home() / ".gdrive-mcp-token.json"))
GMAIL_TOKEN = refresh_token(gd, str(Path.home() / ".gmail-mcp-token.json"))

# ── Step 1: Download the uploaded xlsx from Drive (Drive token) ──
# FILE_ID comes from sprint_data.json (saved by Script B)
_sd_for_attach = json.loads(Path("/tmp/sprint_data.json").read_text("utf-8"))
FILE_ID        = _sd_for_attach.get("xlsx_file_id", FILE_ID if "FILE_ID" in dir() else "")
LOCAL_XLSX     = _sd_for_attach.get("xlsx_local_path", "")
try:
    _drive_xlsx_path = Path("/tmp/sprint_drive_for_email.xlsx")
    # Always prefer Drive so the attachment reflects any user edits made after upload.
    if FILE_ID:
        dl_url = f"https://www.googleapis.com/drive/v3/files/{FILE_ID}?alt=media"
        req = urllib.request.Request(dl_url, headers={"Authorization": f"Bearer {DRIVE_TOKEN}"})
        xlsx_bytes = urllib.request.urlopen(req, context=ctx).read()
        print(f"XLSX downloaded fresh from Drive: {len(xlsx_bytes):,} bytes")
        has_attachment = True
    elif _drive_xlsx_path.exists():
        xlsx_bytes = _drive_xlsx_path.read_bytes()
        print(f"XLSX from local cache: {len(xlsx_bytes):,} bytes")
        has_attachment = True
    elif LOCAL_XLSX and Path(LOCAL_XLSX).exists():
        xlsx_bytes = Path(LOCAL_XLSX).read_bytes()
        print(f"XLSX loaded from local: {len(xlsx_bytes):,} bytes")
        has_attachment = True
    else:
        print("⚠ No xlsx file ID — will send without attachment.")
        xlsx_bytes = b""
        has_attachment = False
except Exception as e:
    print(f"⚠ XLSX download failed: {e} — will send without attachment.")
    xlsx_bytes = b""
    has_attachment = False

# ── Step 2: Build multipart MIME message ──────────────────────────
ATTACHMENT_NAME = f"Test_Status_Report_{PROJECT}_FY27-Sprint_{SPRINT_NO}.xlsx"
SUBJECT = f"Test_Status_Report_{PROJECT}_{SPRINT_NAME.replace(' ', '_')}_Signoff"
# FINAL_TO  = list of To  addresses (from Step 7)
# FINAL_CC  = list of CC  addresses (from Step 7, may be empty)
# FINAL_FROM = sender address or None (from Step 7)

msg = email.mime.multipart.MIMEMultipart("mixed")
msg["Subject"] = SUBJECT
if FINAL_FROM:
    msg["From"] = FINAL_FROM
msg["To"]   = ", ".join(FINAL_TO)
if FINAL_CC:
    msg["Cc"] = ", ".join(FINAL_CC)
msg.attach(email.mime.text.MIMEText(email_html, "html"))

if has_attachment:
    att = email.mime.application.MIMEApplication(xlsx_bytes,
          _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    att.add_header("Content-Disposition", "attachment", filename=ATTACHMENT_NAME)
    msg.attach(att)

# ── Step 3: Base64url-encode and send via Gmail API (Gmail token) ──
raw_b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode()
send_req = urllib.request.Request(
    "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
    data=json.dumps({"raw": raw_b64}).encode(),
    method="POST",
    headers={"Authorization": f"Bearer {GMAIL_TOKEN}", "Content-Type": "application/json"})
send_resp = json.loads(urllib.request.urlopen(send_req, context=ctx).read())
print("Email sent:", send_resp.get("id"), "→ thread:", send_resp.get("threadId"))
```

**Rules for Step 8:**
- **Drive token** exports the XLSX; **Gmail token** sends the email — never swap them.
- Export format is **XLSX** (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`) — covers all 4 tabs in one file.
- Attachment filename: `Test_Status_Report_{PROJECT}_FY27-Sprint_{SPRINT_NO}.xlsx`
- Send to all `@rubrik.com` addresses in a single email.
- For non-`@rubrik.com` addresses: fall back to `mcp__gmail__draft_email` (no attachment possible) and note: `"⚠ Draft created for {address} — send manually."`
- If the XLSX export fails (e.g. permissions error), fall back to sending without attachment and warn: `"⚠ Could not attach XLSX — sent without attachment."`

---

## STEP 9 — Final Summary

```
Sprint QA Report — DONE
==========================================
Project    : {PROJECT}
Sprint     : {SPRINT_NAME}
Dates      : {START_DATE} to {END_DATE}
QA Status  : {OVERALL_STATUS}
TC Source  : Google Sheet — tab "{MATCHED_TAB_TITLE}"
TC Tab URL : {TC_SPRINT_TAB_URL}

Metrics:
  Stories        : {TOTAL_STORIES}
  Total TCs      : {TOTAL_TCS}
  Pass           : {TOTAL_PASS}  ({EXEC_PCT:.1f}%)
  Bugs           : {TOTAL_BUGS}
  Defect Density : {DEFECT_DENSITY:.2f}%
  Defect Leakage : {DEFECT_LEAKAGE:.2f}%

Pipeline:
  QA Qualified  : {QA_QUALIFIED}
  QA Completed  : {QA_COMPLETED}
  Ready for UAT : {READY_UAT}
  UAT Completed : {UAT_COMPLETED}

Bugs:
  P0: {p0_total} ({p0_closed} closed, {p0_open} open)
  P1: {p1_total} ({p1_closed} closed, {p1_open} open)
  P2: {p2_total} ({p2_closed} closed, {p2_open} open)
  P3: {p3_total} ({p3_closed} closed, {p3_open} open)

==========================================
xlsx Report  : {xlsx_link}
Email To     : {", ".join(FINAL_TO)}
Email CC     : {", ".join(FINAL_CC) if FINAL_CC else "(none)"}
Email From   : {FINAL_FROM or "(authenticated account)"}
==========================================
```

---

## Rules

- **TC sheet has a built-in default** — never ask the user for it; accept it only if voluntarily provided as the 4th argument
- **Required inputs: Sprint Name + Start Date + End Date** — stop and ask if any are missing; TC sheet URL is optional (4th arg)
- **TC counts MUST come from the Google Sheet** — never use JIRA sub-tasks
- Always match sprint name to TC sheet tab; warn clearly if no match
- Always query JIRA for both stories AND bugs
- **4 tab names and order are fixed:** `Reports` (idx 0) | `Overall Summary` (idx 1) | `TestCase Coverage` (idx 2) | `Sheet1` (idx 3)
- Build directly in Google Sheets via Sheets API — skip local Excel generation
- Use **urllib** (not requests) with `ssl.CERT_NONE` context for all API calls
- **TC rows MUST be uploaded to Google Sheets** as one contiguous range via `ALL_DATA.append(("TestCase Coverage!A15", tc_vals))`
- After Drive upload, **STOP** and wait for user to review/fill in the report
- **Re-read the Drive sheet** after user confirms recipients — use updated values, not cached
- Email From/To/CC can be supplied as `from=`/`to=`/`cc=` arguments or given interactively after report upload; reply values override argument values
- Send to all `@rubrik.com` recipients in a single email; draft for others
- All cell values must be **strings** (convert all ints/floats before writing)
- Priority mapping: Highest/Blocker→P0, High→P1, Medium→P2, Low→P3
- **Compare to TEMPLATE_FILE_ID `1hzMv6nkTkfrMATAZ686mImB1e8U66kg5` structure before generating**
- BAR chart series MUST use `targetAxis="BOTTOM_AXIS"` (not LEFT_AXIS)
- Sheets API field paths: use `userEnteredFormat.backgroundColor` (camelCase, not snake_case)
- Tab creation order is CRITICAL — see Step 6 for exact sequence to get correct 4-tab order
