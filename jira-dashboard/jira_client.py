from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import json as _json
import os as _os
import re
import re as _re
import threading as _threading
import time

import requests
from requests.auth import HTTPBasicAuth
from config import JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN

def _validate_project_key(key: str) -> str:
    """Raises ValueError if key is not a valid Jira project key."""
    if not key or not _re.match(r'^[A-Z][A-Z0-9_]{0,49}$', key):
        raise ValueError(f"Invalid project key: {key!r}")
    return key


def _validate_date(date_str: str) -> str:
    """Raises ValueError if date_str is not YYYY-MM-DD format."""
    if date_str and not _re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        raise ValueError(f"Invalid date format: {date_str!r}")
    return date_str


def _validate_sprint_id(sprint_id) -> str:
    """Raises ValueError if sprint_id is not numeric."""
    if sprint_id is not None and not _re.match(r'^\d+$', str(sprint_id)):
        raise ValueError(f"Invalid sprint_id: {sprint_id!r}")
    return sprint_id


_TC_SHEET_PROJECT = "SMT2"
_EXPECTED_TC_SHEET_ID = "1GpOHlUz2PexRcgIZPkqrfqB9l79ZhAMJkc7KY3GcFek"

# ── SLA Configuration ────────────────────────────────────────────────────────

_DEFAULT_SLA_HOURS = {
    "Ready for QA": 24,
    "QA In Progress": 48,
    "UAT Sanity Testing": 8,
    "Ready for UAT": 24,
    "Ready for UAT Deployment": 24,
    "UAT Deployment Completed": 24,
}

_DATA_DIR = _os.path.join(_os.path.dirname(__file__), "data")
_SETTINGS_PATH = _os.path.join(_DATA_DIR, "settings.json")
_ALERTS_HISTORY_PATH = _os.path.join(_DATA_DIR, "alerts_history.json")
_SPRINT_SNAPSHOTS_PATH = _os.path.join(_DATA_DIR, "sprint_snapshots.json")
_os.makedirs(_DATA_DIR, exist_ok=True)  # ensure data/ directory exists at import time


def get_settings_value(key, default=None):
    """Read a single value from data/settings.json, returning default if missing."""
    try:
        if _os.path.exists(_SETTINGS_PATH):
            with open(_SETTINGS_PATH) as f:
                return _json.load(f).get(key, default)
    except Exception:
        pass
    return default


def get_sla_hours() -> dict:
    """Return SLA thresholds from settings.json, falling back to defaults."""
    try:
        if _os.path.exists(_SETTINGS_PATH):
            with open(_SETTINGS_PATH) as f:
                s = _json.load(f)
            sla = s.get("sla_hours", {})
            if sla:
                merged = dict(_DEFAULT_SLA_HOURS)
                merged.update(sla)
                return merged
    except Exception:
        pass
    return dict(_DEFAULT_SLA_HOURS)


# ── Alert History ─────────────────────────────────────────────────────────────

_history_lock = _threading.Lock()
_alerts_history_mem: dict = {}
_alerts_history_mem_ts: float = 0.0
_ALERTS_HISTORY_MEM_TTL = 30  # seconds


def _load_alerts_history() -> dict:
    global _alerts_history_mem, _alerts_history_mem_ts
    now = time.monotonic()
    if now - _alerts_history_mem_ts < _ALERTS_HISTORY_MEM_TTL:
        return _alerts_history_mem
    try:
        if _os.path.exists(_ALERTS_HISTORY_PATH):
            with open(_ALERTS_HISTORY_PATH) as f:
                data = _json.load(f)
        else:
            data = {}
    except Exception:
        data = {}
    _alerts_history_mem = data
    _alerts_history_mem_ts = now
    return data


def _save_alerts_history(data: dict):
    global _alerts_history_mem, _alerts_history_mem_ts
    _os.makedirs(_os.path.dirname(_ALERTS_HISTORY_PATH), exist_ok=True)
    with open(_ALERTS_HISTORY_PATH, "w") as f:
        _json.dump(data, f, indent=2)
    _alerts_history_mem = data
    _alerts_history_mem_ts = time.monotonic()


def was_comment_sent_recently(issue_key: str, alert_type: str, cooldown_hours: int = None) -> bool:
    """Returns True if a comment of this alert_type was already sent for this issue within cooldown_hours."""
    if cooldown_hours is None:
        cooldown_hours = get_settings_value("alert_cooldown_hours", 24)
    with _history_lock:
        history = _load_alerts_history()
        key = f"{issue_key}:{alert_type}"
        entry = history.get(key)
        if not entry:
            return False
        try:
            sent_dt = datetime.fromisoformat(entry["sent_at"])
            if sent_dt.tzinfo is None:
                sent_dt = sent_dt.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - sent_dt).total_seconds() / 3600
            return age_hours < cooldown_hours
        except Exception:
            return False


def record_comment_sent(issue_key: str, alert_type: str):
    """Record that an alert comment was sent for this issue."""
    with _history_lock:
        history = _load_alerts_history()
        key = f"{issue_key}:{alert_type}"
        history[key] = {
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "issue_key": issue_key,
            "alert_type": alert_type,
        }
        if len(history) > 1000:
            oldest_keys = sorted(history, key=lambda k: history[k].get("sent_at", ""))[:len(history) - 1000]
            for k in oldest_keys:
                del history[k]
        _save_alerts_history(history)


# ── Sprint Snapshots ──────────────────────────────────────────────────────────

def _load_sprint_snapshots() -> list:
    try:
        if _os.path.exists(_SPRINT_SNAPSHOTS_PATH):
            with open(_SPRINT_SNAPSHOTS_PATH) as f:
                return _json.load(f)
    except Exception:
        pass
    return []


def _save_sprint_snapshot(snapshot: dict):
    snapshots = _load_sprint_snapshots()
    key = f"{snapshot['project_key']}:{snapshot.get('sprint_id', 'all')}"
    snapshots = [s for s in snapshots if f"{s['project_key']}:{s.get('sprint_id', 'all')}" != key]
    snapshots.append(snapshot)
    snapshots = snapshots[-20:]
    _os.makedirs(_os.path.dirname(_SPRINT_SNAPSHOTS_PATH), exist_ok=True)
    with open(_SPRINT_SNAPSHOTS_PATH, "w") as f:
        _json.dump(snapshots, f, indent=2)

_DESIGN_KEYWORDS = (
    "test case design", "test case creation", "test case review",
    "test design", "test cases preparation", "preparation", "test case writing",
)


def _extract_adf_urls(node):
    """Walk an Atlassian Document Format node and return all URLs found in links/cards."""
    urls = []
    if isinstance(node, dict):
        for mark in node.get("marks", []):
            if mark.get("type") == "link":
                href = mark.get("attrs", {}).get("href", "")
                if href:
                    urls.append(href)
        if node.get("type") in ("inlineCard", "blockCard", "embedCard"):
            url = node.get("attrs", {}).get("url", "")
            if url:
                urls.append(url)
        for child in node.get("content", []):
            urls.extend(_extract_adf_urls(child))
    elif isinstance(node, list):
        for item in node:
            urls.extend(_extract_adf_urls(item))
    return urls


