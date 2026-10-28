"""Developer Console — run Anonymous Apex and SOQL against QA / UAT.

Everything goes through the Salesforce CLI (`sf`), so it uses the same logged-in
sessions as the rest of the app. No credentials are stored. Purely additive:
does not import anything from Order_Validation_App.py or the other pages (it
only imports the shared stylesheet from theme.py).
"""

import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# theme.py lives in the project root, one level above pages/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from theme import apply_theme  # noqa: E402

st.set_page_config(page_title="Developer Console · Rubrik", page_icon="🛠️", layout="wide")
apply_theme("devconsole")

# Candidate CLI aliases per environment, first one that resolves wins.
# (README documents qa-org, but some machines have the QA org saved as rbkqa.)
ORG_ALIASES = {
    "QA":  ["qa-org", "rbkqa"],
    "UAT": ["uat-org"],
}

APEX_TIMEOUT_S = 120
SOQL_TIMEOUT_S = 60
MAX_HISTORY = 25

# Anything that can change data or org state. Used only to decide whether to
# ask for confirmation before running — not a security boundary.
_DML_PATTERN = re.compile(
    r"\b(insert|update|upsert|delete|undelete|merge)\b"
    r"|\bDatabase\.(insert|update|upsert|delete|undelete|merge|executeBatch)\b"
    r"|\bSystem\.(enqueueJob|schedule|schedule[A-Za-z]*)\b",
    re.IGNORECASE,
)

SAMPLE_APEX = """\
// Anonymous Apex — runs as your user in the selected org.
Order o = [SELECT Id, OrderNumber, Status FROM Order LIMIT 1];
System.debug('Order ' + o.OrderNumber + ' is ' + o.Status);
"""

SAMPLE_SOQL = "SELECT Id, OrderNumber, Status, EffectiveDate FROM Order ORDER BY CreatedDate DESC LIMIT 20"


# ── CLI helpers ───────────────────────────────────────────────────────────────
def _run_cli(cmd: list, timeout: int) -> dict:
    """Run an sf command with --json and return the parsed payload (never raises)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return {"status": 1, "message": "Salesforce CLI (`sf`) not found on PATH."}
    except subprocess.TimeoutExpired:
        return {"status": 1, "message": f"Timed out after {timeout}s."}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        msg = (proc.stderr or proc.stdout or "No output from sf CLI.").strip()
        return {"status": 1, "message": msg}


@st.cache_data(ttl=60, show_spinner=False)
def resolve_org(env: str) -> dict:
    """Find the first alias for `env` that the CLI knows. Returns alias/username/instance_url."""
    last_msg = "No matching org alias found."
    for alias in ORG_ALIASES[env]:
        data = _run_cli(["sf", "org", "display", "--target-org", alias, "--json"], 20)
        result = data.get("result") or {}
        if data.get("status") == 0 and result.get("username"):
            return {
                "alias": alias,
                "username": result["username"],
                "instance_url": result.get("instanceUrl", ""),
                "error": "",
            }
        last_msg = data.get("message", last_msg)
    return {"alias": "", "username": "", "instance_url": "", "error": last_msg}


def run_apex(alias: str, code: str) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".apex", delete=False, encoding="utf-8") as fh:
        fh.write(code)
        path = fh.name
    try:
        return _run_cli(["sf", "apex", "run", "--file", path, "--target-org", alias, "--json"], APEX_TIMEOUT_S)
    finally:
        Path(path).unlink(missing_ok=True)


def run_soql(alias: str, soql: str, tooling: bool, all_rows: bool) -> dict:
    cmd = ["sf", "data", "query", "--query", " ".join(soql.split()), "--target-org", alias, "--json"]
    if tooling:
        cmd.append("--use-tooling-api")
    if all_rows:
        cmd.append("--all-rows")
    return _run_cli(cmd, SOQL_TIMEOUT_S)


def records_to_df(records: list) -> pd.DataFrame:
    """Flatten SOQL records (drops `attributes`, expands relationship fields like Account.Name)."""
    if not records:
        return pd.DataFrame()
    df = pd.json_normalize(records, sep=".")
    return df.drop(columns=[c for c in df.columns if c == "attributes" or c.endswith(".attributes.type")
                            or c.endswith(".attributes.url") or c == "attributes.type" or c == "attributes.url"],
                   errors="ignore")


def add_history(kind: str, body: str, ok: bool, elapsed: float, env: str):
    hist = st.session_state.setdefault("devconsole_history", [])
    hist.insert(0, {
        "time": datetime.now().strftime("%H:%M:%S"),
        "kind": kind, "env": env, "ok": ok,
        "elapsed": f"{elapsed:.1f}s", "body": body,
    })
    del hist[MAX_HISTORY:]


def load_into_editor(kind: str, body: str):
    st.session_state["apex_code" if kind == "Apex" else "soql_text"] = body


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
        <div class="sidebar-brand-title">🛠️ Developer Console</div>
        <div class="sidebar-brand-sub">Rubrik ProdOps · Salesforce CLI</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section-label">Salesforce Connection</div>', unsafe_allow_html=True)
    env = st.selectbox("Environment", list(ORG_ALIASES.keys()), key="devconsole_env")
    org = resolve_org(env)
    if org["alias"]:
        st.success(f"Connected ✅\n\n`{org['username']}`")
        st.caption(f"Alias: `{org['alias']}`")
    else:
        st.error("Not connected")
        st.caption(org["error"])
        st.code(f"sf org login device --alias {ORG_ALIASES[env][0]}", language="bash")
    if st.button("🔄 Re-check connection", use_container_width=True):
        resolve_org.clear()
        st.rerun()

    st.markdown("---")
    with st.expander(f"📜 History ({len(st.session_state.get('devconsole_history', []))})"):
        hist = st.session_state.get("devconsole_history", [])
        if not hist:
            st.caption("Nothing run yet this session.")
        for i, h in enumerate(hist):
            icon = "✅" if h["ok"] else "❌"
            first_line = h["body"].strip().splitlines()[0][:40] if h["body"].strip() else ""
            st.button(f"{icon} {h['time']} · {h['env']} · {h['kind']}\n{first_line}",
                      key=f"hist_{i}", use_container_width=True,
                      on_click=load_into_editor, args=(h["kind"], h["body"]))

st.markdown(f"""
<div class="app-header">
    <div class="app-header-icon">🛠️</div>
    <div class="app-header-text">
        <h1>Developer Console</h1>
        <p>Run Anonymous Apex and SOQL against Salesforce &nbsp;·&nbsp; Rubrik ProdOps</p>
    </div>
    <div class="app-header-tags">
        <span class="app-tag">⚡ Salesforce CLI</span>
        <span class="app-tag">🔒 QA &amp; UAT</span>
        <span class="app-tag">🎯 {env}</span>
    </div>