def _check_design_sheet_mismatch(issue_key: str, subtasks: list) -> bool:
    """Returns True if a Test Case Design subtask exists but doesn't link to the expected TC sheet."""
    if not issue_key.startswith(_TC_SHEET_PROJECT):
        return False
    for st in subtasks:
        summary = st.get("fields", {}).get("summary", "").lower()
        if not any(k in summary for k in _DESIGN_KEYWORDS):
            continue
        st_key = st.get("key")
        if not st_key:
            continue
        cache_key = f"design_sheet:{st_key}"
        has_correct_sheet = _cache_get(cache_key)
        if has_correct_sheet is None:
            try:
                resp = _session.get(
                    f"{JIRA_URL}/rest/api/3/issue/{st_key}",
                    params={"fields": "description"},
                )
                resp.raise_for_status()
                desc = resp.json().get("fields", {}).get("description")
                urls = _extract_adf_urls(desc) if desc else []
                has_correct_sheet = any(_EXPECTED_TC_SHEET_ID in u for u in urls)
                _cache_set(cache_key, has_correct_sheet)
            except Exception:
                has_correct_sheet = False  # treat API error as sheet missing (conservative)
        if not has_correct_sheet:
            return True
    return False

_cache: dict = {}
_CACHE_TTL_DEFAULT = 300  # seconds (5 minutes)

def _cache_get(key):
    entry = _cache.get(key)
    if entry:
        ttl = get_settings_value("cache_ttl", _CACHE_TTL_DEFAULT)
        if time.time() - entry[1] < ttl:
            return entry[0]
    return None

def _cache_set(key, value):
    _cache[key] = (value, time.time())

def clear_cache():
    _cache.clear()

QA_STATUSES = [
    "Ready for QA",
    "QA In Progress",
    "QA Completed",
    "Ready for UAT",
    "Ready for UAT Deployment",
    "UAT Deployment Completed",
    "UAT Sanity Testing",
]

EPIC_SIGNOFF_TASKS = [
    {"summary": "QA: ProdOps Sign-Off",        "assignee_name": "Ashwini Koppad",     "qa_name": "Ashwini Koppad"},
    {"summary": "QA: Revenue Sign-Off",        "assignee_name": "Neethu Krishnan",    "qa_name": "Neethu Krishnan"},
    {"summary": "QA: CPQ Sign-off",            "assignee_name": "Sreeveena Chowdary", "qa_name": "Sreeveena Chowdary"},
    {"summary": "QA: Test Case Validation",    "assignee_name": "Sreeveena Chowdary", "qa_name": "Sreeveena Chowdary"},
]

PRODOPS_QA_TEAM = [
    "Ashish Samar",
    "Ashwini Koppad",
    "Bhavani Marupaka",
    "Karthik Surada",
    "Teekshna Vallivireddy",
    "US Mahesh Reddy",
    "Urati Sai Krishna",
    "Amara MaheshKumar",
    "Shashi Kumar",
]


class _TimeoutSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", 15)
        return super().request(method, url, **kwargs)


_session = _TimeoutSession()
_session.auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
_session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})


def test_connection(retries: int = 2):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = _session.get(f"{JIRA_URL}/rest/api/3/myself")
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise last_exc


def get_projects():
    cached = _cache_get("projects")
    if cached is not None:
        return cached
    results = []
    start = 0
    while True:
        resp = _session.get(
            f"{JIRA_URL}/rest/api/3/project/search",
            params={"startAt": start, "maxResults": 50, "orderBy": "name"},
        )
        resp.raise_for_status()
        data = resp.json()
        for p in data.get("values", []):
            results.append({
                "key": p["key"],
                "name": p["name"],
                "avatar": p.get("avatarUrls", {}).get("24x24"),
            })
        if data.get("isLast", True):
            break
        start += 50
    _cache_set("projects", results)
    return results


def get_sprints(project_key: str):
    _validate_project_key(project_key)
    cache_key = f"sprints:{project_key}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    resp = _session.get(
        f"{JIRA_URL}/rest/agile/1.0/board",
        params={"projectKeyOrId": project_key},
    )
    resp.raise_for_status()
    boards = resp.json().get("values", [])

    seen_ids = set()
    all_sprints = []
    for board in boards:
        try:
            sprint_resp = _session.get(
                f"{JIRA_URL}/rest/agile/1.0/board/{board['id']}/sprint",
                params={"state": "active,future,closed", "maxResults": 50},
            )
            sprint_resp.raise_for_status()
            sprints = sprint_resp.json().get("values", [])
            for s in sprints:
                if s["id"] not in seen_ids:
                    seen_ids.add(s["id"])
                    all_sprints.append({
                        "id": s["id"],
                        "name": s["name"],
                        "state": s["state"],
                        "startDate": s.get("startDate"),
                        "endDate": s.get("endDate"),
                    })
        except Exception:
            continue

    _cache_set(cache_key, all_sprints)
    return all_sprints


def _business_hours_elapsed(start: datetime, end: datetime) -> float:
    """Hours between start and end, excluding any time that falls on a Saturday or Sunday."""
    if start >= end:
        return 0.0
    total_seconds = 0.0
    cursor = start
    while cursor < end:
        next_midnight = (cursor + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        segment_end = min(end, next_midnight)
        if cursor.weekday() < 5:  # Monday=0 ... Friday=4; Saturday=5, Sunday=6 are skipped
            total_seconds += (segment_end - cursor).total_seconds()
        cursor = segment_end
    return total_seconds / 3600


def _check_qa_update_missing(comment_field, status_name: str = "Ready for QA"):
    if not comment_field or not isinstance(comment_field, dict):
        return True
    comments = comment_field.get("comments", [])
    if not comments:
        return True
    latest = comments[-1]
    created_str = latest.get("created", "")
    if not created_str:
        return True
    try:
        created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        sla_hours = get_sla_hours().get(status_name, 24)
        age_hours = _business_hours_elapsed(created_dt, datetime.now(timezone.utc))
        return age_hours > sla_hours
    except Exception:
        return False


def add_comment(issue_key: str, qa_name: str, account_id: str = None,
                message_suffix: str = ", can you please update the QA Progress?",
                message_prefix: str = "", alert_type: str = "qa_update",
                force: bool = False):
    if not force and was_comment_sent_recently(issue_key, alert_type):
        return {"skipped": True, "reason": "Comment already sent within cooldown period"}
    mention_node = (
        {"type": "mention", "attrs": {"id": account_id, "text": f"@{qa_name}"}}
        if account_id
        else {"type": "text", "text": f"@{qa_name}"}
    )
    para_content = []
    if message_prefix:
        para_content.append({"type": "text", "text": message_prefix})
    para_content.append(mention_node)
    para_content.append({"type": "text", "text": message_suffix})
    body = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": para_content,
                }
            ],
        }
    }
    resp = _session.post(f"{JIRA_URL}/rest/api/3/issue/{issue_key}/comment", json=body)
    resp.raise_for_status()
    record_comment_sent(issue_key, alert_type)
    return resp.json()


def _get_open_execution_subtask(subtasks: list):
    """Return {key, assigneeName, assigneeId} for the first non-Done execution subtask, or None."""
    for st in subtasks:
        fields = st.get("fields", {})
        summary = fields.get("summary", "").lower()
        st_status = fields.get("status", {}).get("statusCategory", {}).get("key", "").lower()
        is_execution = any(k in summary for k in ("test case execution", "test cases execution", "test execution"))
        if is_execution and st_status != "done":
            st_key = st.get("key")
            cached = _cache_get(f"st_assignee:{st_key}")
            if cached is not None:
                return cached
            assignee = {}
            try:
                resp = _session.get(
                    f"{JIRA_URL}/rest/api/3/issue/{st_key}",
                    params={"fields": "assignee"},
                )
                resp.raise_for_status()
                assignee = resp.json().get("fields", {}).get("assignee") or {}
            except Exception:
                pass
            result = {
                "key": st_key,
                "assigneeName": assignee.get("displayName", ""),
                "assigneeId": assignee.get("accountId", ""),
            }
            _cache_set(f"st_assignee:{st_key}", result)
            return result
    return None


def _get_open_design_subtask(subtasks: list):
    """Return {key, assigneeName, assigneeId} for the first Open/In Progress design subtask, or None.
    Fetches subtask details to get assignee since the subtasks array only has minimal fields."""
    for st in subtasks:
        fields = st.get("fields", {})
        summary = fields.get("summary", "").lower()
        st_status = fields.get("status", {}).get("statusCategory", {}).get("key", "").lower()
        is_design = any(k in summary for k in ("test case design", "test case creation", "test case review", "test design", "test cases preparation", "preparation", "test case writing"))
        if is_design and st_status != "done":
            st_key = st.get("key")
            cached = _cache_get(f"st_assignee:{st_key}")
            if cached is not None:
                return cached
            assignee = {}
            has_comment = False
            try:
                resp = _session.get(
                    f"{JIRA_URL}/rest/api/3/issue/{st_key}",
                    params={"fields": "assignee,comment"},
                )
                resp.raise_for_status()
                st_fields = resp.json().get("fields", {})
                assignee = st_fields.get("assignee") or {}
                cf = st_fields.get("comment")
                has_comment = bool(cf and cf.get("comments"))
            except Exception:
                pass
            result = {
                "key": st_key,
                "assigneeName": assignee.get("displayName", ""),
                "assigneeId": assignee.get("accountId", ""),
                "hasComment": has_comment,
            }
            _cache_set(f"st_assignee:{st_key}", result)
            return result
    return None


_SUBTASK_PREFETCH_FIELDS = [
    "summary", "status", "assignee",
    "customfield_12726", "customfield_16854",
    "description", "comment",
]


def _prefetch_subtasks(issues: list):
    """Batch-fetch all subtask details before parallel _process_issue() calls.

    Collects every subtask key from the issues list, fetches them all in one
    JQL query (100 keys per page), and pre-populates the four cache namespaces
    that _process_issue() helpers read:
      st_assignee:{key}  — _get_open_design_subtask
      st_qa:{key}        — _check_subtasks_qa_contact
      design_sheet:{key} — _check_design_sheet_mismatch
      unit_test:{key}    — _check_unit_test_results_in_comments
    """
    seen: set = set()
    all_keys: list = []
    for issue in issues:
        for st in issue.get("fields", {}).get("subtasks", []):
            k = st.get("key")
            if k and k not in seen:
                seen.add(k)
                all_keys.append(k)

    if not all_keys:
        return

    batches = [all_keys[i:i + 100] for i in range(0, len(all_keys), 100)]

    def _fetch_batch(batch):
        keys_csv = ", ".join(batch)
        try:
            return _fetch_all_issues(f"key in ({keys_csv})", _SUBTASK_PREFETCH_FIELDS)
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=min(len(batches), 10)) as executor:
        batch_results = list(executor.map(_fetch_batch, batches))

    for fetched in batch_results:
        for st in fetched:
            k = st["key"]
            f = st["fields"]
            summary_lower = f.get("summary", "").lower()
            status_cat = f.get("status", {}).get("statusCategory", {}).get("key", "").lower()
            is_design = any(kw in summary_lower for kw in _DESIGN_KEYWORDS)

            # st_qa — _check_subtasks_qa_contact
            _cache_set(f"st_qa:{k}", bool(f.get("customfield_12726") or f.get("customfield_16854")))

            # unit_test — _check_unit_test_results_in_comments
            if "unit test" in summary_lower:
                cf = f.get("comment")
                _cache_set(f"unit_test:{k}", bool(cf and cf.get("comments")))

            # design_sheet — _check_design_sheet_mismatch (SMT2 only)
            if is_design:
                desc = f.get("description")
                urls = _extract_adf_urls(desc) if desc else []
                _cache_set(f"design_sheet:{k}", any(_EXPECTED_TC_SHEET_ID in u for u in urls))

            # st_assignee — _get_open_design_subtask
            if is_design and status_cat != "done":
                assignee = f.get("assignee") or {}
                cf = f.get("comment")
                _cache_set(f"st_assignee:{k}", {
                    "key": k,
                    "assigneeName": assignee.get("displayName", ""),
                    "assigneeId": assignee.get("accountId", ""),
                    "hasComment": bool(cf and cf.get("comments")),
                })


_DESIGN_QA_KEYWORDS = ("test case design", "test case creation", "test case review", "test design", "test cases preparation", "preparation", "test case writing")
_EXECUTION_QA_KEYWORDS = ("test case execution", "test cases execution", "test execution")


def _is_design_qa_subtask(summary_lower: str) -> bool:
    """True if a subtask summary counts as the Test Case Design subtask.

    Beyond the exact _DESIGN_QA_KEYWORDS phrases, accept any summary that just
    mentions "test case" (e.g. "Test Cases for GTMIT-706") as long as it isn't
    actually the execution subtask.
    """
    if any(k in summary_lower for k in _DESIGN_QA_KEYWORDS):
        return True
    return "test case" in summary_lower and "execution" not in summary_lower

def _check_subtasks_qa_contact(subtasks: list) -> list:
    """Return list of {key, summary} for Test Case Design/Execution subtasks missing QA Contact.
    Subtasks array only has minimal fields, so each subtask is fetched individually (cached)."""
    missing = []
    for st in subtasks:
        st_key = st.get("key")
        st_summary = st.get("fields", {}).get("summary", st_key)
        st_status_cat = st.get("fields", {}).get("status", {}).get("statusCategory", {}).get("key", "").lower()
        if st_status_cat == "done":
            continue
        summary_lower = st_summary.lower()
        is_relevant = any(k in summary_lower for k in _DESIGN_QA_KEYWORDS) or any(k in summary_lower for k in _EXECUTION_QA_KEYWORDS)
        if not is_relevant:
            continue
        cache_key = f"st_qa:{st_key}"
        has_qa = _cache_get(cache_key)
        if has_qa is None:
            try:
                resp = _session.get(
                    f"{JIRA_URL}/rest/api/3/issue/{st_key}",
                    params={"fields": "customfield_12726,customfield_16854"},
                )
                resp.raise_for_status()
                f = resp.json().get("fields", {})
                has_qa = bool(f.get("customfield_12726") or f.get("customfield_16854"))
            except Exception:
                has_qa = True  # skip on error
            _cache_set(cache_key, has_qa)
        if not has_qa:
            missing.append({"key": st_key, "summary": st_summary})
    return missing