</div>
""", unsafe_allow_html=True)
st.caption("Every run uses your own Salesforce CLI session")

if not org["alias"]:
    st.warning("Connect to the selected org first (see sidebar), then click **Re-check connection**.")
    st.stop()

tab_apex, tab_soql = st.tabs(["⚡ Anonymous Apex", "🔎 SOQL Query"])

# ── Anonymous Apex ────────────────────────────────────────────────────────────
with tab_apex:
    st.session_state.setdefault("apex_code", SAMPLE_APEX)
    code = st.text_area("Apex code", key="apex_code", height=320,
                        help="Executed as a single anonymous Apex request.")

    changes_data = bool(_DML_PATTERN.search(re.sub(r"//.*|/\*.*?\*/", "", code, flags=re.DOTALL)))
    confirmed = True
    if changes_data:
        st.warning(f"This script looks like it can **modify data or enqueue work** in {env}.")
        confirmed = st.checkbox(f"I understand this will run against {env} ({org['username']})",
                                key="apex_confirm")

    c1, c2 = st.columns([1, 5])
    run_clicked = c1.button("▶ Execute", type="primary", disabled=not confirmed or not code.strip(),
                            key="apex_run")
    only_debug = c2.checkbox("Show only USER_DEBUG lines", value=True, key="apex_only_debug")

    if run_clicked:
        t0 = time.time()
        with st.spinner(f"Executing in {env}..."):
            resp = run_apex(org["alias"], code)
        elapsed = time.time() - t0
        res = resp.get("result") or {}
        ok = resp.get("status") == 0 and res.get("compiled") and res.get("success")
        add_history("Apex", code, bool(ok), elapsed, env)
        st.session_state["apex_last"] = {"resp": resp, "elapsed": elapsed, "ok": bool(ok)}

    last = st.session_state.get("apex_last")
    if last:
        resp, res = last["resp"], last["resp"].get("result") or {}
        if last["ok"]:
            st.success(f"Executed successfully in {last['elapsed']:.1f}s")
        elif res and not res.get("compiled", True):
            st.error(f"Compile error — line {res.get('line')}, column {res.get('column')}: "
                     f"{res.get('compileProblem')}")
        elif res:
            st.error(f"Runtime exception: {res.get('exceptionMessage')}")
            if res.get("exceptionStackTrace"):
                st.code(res["exceptionStackTrace"])
        else:
            st.error(resp.get("message", "Execution failed."))

        log = res.get("logs", "")
        if log:
            lines = log.splitlines()
            shown = [l for l in lines if "|USER_DEBUG|" in l] if only_debug else lines
            if only_debug:
                # Keep just the message part: "12:00:00.0 (123)|USER_DEBUG|[3]|DEBUG|hello"
                shown = [l.split("|DEBUG|", 1)[-1] if "|DEBUG|" in l else l for l in shown]
            st.markdown(f"**Debug log** ({len(lines)} lines)")
            st.code("\n".join(shown) or "(no USER_DEBUG output)", language="text")
            st.download_button("⬇ Download full log", log, file_name="apex_debug.log", key="apex_dl")

# ── SOQL ──────────────────────────────────────────────────────────────────────
with tab_soql:
    st.session_state.setdefault("soql_text", SAMPLE_SOQL)
    soql = st.text_area("SOQL", key="soql_text", height=140)
    o1, o2, o3 = st.columns([1, 1, 4])
    tooling = o1.checkbox("Tooling API", key="soql_tooling")
    all_rows = o2.checkbox("Include deleted", key="soql_all_rows")
    if o3.button("▶ Run query", type="primary", disabled=not soql.strip(), key="soql_run"):
        t0 = time.time()
        with st.spinner(f"Querying {env}..."):
            resp = run_soql(org["alias"], soql, tooling, all_rows)
        elapsed = time.time() - t0
        add_history("SOQL", soql, resp.get("status") == 0, elapsed, env)
        st.session_state["soql_last"] = {"resp": resp, "elapsed": elapsed}

    last = st.session_state.get("soql_last")
    if last:
        resp = last["resp"]
        if resp.get("status") == 0:
            result = resp.get("result", {})
            df = records_to_df(result.get("records", []))
            st.success(f"{result.get('totalSize', 0)} row(s) in {last['elapsed']:.1f}s")
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.download_button("⬇ Download CSV", df.to_csv(index=False), file_name="soql_result.csv",
                                   mime="text/csv", key="soql_dl")
        else:
            st.error(resp.get("message", "Query failed."))