def _process_issue(issue):
    fields = issue["fields"]
    subtasks = fields.get("subtasks", [])
    subtask_names = [st.get("fields", {}).get("summary", "") for st in subtasks]
    rca_field = fields.get("customfield_13446")
    sprint_field = fields.get("customfield_10006") or []
    status_name = fields.get("status", {}).get("name", "Unknown")
    is_prdops_story = (
        issue["key"].startswith("PRDOPS-")
        and fields.get("issuetype", {}).get("name", "") == "Story"
    )
    qa_update_missing = (
        is_prdops_story
        and status_name in ("Ready for QA", "QA In Progress")
        and _check_qa_update_missing(fields.get("comment"), status_name)
    )
    uat_sanity_missing = (
        is_prdops_story
        and status_name == "UAT Sanity Testing"
        and _check_qa_update_missing(fields.get("comment"), "UAT Sanity Testing")
    )
    design_subtask_invalid, execution_subtask_invalid = _check_subtasks_open_in_ready_for_qa(status_name, subtasks)
    subtasks_qa_contact_missing = _check_subtasks_qa_contact(subtasks)
    subtasks_missing = _check_subtasks_missing(status_name, subtasks)
    comment_field = fields.get("comment")
    latest_comment = None
    if comment_field and isinstance(comment_field, dict):
        comments = comment_field.get("comments", [])
        if comments:
            last = comments[-1]
            raw_text = _extract_description_text(last.get("body", "")).strip()
            comment_text = re.sub(r"\[~accountid:[^\]]+\]", "", raw_text).strip()
            if comment_text:
                latest_comment = {
                    "author": (last.get("author") or {}).get("displayName", "Unknown"),
                    "text": comment_text,
                    "created": last.get("created", ""),
                }
    return {
        "key": issue["key"],
        "url": f"{JIRA_URL}/browse/{issue['key']}",
        "summary": fields.get("summary", ""),
        "status": status_name,
        "statusCategory": _get_status_category(fields.get("status", {})),
        "issueType": fields.get("issuetype", {}).get("name", ""),
        "priority": fields.get("priority", {}).get("name", "None") if fields.get("priority") else "None",
        "reporter": _extract_person(fields.get("reporter")),
        "assignee": _extract_person(fields.get("assignee")),
        "qaContact": _extract_person(fields.get("customfield_12726") or fields.get("customfield_16854")),
        "labels": fields.get("labels", []),
        "created": fields.get("created", ""),
        "subtaskNames": subtask_names,
        "hasUnitTestSubtask": any("unit test" in n.lower() for n in subtask_names),
        "hasUnitTestComment": _check_unit_test_results_in_comments(
            fields.get("comment"), fields.get("assignee"), subtasks
        ),
        "descriptionText": _extract_description_text(fields.get("description")),
        "expectedOutcome": _extract_description_text(fields.get("customfield_10701")),
        "actualOutcome": _extract_description_text(fields.get("customfield_10702")),
        "stepsToReproduce": _extract_description_text(fields.get("customfield_10703")),
        "rca": rca_field.get("value", "") if isinstance(rca_field, dict) else "",
        "rootCauseSummary": _extract_description_text(fields.get("customfield_12712")),
        "sprintNames": [s.get("name", "") for s in sprint_field if isinstance(s, dict)],
        "qaUpdateMissing": qa_update_missing,
        "uatSanityMissing": uat_sanity_missing,
        "designSubtaskInvalid": design_subtask_invalid,
        "executionSubtaskInvalid": execution_subtask_invalid,
        "openDesignSubtask": _get_open_design_subtask(subtasks),
        "openExecutionSubtask": _get_open_execution_subtask(subtasks),
        "subtasksQaContactMissing": subtasks_qa_contact_missing,
        "tcSheetMissing": _check_design_sheet_mismatch(issue["key"], subtasks),
        "latestComment": latest_comment,
        "subtasksMissing": subtasks_missing,
        "alertSentAt": _load_alerts_history().get(f"{issue['key']}:qa_update", {}).get("sent_at"),
    }


def get_issues(project_key: str, sprint_id: str = None, issue_type: str = None,
               created_from: str = None, created_to: str = None):
    _validate_project_key(project_key)
    _validate_sprint_id(sprint_id)
    _validate_date(created_from)
    _validate_date(created_to)
    if issue_type and issue_type.lower() == "epic":
        return _get_epic_issues(project_key, sprint_id, created_from=created_from, created_to=created_to)

    result_cache_key = f"issues_result:{project_key}:{sprint_id}:{issue_type}:{created_from}:{created_to}"
    cached = _cache_get(result_cache_key)
    if cached is not None:
        return cached

    fields_list = [
        "summary", "status", "issuetype", "priority",
        "reporter", "assignee", "labels", "created",
        "customfield_12726", "customfield_16854",
        "customfield_13446", "customfield_12712",
        "customfield_10006",
        "customfield_10701", "customfield_10702", "customfield_10703",
        "subtasks", "description", "comment",
    ]

    if sprint_id:
        if issue_type:
            type_map = {"story": "Story", "bug": "Bug", "defect": "Bug"}
            mapped = type_map.get(issue_type.lower(), issue_type)
            types = [mapped]
        else:
            types = ["Story", "Bug"]
        all_issues = _fetch_sprint_issues(sprint_id, fields_list=fields_list,
                                          project_key=project_key, issue_types=types)
    else:
        jql_parts = [f"project = {project_key}"]
        if issue_type:
            type_map = {"story": "Story", "bug": "Bug", "defect": "Bug"}
            mapped = type_map.get(issue_type.lower(), issue_type)
            jql_parts.append(f'issuetype = "{mapped}"')
        else:
            jql_parts.append("issuetype in (Story, Bug)")
        if created_from:
            jql_parts.append(f'created >= "{created_from}"')
        if created_to:
            jql_parts.append(f'created <= "{created_to}"')
        jql = " AND ".join(jql_parts) + " ORDER BY priority DESC, created DESC"
        all_issues = _fetch_all_issues(jql, fields_list)

    _prefetch_subtasks(all_issues)
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(_process_issue, all_issues))

    _cache_set(result_cache_key, results)
    return results


def _fetch_sprint_issues(sprint_id: str, fields_list: list = None,
                         project_key: str = None, issue_types: list = None):
    # Try Agile API first (works for company-managed projects)
    try:
        agile_issues = _fetch_sprint_issues_agile(sprint_id, fields_list)
        if agile_issues:
            if project_key:
                agile_issues = [i for i in agile_issues
                                if i.get("fields", {}).get("project", {}).get("key") == project_key]
            if issue_types:
                lower_types = [t.lower() for t in issue_types]
                agile_issues = [i for i in agile_issues
                                if i.get("fields", {}).get("issuetype", {}).get("name", "").lower()
                                in lower_types]
            if agile_issues:
                return agile_issues
    except Exception:
        pass

    # Fallback for team-managed projects: fetch via JQL, filter by sprint field
    if not project_key:
        return []

    jql_parts = [f"project = {project_key}"]
    if issue_types:
        types_str = ", ".join(issue_types)
        jql_parts.append(f"issuetype in ({types_str})")
    jql = " AND ".join(jql_parts) + " ORDER BY priority DESC, created DESC"

    extended_fields = list(set(fields_list or []) | {"customfield_10006"})
    all_issues = _fetch_all_issues(jql, extended_fields)

    filtered = []
    sid = str(sprint_id)
    for issue in all_issues:
        sprints = issue.get("fields", {}).get("customfield_10006") or []
        for s in sprints:
            if isinstance(s, dict) and str(s.get("id")) == sid:
                filtered.append(issue)
                break
            elif isinstance(s, str) and sid in s:
                filtered.append(issue)
                break
    return filtered


def _fetch_sprint_issues_agile(sprint_id: str, fields_list: list = None):
    resp = _session.get(f"{JIRA_URL}/rest/agile/1.0/sprint/{sprint_id}")
    resp.raise_for_status()
    board_id = resp.json().get("originBoardId")

    all_issues = []
    start_at = 0
    while True:
        params = {"startAt": start_at, "maxResults": 100}
        if fields_list:
            all_fields = set(fields_list) | {"project", "issuetype"}
            params["fields"] = ",".join(all_fields)

        if board_id:
            url = f"{JIRA_URL}/rest/agile/1.0/board/{board_id}/sprint/{sprint_id}/issue"
        else:
            url = f"{JIRA_URL}/rest/agile/1.0/sprint/{sprint_id}/issue"

        resp = _session.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        issues = data.get("issues", [])
        all_issues.extend(issues)
        if start_at + len(issues) >= data.get("total", 0):
            break
        start_at += len(issues)
    return all_issues


def _fetch_all_issues(jql: str, fields_list: list):
    all_issues = []
    next_token = None
    while True:
        body = {"jql": jql, "maxResults": 100, "fields": fields_list}
        if next_token:
            body["nextPageToken"] = next_token
        resp = _session.post(
            f"{JIRA_URL}/rest/api/3/search/jql",
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        all_issues.extend(data.get("issues", []))
        if data.get("isLast", True):
            break
        next_token = data.get("nextPageToken")
        if not next_token:
            break
    return all_issues


def _get_epic_issues(project_key: str, sprint_id: str = None,
                     created_from: str = None, created_to: str = None):
    child_fields = ["summary", "status", "issuetype", "priority", "parent",
                    "assignee", "customfield_12726", "customfield_16854",
                    "subtasks", "description", "comment", "customfield_13446",
                    "customfield_12712", "customfield_10006",
                    "customfield_10701", "customfield_10702", "customfield_10703"]

    epic_fields = [
        "summary", "status", "issuetype", "priority",
        "reporter", "assignee", "labels", "created",
        "customfield_12726", "customfield_16854",
    ]

    # pre_fetched_epics is set when we fetch epics first (date filter path)
    # so we skip the second epic fetch in the shared code below
    pre_fetched_epics = None

    if sprint_id:
        sprint_children = _fetch_sprint_issues(sprint_id, fields_list=child_fields,
                                               project_key=project_key, issue_types=["Story", "Bug"])
        epic_keys = set()
        for child in sprint_children:
            parent = child["fields"].get("parent")
            if parent and parent.get("key"):
                epic_keys.add(parent["key"])
        if not epic_keys:
            return []
        keys_list = ", ".join(epic_keys)
        all_children_jql = (
            f"parent in ({keys_list}) AND issuetype in (Story, Bug, Task) "
            f"ORDER BY priority DESC"
        )
        children = _fetch_all_issues(all_children_jql, child_fields)

    elif created_from or created_to:
        # Date filter: apply to EPIC's own creation date, then fetch their children.
        # (applying the date to children would incorrectly show old epics that have
        # recently-created children)
        epic_date_parts = [f"project = {project_key}", "issuetype = Epic"]
        if created_from:
            epic_date_parts.append(f'created >= "{created_from}"')
        if created_to:
            epic_date_parts.append(f'created <= "{created_to}"')
        epic_date_jql = " AND ".join(epic_date_parts) + " ORDER BY priority DESC, created DESC"
        pre_fetched_epics = _fetch_all_issues(epic_date_jql, epic_fields)
        if not pre_fetched_epics:
            return []
        keys_csv = ", ".join(e["key"] for e in pre_fetched_epics)
        children_jql = (
            f"parent in ({keys_csv}) AND issuetype in (Story, Bug, Task) "
            f"ORDER BY priority DESC"
        )
        children = _fetch_all_issues(children_jql, child_fields)

    else:
        child_jql = (
            f'project = {project_key} AND issuetype in (Story, Bug, Task) '
            f'ORDER BY priority DESC'
        )
        children = _fetch_all_issues(child_jql, child_fields)

    epic_keys = set()
    children_by_epic = {}
    for child in children:
        parent = child["fields"].get("parent")
        if parent and parent.get("key"):
            pk = parent["key"]
            epic_keys.add(pk)
            children_by_epic.setdefault(pk, []).append(child)

    if pre_fetched_epics is not None:
        # Already fetched epics in the date-filter path above
        epics = pre_fetched_epics
    else:
        if not epic_keys:
            return []
        keys_csv = ", ".join(epic_keys)
        epic_jql = f"key in ({keys_csv}) ORDER BY priority DESC, created DESC"
        epics = _fetch_all_issues(epic_jql, epic_fields)

    # Process all children across all epics in parallel (same pattern as get_issues)
    all_children_flat = [c for epic in epics for c in children_by_epic.get(epic["key"], [])]
    _prefetch_subtasks(all_children_flat)
    with ThreadPoolExecutor(max_workers=20) as executor:
        processed_children = list(executor.map(_process_issue, all_children_flat))
    processed_by_key = {p["key"]: p for p in processed_children}

    results = []
    for epic in epics:
        fields = epic["fields"]
        epic_children_raw = children_by_epic.get(epic["key"], [])

        status_counts = {}
        for c in epic_children_raw:
            s = c["fields"].get("status", {}).get("name", "Unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        child_summaries = [processed_by_key[c["key"]] for c in epic_children_raw if c["key"] in processed_by_key]

        status = fields.get("status", {})
        qa_contact = _extract_person(
            fields.get("customfield_12726") or fields.get("customfield_16854")
        )

        results.append({
            "key": epic["key"],
            "url": f"{JIRA_URL}/browse/{epic['key']}",
            "summary": fields.get("summary", ""),
            "status": status.get("name", "Unknown"),
            "statusCategory": _get_status_category(status),
            "issueType": "Epic",
            "priority": fields.get("priority", {}).get("name", "None") if fields.get("priority") else "None",
            "reporter": _extract_person(fields.get("reporter")),
            "assignee": _extract_person(fields.get("assignee")),
            "qaContact": qa_contact,
            "labels": fields.get("labels", []),
            "created": fields.get("created", ""),
            "subtaskNames": [],
            "descriptionText": "",
            "rca": "",
            "rootCauseSummary": "",
            "sprintNames": [],
            "childCount": len(epic_children_raw),
            "childStatusSummary": status_counts,
            "children": child_summaries,
        })

    return results


def _get_parent_sprint_id(issue_key: str):
    resp = _session.get(
        f"{JIRA_URL}/rest/api/3/issue/{issue_key}",
        params={"fields": "customfield_10020"},
    )
    resp.raise_for_status()
    sprint_field = resp.json().get("fields", {}).get("customfield_10020")
    if isinstance(sprint_field, list) and sprint_field:
        return sprint_field[-1].get("id")
    if isinstance(sprint_field, dict):
        return sprint_field.get("id")
    return None


def _get_epic_key(issue_key: str):
    resp = _session.get(
        f"{JIRA_URL}/rest/api/3/issue/{issue_key}",
        params={"fields": "parent"},
    )
    resp.raise_for_status()
    parent = resp.json().get("fields", {}).get("parent", {})
    if parent and parent.get("fields", {}).get("issuetype", {}).get("name", "").lower() == "epic":
        return parent.get("key")
    return None


def create_subtasks(parent_key: str, project_key: str, subtask_summaries: list):
    _validate_project_key(project_key)
    subtask_type_id = _get_subtask_type_id(project_key)
    qa_account_id = _get_qa_contact_account_id(parent_key)

    if parent_key.startswith("ITNPI-"):
        sprint_source_key = _get_epic_key(parent_key) or parent_key
    else:
        sprint_source_key = parent_key
    sprint_id = _get_parent_sprint_id(sprint_source_key)

    created = []
    for summary in subtask_summaries:
        fields = {
            "project": {"key": project_key},
            "parent": {"key": parent_key},
            "issuetype": {"id": subtask_type_id},
            "summary": summary,
        }
        if qa_account_id:
            fields["assignee"] = {"accountId": qa_account_id}
            fields["customfield_12726"] = {"accountId": qa_account_id}
        if sprint_id:
            fields["customfield_10020"] = [sprint_id]

        resp = _session.post(
            f"{JIRA_URL}/rest/api/3/issue",
            json={"fields": fields},
        )
        resp.raise_for_status()
        created.append(resp.json()["key"])
    return created


def _get_qa_contact_account_id(issue_key: str):
    resp = _session.get(
        f"{JIRA_URL}/rest/api/3/issue/{issue_key}",
        params={"fields": "customfield_12726,customfield_16854"},
    )
    resp.raise_for_status()
    fields = resp.json().get("fields", {})
    qa = fields.get("customfield_12726") or fields.get("customfield_16854")
    if qa and isinstance(qa, dict):
        return qa.get("accountId")
    return None


def get_qa_contacts(project_keys: list):
    cache_key = f"qa_contacts:{','.join(sorted(project_keys))}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    keys_jql = ", ".join(project_keys)
    jql = (
        f"project in ({keys_jql}) AND "
        f"(cf[12726] is not EMPTY OR cf[16854] is not EMPTY) "
        f"ORDER BY created DESC"
    )
    try:
        issues = _fetch_all_issues(jql, ["customfield_12726", "customfield_16854"])
    except Exception:
        issues = []

    seen_ids = set()
    candidates = []
    for issue in issues:
        f = issue["fields"]
        qa = f.get("customfield_12726") or f.get("customfield_16854")
        if not qa or not isinstance(qa, dict):
            continue
        account_id = qa.get("accountId")
        if not account_id or account_id in seen_ids:
            continue
        seen_ids.add(account_id)
        candidates.append({
            "name": qa.get("displayName", "Unknown"),
            "accountId": account_id,
            "avatar": qa.get("avatarUrls", {}).get("24x24"),
        })

    def _is_active(contact):
        try:
            resp = _session.get(
                f"{JIRA_URL}/rest/api/3/user",
                params={"accountId": contact["accountId"]},
            )
            resp.raise_for_status()
            return contact if resp.json().get("active", True) else None
        except Exception:
            return contact

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(_is_active, candidates))

    active_contacts = sorted([c for c in results if c], key=lambda x: x["name"])
    _cache_set(cache_key, active_contacts)
    return active_contacts


def get_issues_by_qa_contact(qa_name: str):
    if not qa_name or '"' in qa_name:
        raise ValueError("Invalid qa_name")

    account_id = _get_account_id_by_name(qa_name)
    if not account_id:
        return []
    if not _re.match(r'^[a-zA-Z0-9:_-]+$', account_id):
        raise ValueError(f"Unexpected account_id format: {account_id!r}")

    fields_list = [
        "summary", "status", "issuetype", "priority",
        "reporter", "assignee", "labels", "created",
        "customfield_12726", "customfield_16854",
        "customfield_13446", "customfield_12712",
        "customfield_10006",
        "customfield_10701", "customfield_10702", "customfield_10703",
        "subtasks", "description", "comment",
    ]
    jql = (
        f'(cf[12726] = "{account_id}" OR assignee = "{account_id}") '
        f'AND issuetype in (Story, Bug) '
        f'ORDER BY priority DESC, created DESC'
    )
    try:
        raw_issues = _fetch_all_issues(jql, fields_list)
    except Exception:
        return []

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(_process_issue, raw_issues))

    return results


def _get_subtask_type_id(project_key: str):
    resp = _session.get(f"{JIRA_URL}/rest/api/3/project/{project_key}")
    resp.raise_for_status()
    project_id = resp.json()["id"]

    resp2 = _session.get(
        f"{JIRA_URL}/rest/api/3/issuetype/project",
        params={"projectId": project_id},
    )
    resp2.raise_for_status()
    for t in resp2.json():
        if t.get("subtask") and t["name"].lower() in ("sub-task", "subtask"):
            return str(t["id"])
    raise ValueError(f"No Sub-task issue type found for project {project_key}")


def _get_account_id_by_name(display_name: str):
    cache_key = f"user_account_id:{display_name}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    resp = _session.get(
        f"{JIRA_URL}/rest/api/3/user/search",
        params={"query": display_name, "maxResults": 10},
    )
    resp.raise_for_status()
    account_id = None
    for u in resp.json():
        if u.get("displayName", "").lower() == display_name.lower():
            account_id = u.get("accountId")
            break
    _cache_set(cache_key, account_id)
    return account_id


def _get_task_type_id(project_key: str):
    resp = _session.get(f"{JIRA_URL}/rest/api/3/project/{project_key}")
    resp.raise_for_status()
    project_id = resp.json()["id"]

    resp2 = _session.get(
        f"{JIRA_URL}/rest/api/3/issuetype/project",
        params={"projectId": project_id},
    )
    resp2.raise_for_status()
    types = resp2.json()

    for preferred in ("task", "story"):
        for t in types:
            if not t.get("subtask") and t["name"].lower() == preferred:
                return str(t["id"])
    raise ValueError(f"No Task or Story issue type found for project {project_key}")


def create_epic_signoff_tasks(epic_key: str, project_key: str, task_summaries: list):
    _validate_project_key(project_key)
    task_type_id = _get_task_type_id(project_key)
    sprint_id = _get_parent_sprint_id(epic_key)

    task_map = {t["summary"]: t for t in EPIC_SIGNOFF_TASKS}

    created = []
    for summary in task_summaries:
        task_def = task_map.get(summary)
        fields = {
            "project": {"key": project_key},
            "parent": {"key": epic_key},
            "issuetype": {"id": task_type_id},
            "summary": summary,
        }
        if sprint_id:
            fields["customfield_10020"] = [sprint_id]
        warning = None

        if task_def:
            assignee_id = _get_account_id_by_name(task_def["assignee_name"])
            qa_id = _get_account_id_by_name(task_def["qa_name"])

            if assignee_id:
                fields["assignee"] = {"accountId": assignee_id}
            else:
                warning = f"Assignee '{task_def['assignee_name']}' not found"

            if qa_id:
                fields["customfield_12726"] = {"accountId": qa_id}

        resp = _session.post(
            f"{JIRA_URL}/rest/api/3/issue",
            json={"fields": fields},
        )
        resp.raise_for_status()
        created.append({
            "key": resp.json()["key"],
            "summary": summary,
            "warning": warning,
        })

    return created


def assign_qa_contact(issue_key: str, account_id: str):
    resp = _session.put(
        f"{JIRA_URL}/rest/api/3/issue/{issue_key}",
        json={"fields": {"customfield_12726": {"accountId": account_id}}},
    )
    resp.raise_for_status()


def assign_qa_contact_by_name(issue_key: str, display_name: str):
    account_id = _get_account_id_by_name(display_name)
    if not account_id:
        raise ValueError(f"Could not find JIRA user: {display_name}")
    assign_qa_contact(issue_key, account_id)


def get_qa_tracking(project_key: str, sprint_id: str = None,
                    created_from: str = None, created_to: str = None):
    _validate_project_key(project_key)
    _validate_sprint_id(sprint_id)
    _validate_date(created_from)
    _validate_date(created_to)

    result_cache_key = f"qa_tracking_result:{project_key}:{sprint_id}:{created_from}:{created_to}"
    cached = _cache_get(result_cache_key)
    if cached is not None:
        return cached

    fields_list = ["summary", "status", "issuetype", "priority",
                   "assignee", "customfield_12726", "customfield_16854"]

    if sprint_id:
        all_issues = _fetch_sprint_issues(sprint_id, fields_list=fields_list,
                                          project_key=project_key, issue_types=["Story", "Bug"])
    else:
        jql_parts = [f"project = {project_key}", "issuetype in (Story, Bug)"]
        if created_from:
            jql_parts.append(f'created >= "{created_from}"')
        if created_to:
            jql_parts.append(f'created <= "{created_to}"')
        jql = " AND ".join(jql_parts) + " ORDER BY priority DESC, created DESC"
        all_issues = _fetch_all_issues(jql, fields_list)

    qa_issues = []
    for issue in all_issues:
        fields = issue["fields"]
        qa_contact = _extract_person(
            fields.get("customfield_12726") or fields.get("customfield_16854")
        )
        if qa_contact["name"] == "Unassigned":
            continue
        qa_issues.append((issue, qa_contact))

    tracking_map = {}
    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_key = {
            executor.submit(_get_status_durations, issue["key"]): issue["key"]
            for issue, _ in qa_issues
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            tracking_map[key] = future.result()

    results = []
    for issue, qa_contact in qa_issues:
        fields = issue["fields"]
        results.append({
            "key": issue["key"],
            "url": f"{JIRA_URL}/browse/{issue['key']}",
            "summary": fields.get("summary", ""),
            "issueType": fields.get("issuetype", {}).get("name", ""),
            "priority": fields.get("priority", {}).get("name", "None") if fields.get("priority") else "None",
            "currentStatus": fields.get("status", {}).get("name", "Unknown"),
            "assignee": _extract_person(fields.get("assignee")),
            "qaContact": qa_contact,
            "qaStatusTimes": tracking_map.get(issue["key"], []),
        })

    _cache_set(result_cache_key, results)
    return results


def _get_status_durations(issue_key: str):
    cache_key = f"status_durations:{issue_key}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    resp = _session.get(
        f"{JIRA_URL}/rest/api/3/issue/{issue_key}",
        params={"expand": "changelog", "fields": "status"},
    )
    resp.raise_for_status()
    data = resp.json()

    transitions = []
    for history in data.get("changelog", {}).get("histories", []):
        created = history["created"]
        for item in history.get("items", []):
            if item["field"] == "status":
                transitions.append({
                    "timestamp": created,
                    "fromStatus": item["fromString"],
                    "toStatus": item["toString"],
                })

    transitions.sort(key=lambda t: t["timestamp"])

    durations = {}
    spans = {}
    for qa_status in QA_STATUSES:
        durations[qa_status] = 0.0
        spans[qa_status] = []

    now = datetime.now(timezone.utc)

    for i, t in enumerate(transitions):
        to_status = t["toStatus"]
        if to_status not in durations:
            continue

        entered = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))

        exited = None
        is_current = False
        for j in range(i + 1, len(transitions)):
            if transitions[j]["fromStatus"] == to_status:
                exited = datetime.fromisoformat(
                    transitions[j]["timestamp"].replace("Z", "+00:00")
                )
                break

        if exited is None:
            current_status = data.get("fields", {}).get("status", {}).get("name", "")
            if current_status == to_status:
                exited = now
                is_current = True
            else:
                continue

        hours = (exited - entered).total_seconds() / 3600
        durations[to_status] += hours
        spans[to_status].append({
            "entered": entered.strftime("%b %d, %Y %I:%M %p"),
            "exited": "Now (current)" if is_current else exited.strftime("%b %d, %Y %I:%M %p"),
        })

    result = []
    for status in QA_STATUSES:
        rounded = round(durations[status], 1)
        if rounded > 0:
            result.append({
                "status": status,
                "hours": rounded,
                "spans": spans[status],
            })

    _cache_set(cache_key, result)
    return result


def _check_unit_test_in_comments(comment_field, assignee_field):
    if not comment_field or not isinstance(comment_field, dict):
        return False
    assignee_id = None
    if assignee_field and isinstance(assignee_field, dict):
        assignee_id = assignee_field.get("accountId")
    for comment in comment_field.get("comments", []):
        body_text = _extract_description_text(comment.get("body"))
        body_lower = body_text.lower()
        if "unit test" in body_lower or "unit result" in body_lower or "test result" in body_lower:
            return True
    return False


def _check_subtasks_open_in_ready_for_qa(status_name: str, subtasks: list) -> tuple:
    is_active_qa = status_name in ("Ready for QA", "QA In Progress")
    is_late_qa = status_name in (
        "QA Completed", "Ready for UAT", "UAT Sanity Testing",
        "Ready for UAT Deployment", "UAT Deployment Completed",
    )
    design_invalid = False
    execution_invalid = False
    for st in subtasks:
        summary = st.get("fields", {}).get("summary", "").lower()
        st_status = st.get("fields", {}).get("status", {}).get("name", "").lower()
        st_status_cat = st.get("fields", {}).get("status", {}).get("statusCategory", {}).get("key", "").lower()
        is_done = st_status_cat == "done"
        is_design = any(k in summary for k in ("test case design", "test case creation", "test case review", "test design", "test cases preparation", "preparation", "test case writing"))
        is_execution = any(k in summary for k in ("test case execution", "test cases execution", "test execution"))
        if is_design and st_status == "open":
            design_invalid = True
        if is_design and is_late_qa and not is_done:
            design_invalid = True
        if is_execution and (is_active_qa or is_late_qa) and st_status == "open":
            execution_invalid = True
        if is_execution and (is_active_qa or is_late_qa) and not is_done:
            execution_invalid = True
    return design_invalid, execution_invalid


def _check_subtasks_missing(status_name: str, subtasks: list) -> dict:
    """Check if required TC Design/Execution subtasks are completely absent."""
    needs_design = status_name in (
        "Ready for QA", "QA In Progress", "QA Completed",
        "Ready for UAT", "UAT Sanity Testing",
        "Ready for UAT Deployment", "UAT Deployment Completed",
    )
    needs_execution = status_name in (
        "QA In Progress", "QA Completed",
        "Ready for UAT", "UAT Sanity Testing",
        "Ready for UAT Deployment", "UAT Deployment Completed",
    )
    if not needs_design and not needs_execution:
        return {"design": False, "execution": False}

    has_design = any(
        _is_design_qa_subtask(st.get("fields", {}).get("summary", "").lower())
        for st in subtasks
    )
    has_execution = any(
        any(k in st.get("fields", {}).get("summary", "").lower() for k in _EXECUTION_QA_KEYWORDS)
        for st in subtasks
    )
    return {
        "design": needs_design and not has_design,
        "execution": needs_execution and not has_execution,
    }


_ACTIVE_QA_STATUSES = (
    "Ready for QA", "QA In Progress", "Ready for UAT",
    "Ready for UAT Deployment", "UAT Sanity Testing", "UAT Deployment Completed",
)


def get_workload(project_key: str, sprint_id: str = None):
    _validate_project_key(project_key)
    _validate_sprint_id(sprint_id)

    fields_list = ["summary", "status", "issuetype", "priority",
                   "assignee", "customfield_12726", "customfield_16854"]

    if sprint_id:
        issues = _fetch_sprint_issues(sprint_id, fields_list=fields_list,
                                      project_key=project_key, issue_types=["Story", "Bug"])
    else:
        jql = f"project = {project_key} AND issuetype in (Story, Bug) ORDER BY created DESC"
        issues = _fetch_all_issues(jql, fields_list)

    workload = {}
    for issue in issues:
        f = issue["fields"]
        status_name = f.get("status", {}).get("name", "Unknown")
        if status_name not in _ACTIVE_QA_STATUSES:
            continue
        qa = f.get("customfield_12726") or f.get("customfield_16854")
        if not qa or not isinstance(qa, dict):
            continue
        name = qa.get("displayName", "Unknown")
        if name not in workload:
            workload[name] = {
                "name": name,
                "avatar": qa.get("avatarUrls", {}).get("24x24"),
                "accountId": qa.get("accountId"),
                "statuses": {},
                "total": 0,
            }
        workload[name]["statuses"][status_name] = workload[name]["statuses"].get(status_name, 0) + 1
        workload[name]["total"] += 1

    result = sorted(workload.values(), key=lambda x: -x["total"])
    return result


def get_velocity(project_key: str, sprint_id: str = None):
    _validate_project_key(project_key)
    _validate_sprint_id(sprint_id)

    tracking_data = get_qa_tracking(project_key, sprint_id)
    velocity = {}
    for item in tracking_data:
        qa_name = item.get("qaContact", {}).get("name", "Unassigned")
        if qa_name == "Unassigned":
            continue
        if qa_name not in velocity:
            velocity[qa_name] = {
                "name": qa_name,
                "avatar": item.get("qaContact", {}).get("avatar"),
                "issues_count": 0,
                "avg_ready_to_in_progress": [],
                "avg_in_progress_to_completed": [],
                "avg_total_qa_time": [],
            }
        velocity[qa_name]["issues_count"] += 1
        status_times = {s["status"]: s["hours"] for s in item.get("qaStatusTimes", [])}
        rq_h = status_times.get("Ready for QA", 0)
        qp_h = status_times.get("QA In Progress", 0)
        qc_h = status_times.get("QA Completed", 0)
        if rq_h > 0:
            velocity[qa_name]["avg_ready_to_in_progress"].append(rq_h)
        if qp_h > 0:
            velocity[qa_name]["avg_in_progress_to_completed"].append(qp_h)
        if rq_h + qp_h + qc_h > 0:
            velocity[qa_name]["avg_total_qa_time"].append(rq_h + qp_h + qc_h)

    def _avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    result = []
    for v in velocity.values():
        result.append({
            "name": v["name"],
            "avatar": v["avatar"],
            "issues_count": v["issues_count"],
            "avg_pickup_hours": _avg(v["avg_ready_to_in_progress"]),
            "avg_qa_hours": _avg(v["avg_in_progress_to_completed"]),
            "avg_total_hours": _avg(v["avg_total_qa_time"]),
        })
    result.sort(key=lambda x: -(x["issues_count"]))
    return result


def _check_unit_test_results_in_comments(parent_comment_field, assignee_field, subtasks):
    # Check "Unit Testing" subtask first — any comment at all counts as results posted
    for st in subtasks:
        st_summary = st.get("fields", {}).get("summary", "")
        if "unit test" in st_summary.lower():
            st_key = st.get("key")
            if not st_key:
                continue
            cache_key = f"unit_test:{st_key}"
            has_comments = _cache_get(cache_key)
            if has_comments is None:
                try:
                    resp = _session.get(
                        f"{JIRA_URL}/rest/api/3/issue/{st_key}",
                        params={"fields": "comment"},
                    )
                    resp.raise_for_status()
                    st_comment_field = resp.json().get("fields", {}).get("comment")
                    has_comments = bool(st_comment_field and st_comment_field.get("comments"))
                    _cache_set(cache_key, has_comments)
                except Exception:
                    continue
            if has_comments:
                return True
    # Fall back to keyword matching in parent story comments
    return _check_unit_test_in_comments(parent_comment_field, assignee_field)


def _get_status_category(status_field):
    cat = status_field.get("statusCategory", {}).get("name", "")
    if cat == "Done":
        return "Done"
    if cat == "In Progress":
        return "In Progress"
    return "To Do"


def _extract_description_text(desc):
    if not desc:
        return ""
    if isinstance(desc, str):
        return desc
    texts = []
    _walk_adf(desc, texts)
    return " ".join(texts)


def _walk_adf(node, texts):
    if isinstance(node, dict):
        if node.get("type") == "text":
            texts.append(node.get("text", ""))
        elif node.get("type") == "mention":
            mention_text = node.get("attrs", {}).get("text", "")
            if mention_text:
                texts.append(mention_text)
        for child in node.get("content", []):
            _walk_adf(child, texts)
    elif isinstance(node, list):
        for item in node:
            _walk_adf(item, texts)


def _extract_person(person_field):
    if not person_field:
        return {"name": "Unassigned", "avatar": None, "accountId": None}
    return {
        "name": person_field.get("displayName", "Unknown"),
        "avatar": person_field.get("avatarUrls", {}).get("24x24"),
        "accountId": person_field.get("accountId"),
    }
