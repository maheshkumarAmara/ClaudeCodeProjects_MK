import streamlit as st
import subprocess
import json
import io
import base64
import calendar
import concurrent.futures
from datetime import datetime, timedelta
from pathlib import Path
import requests
import pandas as pd

# ── Persistent data directory ─────────────────────────────────────────────────
DATA_DIR          = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE      = DATA_DIR / "history.json"
KNOWN_ISSUES_FILE = DATA_DIR / "known_issues.json"
JIRA_CONFIG_FILE  = DATA_DIR / "jira_config.json"

def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except (json.JSONDecodeError, OSError):
        return default

def _write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2))

def load_history() -> list:
    return _read_json(HISTORY_FILE, [])

def append_history(run: dict):
    history = load_history()
    history.append(run)
    _write_json(HISTORY_FILE, history[-50:])

def load_known_issues() -> dict:
    return _read_json(KNOWN_ISSUES_FILE, {})

def save_known_issues(data: dict):
    _write_json(KNOWN_ISSUES_FILE, data)

def load_jira_config() -> dict:
    return _read_json(JIRA_CONFIG_FILE, {})

def save_jira_config(cfg: dict):
    _write_json(JIRA_CONFIG_FILE, cfg)

def create_jira_issue(cfg: dict, project_key: str, summary: str, description: str,
                      priority: str = "Medium", labels: list = None, components: list = None):
    auth = base64.b64encode(f"{cfg['email']}:{cfg['token']}".encode()).decode()
    fields = {
        "project":     {"key": project_key},
        "summary":     summary,
        "description": description,
        "issuetype":   {"name": "Bug"},
        "priority":    {"name": priority},
        "labels":      labels if labels is not None else ["QA-Auto", "OrderValidation"],
    }
    _comp = cfg.get("component", "").strip()
    if _comp:
        fields["components"] = [{"name": _comp}]
    resp = requests.post(
        f"{cfg['url'].rstrip('/')}/rest/api/2/issue",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        json={"fields": fields},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["key"], f"{cfg['url'].rstrip('/')}/browse/{data['key']}"

def generate_html_report(order_nums: list, all_dl_sections: dict,
                         env: str, timestamp: str,
                         grand_total: int, grand_passed: int, grand_failed: int) -> str:
    rows_html = ""
    for section, df in all_dl_sections.items():
        rows_html += f'<h3 style="margin-top:2rem;color:#1a3a6e;">{section}</h3>'
        rows_html += '<table><thead><tr>'
        for col in df.columns:
            rows_html += f'<th>{col}</th>'
        rows_html += '</tr></thead><tbody>'
        for _, row in df.iterrows():
            status = str(row.get("Status", ""))
            if "FAIL" in status:
                bg = "#ffe0e0"
            elif "PASS" in status:
                bg = "#e0f5e9"
            elif "N/A" in status or "ℹ️" in status:
                bg = "#e8f4ff"
            else:
                bg = "#ffffff"
            rows_html += f'<tr style="background:{bg};">'
            for val in row:
                rows_html += f'<td>{val}</td>'
            rows_html += '</tr>'
        rows_html += '</tbody></table>'

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Order Validation Report</title>
<style>
body{{font-family:Inter,Arial,sans-serif;margin:2rem;background:#f5f8fc;color:#1a1a2e}}
h1{{color:#0d1b2a}} h2{{color:#1a3a6e}} h3{{color:#1a3a6e;border-bottom:1px solid #cce}}
table{{border-collapse:collapse;width:100%;margin-bottom:1rem;background:#fff;
       box-shadow:0 1px 4px rgba(0,0,0,.08);border-radius:6px;overflow:hidden}}
th{{background:#1a3a6e;color:#fff;padding:.5rem .75rem;text-align:left;font-size:.82rem}}
td{{padding:.4rem .75rem;font-size:.82rem;border-bottom:1px solid #eee}}
.meta{{background:#fff;border-radius:8px;padding:1rem 1.5rem;margin-bottom:1.5rem;
       box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.badge{{display:inline-block;padding:.2rem .6rem;border-radius:12px;font-weight:600;font-size:.8rem}}
.pass{{background:#e0f5e9;color:#1a7a3c}} .fail{{background:#ffe0e0;color:#a00}} .info{{background:#e8f4ff;color:#1a3a6e}}
</style></head><body>
<h1>✅ Order Validation Report</h1>
<div class="meta">
  <b>Date:</b> {timestamp} &nbsp;|&nbsp; <b>Environment:</b> {env} &nbsp;|&nbsp;
  <b>Orders:</b> {', '.join(order_nums)}<br>
  <span class="badge pass">✅ Passed: {grand_passed}</span>&nbsp;
  <span class="badge fail">❌ Failed: {grand_failed}</span>&nbsp;
  <span class="badge info">Total: {grand_total}</span>
</div>
{rows_html}
</body></html>"""

st.set_page_config(page_title="Order Validation", page_icon="✅", layout="wide")

# ── CSS styles ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Global */
html, body, [class*="css"] { font-family: 'Inter', 'Segoe UI', Arial, sans-serif; }
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }

/* ── Full dark background ── */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewBlockContainer"],
[data-testid="stHeader"],
[data-testid="stToolbar"],
header[data-testid="stHeader"],
.main .block-container {
    background: linear-gradient(160deg, #0d1b2a 0%, #112240 60%, #0f3460 100%) !important;
}

/* Top toolbar text/icons */
[data-testid="stHeader"] * { color: #a0c4dd !important; }
[data-testid="stToolbar"] * { color: #a0c4dd !important; }

/* Main content text */
.main, .main p, .main span, .main div,
.main label, .main .stMarkdown,
[data-testid="stMarkdownContainer"] { color: #c8ddf0 !important; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0a1628 0%, #0d1f3c 60%, #0f3460 100%);
    border-right: 1px solid rgba(255,255,255,0.08);
}
section[data-testid="stSidebar"] * { color: #d8e6f3 !important; }
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { color: #ffffff !important; letter-spacing: 0.4px; }
section[data-testid="stSidebar"] [data-baseweb="select"] * { color: #1a1a2e !important; }
section[data-testid="stSidebar"] code {
    color: #e8f4ff !important;
    background: rgba(255,255,255,0.12) !important;
    border-radius: 4px; padding: 1px 6px;
}
section[data-testid="stSidebar"] .stButton > button {
    background: #1e3a5f; color: #ffffff !important;
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 8px; font-weight: 500; transition: background 0.2s;
}
section[data-testid="stSidebar"] .stButton > button:hover { background: #2a5298; }
section[data-testid="stSidebar"] [data-testid="stSuccess"] {
    background: rgba(0,184,148,0.15) !important;
    border: 1px solid rgba(0,184,148,0.4) !important; border-radius: 8px;
}
section[data-testid="stSidebar"] [data-testid="stWarning"] {
    background: rgba(253,203,110,0.15) !important;
    border: 1px solid rgba(253,203,110,0.4) !important; border-radius: 8px;
}

/* ── App header ── */
.app-header {
    background: linear-gradient(135deg, #0a1628 0%, #1a3a6e 60%, #1e5f74 100%);
    padding: 1.4rem 2rem; border-radius: 14px; margin-bottom: 1.5rem;
    box-shadow: 0 4px 24px rgba(0,0,0,0.4);
    border: 1px solid rgba(255,255,255,0.08);
}
.app-header h1 { color: #ffffff; margin: 0; font-size: 1.75rem; font-weight: 700; letter-spacing: 0.5px; }
.app-header p  { color: #7eb8d4; margin: 0.25rem 0 0; font-size: 0.88rem; }

/* ── Section headings ── */
h3 { color: #e8f4ff !important; border-bottom: 1px solid rgba(255,255,255,0.12); padding-bottom: 0.3rem; }
h4 { color: #7eb8d4 !important; font-size: 1rem !important; font-weight: 600 !important; }

/* ── Input fields ── */
[data-testid="stTextInput"] input,
[data-testid="stDateInput"] input {
    background: #ffffff !important;
    border: 1px solid rgba(255,255,255,0.3) !important;
    color: #1a1a2e !important;
    border-radius: 8px;
}
[data-testid="stTextInput"] input::placeholder,
[data-testid="stDateInput"] input::placeholder { color: #8899aa !important; }
[data-testid="stTextInput"] label,
[data-testid="stDateInput"] label,
[data-testid="stSelectbox"] label { color: #a0c4dd !important; font-weight: 500; }
[data-baseweb="select"] { background: #ffffff !important; border-radius: 8px; }
[data-baseweb="select"] * { color: #1a1a2e !important; }

/* ── Run Validation button ── */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1e3a6e, #1e5f74);
    color: #ffffff; border: 1px solid rgba(255,255,255,0.15);
    border-radius: 10px; padding: 0.55rem 2rem;
    font-weight: 600; font-size: 1rem;
    box-shadow: 0 4px 16px rgba(0,0,0,0.3); transition: all 0.2s ease;
}
.stButton > button[kind="primary"]:hover { transform: translateY(-1px); box-shadow: 0 6px 20px rgba(0,0,0,0.45); }
.stButton > button[kind="primary"]:disabled { background: #2a3a50; box-shadow: none; transform: none; }

/* ── Dividers ── */
hr { border-color: rgba(255,255,255,0.1); margin: 1.2rem 0; }

/* ── Alert boxes ── */
[data-testid="stInfo"]    { background: rgba(9,132,227,0.12) !important; border-radius: 8px; border-left: 4px solid #0984e3; }
[data-testid="stSuccess"] { background: rgba(0,184,148,0.12) !important; border-radius: 8px; border-left: 4px solid #00b894; }
[data-testid="stWarning"] { background: rgba(253,203,110,0.12) !important; border-radius: 8px; border-left: 4px solid #fdcb6e; }
[data-testid="stError"]   { background: rgba(214,48,49,0.12) !important; border-radius: 8px; border-left: 4px solid #d63031; }

/* ── Expander ── */
details {
    background: rgba(255,255,255,0.04) !important;
    border-radius: 10px !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    margin-bottom: 0.5rem;
}
/* Force expander content area dark */
details > div,
details > div > div,
[data-testid="stExpander"] > div { background: #0d1b2a !important; }
summary { font-weight: 600; color: #e8f4ff !important; padding: 0.7rem 1rem; font-size: 0.95rem; }
summary:hover { color: #ffffff !important; }

/* ── Code blocks (st.code / JSON viewer) ── */
[data-testid="stCode"],
[data-testid="stCode"] > div { background: #0a1628 !important; border-radius: 8px !important; }
[data-testid="stCode"] pre  { background: #0a1628 !important; color: #c8ddf0 !important;
                               font-family: 'Fira Code','Cascadia Code',Consolas,monospace !important;
                               font-size: 0.84rem !important; line-height: 1.6 !important; }
/* Inline code in markdown */
code { background: rgba(255,255,255,0.12) !important; color: #e8f4ff !important;
       border-radius: 4px !important; padding: 1px 6px !important; font-size: 0.88em !important; }

/* ── Spinner ── */
[data-testid="stSpinner"] { color: #7eb8d4 !important; }

/* ── Tabs ── */
[data-testid="stTabs"] [data-baseweb="tab"] { color: #a0c4dd !important; }
[data-testid="stTabs"] [aria-selected="true"] { color: #ffffff !important; border-bottom-color: #4db8ff !important; }
</style>
""", unsafe_allow_html=True)

# ── App header ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="app-header">
    <h1>✅ Order Validation — Salesforce</h1>
    <p>Validate orders in real-time against business rules via Salesforce CLI</p>
</div>
""", unsafe_allow_html=True)

# ── Org config ────────────────────────────────────────────────────────────────
ORG_CONFIG = {
    "QA":  {"alias": "qa-org",  "login_url": "https://rubrikinc--rbkqa.sandbox.my.salesforce.com",             "label": "QA Sandbox"},
    "UAT": {"alias": "uat-org", "login_url": "https://rubrikinc--rbkuat.sandbox.my.salesforce.com",            "label": "UAT Sandbox"},
}

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Salesforce Connection")
    st.markdown("Authenticate via Salesforce CLI — no password needed.")

    env = st.selectbox("Environment", options=list(ORG_CONFIG.keys()),
                       format_func=lambda k: f"{k} — {ORG_CONFIG[k]['label']}")
    org_alias = ORG_CONFIG[env]["alias"]
    login_url  = ORG_CONFIG[env]["login_url"]
    st.caption(f"Alias: `{org_alias}`")

    col1, col2 = st.columns(2)
    with col1:
        connect_btn = st.button("Connect", use_container_width=True)
    with col2:
        login_btn = st.button("Login (Device Flow)", use_container_width=True)

    if login_btn:
        st.sidebar.info(
            f"Run this in your terminal, then click **Connect**:\n\n"
            f"`sf org login device --alias {org_alias} --instance-url {login_url}`\n\n"
            "A code + URL will appear in the terminal — open the URL and enter the code. "
            "No browser redirect required."
        )

# ── Session state ─────────────────────────────────────────────────────────────
if "sf_connected"  not in st.session_state: st.session_state.sf_connected  = False
if "sf_username"   not in st.session_state: st.session_state.sf_username   = ""
if "sf_alias"      not in st.session_state: st.session_state.sf_alias      = ""
if "known_issues"      not in st.session_state: st.session_state.known_issues      = load_known_issues()
if "run_history"       not in st.session_state: st.session_state.run_history       = load_history()
if "last_run_orders"   not in st.session_state: st.session_state.last_run_orders   = []
if "last_order_health" not in st.session_state: st.session_state.last_order_health = {}

# ── Helpers ───────────────────────────────────────────────────────────────────
def verify_sf_org(alias: str):
    """Verify alias is known to SF CLI; returns (username, instance_url) or ('', '')."""
    for cmd in (["sf", "org", "display", "--target-org", alias, "--json"],
                ["sfdx", "force:org:display", "--targetusername", alias, "--json"]):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            data = json.loads(proc.stdout)
            result = data.get("result", {})
            username = result.get("username", "")
            if username:
                return username, result.get("instanceUrl", "")
        except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
            continue
    return "", ""

def run_sf_query(alias: str, soql: str) -> dict:
    """Execute SOQL via SF CLI — the CLI handles token refresh automatically."""
    soql_clean = " ".join(soql.split())
    last_err   = "SF CLI query failed — is `sf` (or `sfdx`) CLI installed?"
    for cmd in (["sf", "data", "query", "--query", soql_clean, "--target-org", alias, "--json"],
                ["sfdx", "force:data:soql:query", "--query", soql_clean, "--targetusername", alias, "--json"]):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(proc.stdout)
            if data.get("status") == 0:
                r = data.get("result", {})
                return {"totalSize": r.get("totalSize", 0), "records": r.get("records", [])}
            last_err = data.get("message", str(data))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        except json.JSONDecodeError:
            continue
    raise Exception(last_err)

def _prefetch_order_data(order_num: str, alias: str) -> dict:
    """Pre-fetch all SF data for one order in parallel. Returns dict or raises."""
    soql_order = f"""
        SELECT Id, OrderNumber, ProcessType__c,
               Stage_PO__c, ScreenStatus__c, Est_Ship_Date__c,
               Deliver_By__c, Order_Accepted_Timestamp__c,
               customer_required_ship_date__c, Type, Order_Sub_Type__c,
               Line_Types__c, BookingStatus__c, Order_Status__c,
               Have_Polaris_Products__c,
               Opportunity.Has_Polaris_Product__c,
               Opportunity.Rubrik_Security_Cloud_Gov_t_Owner__c,
               Opportunity.Rubrik_Security_Cloud_Gov_t_Owner__r.Email,
               Opportunity.Rubrik_Security_Cloud_Gov_t_Owner__r.Phone,
               Has_Third_Party_Hardware_Product__c,
               Third_Party_Hardware_fulfilment_status__c,
               RSC_G_Enabled__c, Ready_for_Gov_Sync__c,
               RSC_G_Contact__c, RSC_G_Contact_Email__c, RSC_G_Contact_Phone__c,
               Bill_To_Name__r.Id, Bill_To_Name__r.Name,
               TotalAmount,
               SBQQ__Quote__r.Id, SBQQ__Quote__r.Name,
               SBQQ__Quote__r.ProcessType__c, SBQQ__Quote__r.SBQQ__NetAmount__c,
               SBQQ__Quote__r.Manual_Fulfillment_Quote__c,
               ManualFulfilment__c, Actual_Order_Ship_Date__c,
               Welcome_letter_sent_for_the_first_time__c,
               WelcomeEmailSentforSoftwareProducts__c, SD_Status__c
        FROM Order WHERE OrderNumber = '{order_num}' LIMIT 1
    """
    soql_items = f"""
        SELECT Product2.Shipping_Lead_Time__c, Product2.Order_Fulfilment__c, Product2.Name,
               Printable_Product__c, Opportunity_Product__r.Printable_Product__c,
               Payment_Options__c, SBQQ__QuoteLine__r.Product_Payment_Option__c,
               SBQQ__SubscriptionTerm__c, SBQQ__QuoteLine__r.SBQQ__SubscriptionTerm__c,
               SBQQ__QuoteLine__r.SBQQ__StartDate__c, SBQQ__QuoteLine__r.End_Date__c,
               SerialNumber__c, Support_Start_Date__c, Support_End_Date__c,
               Support_Term__c, Segment_Label__c, Quarter__c,
               SBQQ__QuoteLine__r.SBQQ__SegmentLabel__c, Product2.Product_Type__c,
               UnitPrice, Quantity, TotalPrice
        FROM OrderItem WHERE Order.OrderNumber = '{order_num}'
    """
    soql_metrics = f"""
        SELECT Order_Creation_Metrics__c, Order_Booking_Metrics__c,
               Order_Provisioning_Metrics__c, Booking_Creation_Metrics__c,
               SC_creation_Metrics__c, Stage_PO_Submission_Metrics__c,
               CLI_creation_Metrics__c, Entitlement_Creation_Metrics__c, Comment__c
        FROM Order_Success_Metrics__c
        WHERE Order__r.Order_Number__c = '{order_num}' LIMIT 1
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as _pool:
        _fo = _pool.submit(run_sf_query, alias, soql_order)
        _fi = _pool.submit(run_sf_query, alias, soql_items)
        _fm = _pool.submit(run_sf_query, alias, soql_metrics)
        _result  = _fo.result()
        _items   = _fi.result()
        _metrics = _fm.result()
    return {"result": _result, "items_result": _items, "metrics_result": _metrics}

# ── Connect ───────────────────────────────────────────────────────────────────
if connect_btn:
    with st.sidebar:
        with st.spinner(f"Verifying {org_alias}…"):
            username, _ = verify_sf_org(org_alias)
    if not username:
        st.sidebar.error(
            f"Org alias `{org_alias}` not found. Run this in your terminal first:\n\n"
            f"`sf org login device --alias {org_alias} --instance-url {login_url}`\n\n"
            "and that `sf` (or `sfdx`) CLI is installed."
        )
        st.session_state.sf_connected = False
    else:
        st.session_state.sf_connected = True
        st.session_state.sf_username  = username
        st.session_state.sf_alias     = org_alias
        st.session_state.sf_env       = env

# ── Connection status ─────────────────────────────────────────────────────────
if st.session_state.sf_connected:
    st.sidebar.success(f"Connected ✅\n{st.session_state.sf_username}")
else:
    st.sidebar.warning("Status: Not connected")
    with st.sidebar.expander("First time? Setup steps"):
        st.markdown("""
1. Install SF CLI if not already: `brew install sf`
2. Login to your selected org using **device flow** (avoids browser redirect errors):

   **QA:**
   `sf org login device --alias qa-org --instance-url https://rubrikinc--rbkqa.sandbox.my.salesforce.com`

   **UAT:**
   `sf org login device --alias uat-org --instance-url https://rubrikinc--rbkuat.sandbox.my.salesforce.com`

   A one-time code and URL will appear in the terminal. Open the URL in your browser and enter the code — no redirect needed.

3. Select the environment above, then click **Connect**

> ⚠️ If you see `AuthCodeExchangeError / invalid_grant`, use the device flow command above instead of `sf org login web`.
        """)

# ── Compare mode ──────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
compare_mode = st.sidebar.checkbox("🔀 Compare QA vs UAT", value=False, key="compare_mode",
                                   help="Run the same orders on both QA and UAT. Both environments must be authenticated.")

# ── Validation Scope ──────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("Validation Scope")
scope_header = st.sidebar.checkbox("Order Header",  value=True, key="scope_header")
scope_items  = st.sidebar.checkbox("OrderItem",     value=True, key="scope_items")
scope_ent    = st.sidebar.checkbox("Entitlements",  value=True, key="scope_ent")

# ── Skip Specific Checks ──────────────────────────────────────────────────────
_SKIPPABLE_VALIDATIONS = [
    ("1",  "Process Type Sync"),
    ("5",  "CESD"),
    ("6",  "EDD"),
    ("7",  "Booking Status"),
    ("8",  "Polaris Products Sync"),
    ("9",  "Third Party Hardware"),
    ("10", "Manual Fulfillment"),
    ("11", "Quote Net vs Orders Sum"),
    ("12", "RSCG Sync"),
    ("13", "RSCG Contact Fields"),
    ("14", "Welcome Letter (Shipped, null PT)"),
    ("15", "Welcome Letter (Shipped, PT set)"),
]
with st.sidebar.expander("🔬 Skip Specific Checks"):
    for _sv_num, _sv_name in _SKIPPABLE_VALIDATIONS:
        st.checkbox(f"#{_sv_num} — {_sv_name}", key=f"skip_v_{_sv_num}", value=False)

_skipped_check_nums = {num for num, _ in _SKIPPABLE_VALIDATIONS
                       if st.session_state.get(f"skip_v_{num}", False)}

# ── Known Issues ──────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
with st.sidebar.expander(f"⚠️ Known Issues ({len(st.session_state.known_issues)})"):
    if st.session_state.known_issues:
        for _vname, _kinfo in list(st.session_state.known_issues.items()):
            _jkey = _kinfo.get("jira_key", "")
            _note = _kinfo.get("note", "")
            _col_a, _col_b = st.columns([4, 1])
            _col_a.caption(f"**{_vname}**" + (f" — {_jkey}" if _jkey else "") + (f"\n_{_note}_" if _note else ""))
            if _col_b.button("✕", key=f"rm_ki_{_vname}"):
                del st.session_state.known_issues[_vname]
                save_known_issues(st.session_state.known_issues)
                st.rerun()
    else:
        st.caption("No suppressed validations yet. Mark failures as Known Issues from the results view.")
    st.markdown("---")
    st.download_button(
        "📤 Export Known Issues",
        data=json.dumps(st.session_state.known_issues, indent=2),
        file_name="known_issues.json",
        mime="application/json",
        key="ki_export_btn",
        use_container_width=True,
    )
    _ki_import_file = st.file_uploader(
        "📥 Import Known Issues JSON",
        type=["json"],
        key="ki_import_up",
        label_visibility="collapsed",
    )
    if _ki_import_file is not None:
        try:
            _imported_ki = json.loads(_ki_import_file.read())
            st.session_state.known_issues.update(_imported_ki)
            save_known_issues(st.session_state.known_issues)
            st.success(f"Imported {len(_imported_ki)} item(s).")
            st.rerun()
        except Exception as _ki_ie:
            st.error(f"Import failed: {_ki_ie}")

# ── JIRA Settings ─────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
with st.sidebar.expander("🔧 JIRA Settings"):
    _jcfg = load_jira_config()
    with st.form("jira_cfg_form"):
        _jurl   = st.text_input("JIRA URL",        value=_jcfg.get("url",     "https://rubrik.atlassian.net"))
        _jemail = st.text_input("Email",            value=_jcfg.get("email",   ""))
        _jtoken = st.text_input("API Token",        value=_jcfg.get("token",   ""), type="password")
        _jproj  = st.text_input("Default Project",  value=_jcfg.get("project", "SPARK"))
        _jcomp  = st.text_input("Component (optional)", value=_jcfg.get("component", "Order Validation"))
        if st.form_submit_button("Save JIRA Config"):
            save_jira_config({"url": _jurl, "email": _jemail, "token": _jtoken, "project": _jproj, "component": _jcomp})
            st.success("JIRA config saved.")

# ── Run History ───────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
with st.sidebar.expander(f"📜 Run History ({len(st.session_state.run_history)})"):
    if st.session_state.run_history:
        for _run in reversed(st.session_state.run_history[-10:]):
            st.caption(
                f"🕐 {_run['timestamp'][:16]}  |  {_run.get('env','?')}\n"
                f"Orders: {', '.join(_run.get('orders', []))}\n"
                f"✅ {_run.get('passed',0)} passed  ❌ {_run.get('failed',0)} failed  / {_run.get('total',0)} total"
            )
            st.markdown("---")
        if len(st.session_state.run_history) >= 2:
            st.markdown("**Pass Rate Trend (last 10 runs)**")
            _chart_data = pd.DataFrame([
                {
                    "Run": r["timestamp"][5:16],
                    "Pass %": round(r.get("passed", 0) / r.get("total", 1) * 100, 1)
                              if r.get("total", 0) > 0 else 0.0,
                }
                for r in st.session_state.run_history[-10:]
            ]).set_index("Run")
            st.line_chart(_chart_data, height=140)
    else:
        st.caption("No runs yet. Run a validation to see history here.")

# ── Helpers: date arithmetic ──────────────────────────────────────────────────
def add_days(date_str, days):
    if not date_str:
        return ""
    try:
        return (datetime.strptime(date_str[:10], "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
    except ValueError:
        return ""

def parse_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        return None

def add_months(date_str, months):
    if not date_str or months is None:
        return ""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        m  = dt.month - 1 + int(months)
        y  = dt.year + m // 12
        m  = m % 12 + 1
        d  = min(dt.day, calendar.monthrange(y, m)[1])
        return datetime(y, m, d).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""

# ── Helper: color-coded HTML table ───────────────────────────────────────────
def render_table(df: pd.DataFrame):
    status_cols = [c for c in df.columns if "Status" in c]

    def row_style(row):
        combined = " ".join(str(row[c]) for c in status_cols if c in row.index)
        if "❌" in combined:
            return "rgba(214,48,49,0.18)", "#ffaaaa"
        elif "✅" in combined:
            return "rgba(0,184,148,0.15)", "#7eecd0"
        else:
            return "rgba(9,132,227,0.12)", "#90c8f0"

    headers = "".join(
        f'<th style="padding:8px 12px; background:#0a1628; color:#a8d4f0; font-size:0.75rem;'
        f' text-transform:uppercase; letter-spacing:0.5px; white-space:nowrap;">{col}</th>'
        for col in df.columns
    )
    body_rows = []
    for _, row in df.iterrows():
        bg, fg = row_style(row)
        cells = "".join(
            f'<td style="padding:7px 12px; border-bottom:1px solid rgba(255,255,255,0.07); color:{fg}; font-size:0.84rem;">{row[col]}</td>'
            for col in df.columns
        )
        body_rows.append(f'<tr style="background:{bg};">{cells}</tr>')

    st.markdown(
        '<div style="overflow-x:auto; border-radius:8px; box-shadow:0 4px 16px rgba(0,0,0,0.3); margin-bottom:1rem; background:#0d1b2a;">'
        '<table style="width:100%; border-collapse:collapse; font-family:Inter,sans-serif;">'
        f'<thead><tr>{headers}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody>'
        '</table></div>',
        unsafe_allow_html=True,
    )

# ── Helper: OI rows with collapsible groups ───────────────────────────────────
def render_oi_rows(rows):
    _collapsible = ("Product Name Match", "Payment Options Match", "Subscription Term Match", "Support Start Date", "Support End Date", "UnitPrice × Quantity", "SerialNumber vs Quantity", "Segment Label", "Quarter")
    pn_rows    = [r for r in rows if r["Validation"].startswith("Product Name Match")]
    po_rows    = [r for r in rows if r["Validation"].startswith("Payment Options Match")]
    st_rows    = [r for r in rows if r["Validation"].startswith("Subscription Term Match")]
    ss_rows    = [r for r in rows if r["Validation"].startswith("Support Start Date")]
    se_rows    = [r for r in rows if r["Validation"].startswith("Support End Date")]
    tp_rows    = [r for r in rows if r["Validation"].startswith("UnitPrice × Quantity")]
    sn_rows    = [r for r in rows if r["Validation"].startswith("SerialNumber vs Quantity")]
    sl_rows    = [r for r in rows if r["Validation"].startswith("Segment Label")]
    qtr_rows   = [r for r in rows if r["Validation"].startswith("Quarter")]
    other_rows = [r for r in rows if not r["Validation"].startswith(_collapsible)]

    if other_rows:
        render_table(pd.DataFrame(other_rows))

    if pn_rows:
        pn_pass = sum(1 for r in pn_rows if "✅" in r["Status"])
        pn_fail = sum(1 for r in pn_rows if "❌" in r["Status"])
        badge = (f" · ✅ {pn_pass} passed" if pn_pass else "") + (f" · ❌ {pn_fail} failed" if pn_fail else "")
        with st.expander(f"Product Name Match — {len(pn_rows)} line item(s){badge}", expanded=False):
            render_table(pd.DataFrame(pn_rows))

    if po_rows:
        po_pass = sum(1 for r in po_rows if "✅" in r["Status"])
        po_fail = sum(1 for r in po_rows if "❌" in r["Status"])
        badge = (f" · ✅ {po_pass} passed" if po_pass else "") + (f" · ❌ {po_fail} failed" if po_fail else "")
        with st.expander(f"Payment Options Match — {len(po_rows)} line item(s){badge}", expanded=False):
            render_table(pd.DataFrame(po_rows))

    if st_rows:
        st_pass = sum(1 for r in st_rows if "✅" in r["Status"])
        st_fail = sum(1 for r in st_rows if "❌" in r["Status"])
        badge = (f" · ✅ {st_pass} passed" if st_pass else "") + (f" · ❌ {st_fail} failed" if st_fail else "")
        with st.expander(f"Subscription Term Match — {len(st_rows)} line item(s){badge}", expanded=False):
            render_table(pd.DataFrame(st_rows))

    if sl_rows:
        sl_pass = sum(1 for r in sl_rows if "✅" in r["Status"])
        sl_fail = sum(1 for r in sl_rows if "❌" in r["Status"])
        badge = (f" · ✅ {sl_pass} passed" if sl_pass else "") + (f" · ❌ {sl_fail} failed" if sl_fail else "")
        with st.expander(f"Segment Label — {len(sl_rows)} line item(s){badge}", expanded=False):
            render_table(pd.DataFrame(sl_rows))

    if qtr_rows:
        qtr_pass = sum(1 for r in qtr_rows if "✅" in r["Status"])
        qtr_fail = sum(1 for r in qtr_rows if "❌" in r["Status"])
        badge = (f" · ✅ {qtr_pass} passed" if qtr_pass else "") + (f" · ❌ {qtr_fail} failed" if qtr_fail else "")
        with st.expander(f"Quarter — {len(qtr_rows)} line item(s){badge}", expanded=False):
            render_table(pd.DataFrame(qtr_rows))

    if ss_rows:
        ss_pass = sum(1 for r in ss_rows if "✅" in r["Status"])
        ss_fail = sum(1 for r in ss_rows if "❌" in r["Status"])
        badge = (f" · ✅ {ss_pass} passed" if ss_pass else "") + (f" · ❌ {ss_fail} failed" if ss_fail else "")
        with st.expander(f"Support Start Date — {len(ss_rows)} line item(s){badge}", expanded=False):
            render_table(pd.DataFrame(ss_rows))

    if se_rows:
        se_pass = sum(1 for r in se_rows if "✅" in r["Status"])
        se_fail = sum(1 for r in se_rows if "❌" in r["Status"])
        badge = (f" · ✅ {se_pass} passed" if se_pass else "") + (f" · ❌ {se_fail} failed" if se_fail else "")
        with st.expander(f"Support End Date — {len(se_rows)} line item(s){badge}", expanded=False):
            render_table(pd.DataFrame(se_rows))

    if tp_rows:
        tp_pass = sum(1 for r in tp_rows if "✅" in r["Status"])
        tp_fail = sum(1 for r in tp_rows if "❌" in r["Status"])
        badge = (f" · ✅ {tp_pass} passed" if tp_pass else "") + (f" · ❌ {tp_fail} failed" if tp_fail else "")
        with st.expander(f"UnitPrice × Quantity = TotalPrice — {len(tp_rows)} line item(s){badge}", expanded=False):
            render_table(pd.DataFrame(tp_rows))

    if sn_rows:
        sn_pass = sum(1 for r in sn_rows if "✅" in r["Status"])
        sn_fail = sum(1 for r in sn_rows if "❌" in r["Status"])
        badge = (f" · ✅ {sn_pass} passed" if sn_pass else "") + (f" · ❌ {sn_fail} failed" if sn_fail else "")
        with st.expander(f"SerialNumber vs Quantity — {len(sn_rows)} line item(s){badge}", expanded=False):
            render_table(pd.DataFrame(sn_rows))

# ── Helper: Entitlement rows grouped by validation type ──────────────────────
def render_ent_rows(rows):
    _groups = [
        ("SubType",           "SubType"),
        ("Product",           "Product"),
        ("Base Product",      "Base Product"),
        ("Subscription Term", "Subscription Term"),
        ("Quantity",          "Quantity"),
        ("MFG Ent SubType",       "MFG Ent SubType"),
        ("MFG Ent BaseProductName", "MFG Ent BaseProductName"),
    ]
    for prefix, label in _groups:
        grp = [r for r in rows if r["Validation"].startswith(prefix)]
        if not grp:
            continue
        grp_pass = sum(1 for r in grp if "✅" in r["Status"])
        grp_fail = sum(1 for r in grp if "❌" in r["Status"])
        badge = (f" · ✅ {grp_pass} passed" if grp_pass else "") + (f" · ❌ {grp_fail} failed" if grp_fail else "")
        with st.expander(f"{label} — {len(grp)} entitlement(s){badge}", expanded=False):
            render_table(pd.DataFrame(grp))

def _copy_buttons_html(fail_rows: list):
    """Render all copy buttons for fail rows in one HTML block."""
    btns = ""
    for _row in fail_rows:
        txt = (
            f"{_row.get('Validation','')} | Expected: {_row.get('Expected','')} | Actual: {_row.get('Actual','')}"
        ).replace("'", "\\'").replace('"', '&quot;')
        btns += (
            f'<button onclick="navigator.clipboard.writeText(\'{txt}\')" '
            f'style="background:rgba(30,58,95,0.8);border:1px solid rgba(100,150,200,0.4);'
            f'color:#c8ddf0;padding:3px 12px;border-radius:5px;cursor:pointer;'
            f'font-size:0.76rem;margin:2px 4px;display:inline-block;" '
            f'title="Copy this failure">📋 {_row.get("Validation","")[:50]}</button>'
        )
    if btns:
        import streamlit.components.v1 as stc
        stc.html(f'<div style="margin-bottom:8px;">{btns}</div>', height=max(40, 34 * ((len(fail_rows) + 3) // 4)))

# ── Main input area ───────────────────────────────────────────────────────────
def _parse_order_text(raw: str) -> list:
    """Extract order numbers from free-form text.

    Handles all paste formats from Salesforce export:
    - Copy (CSV):   "_","Order_Number__c" / "Order","140703"   (quoted, comma-sep)
    - Copy (Excel): _\tOrder_Number__c / Order\t140703         (tab-sep)
    - Plain list:   140703\n140709  or  140703, 140709
    """
    import re
    # Split on whitespace, commas, semicolons, tabs — any mix
    tokens = re.split(r"[\t ,;\r\n]+", raw.strip())
    result = []
    for tok in tokens:
        # Strip surrounding quotes and whitespace (handles CSV quoting)
        clean = tok.strip().strip('"').strip("'").strip()
        if clean.isdigit() and len(clean) >= 4:   # order numbers are ≥4 digits
            result.append(clean)
    return list(dict.fromkeys(result))  # deduplicate, preserve order

def _parse_csv_upload(file) -> list:
    """Extract order numbers from an uploaded CSV/TXT file."""
    df = pd.read_csv(file, dtype=str)
    # Named column containing 'order' + 'number'?
    candidates = [c for c in df.columns if "order" in c.lower() and "number" in c.lower()]
    if candidates:
        nums = df[candidates[0]].dropna().str.strip().tolist()
    elif df.shape[1] == 1:
        nums = df.iloc[:, 0].dropna().str.strip().tolist()
    else:
        # Find the column where most values are pure digits (order numbers)
        best = None
        for col in df.columns:
            if df[col].dropna().str.strip().str.match(r"^\d{5,}$").mean() > 0.8:
                best = col
                break
        nums = df[best].dropna().str.strip().tolist() if best else df.iloc[:, 0].dropna().str.strip().tolist()
    return [n for n in nums if n.isdigit()]

col_on, col_td = st.columns([3, 1])
with col_on:
    st.markdown("**Order Number(s)**")
    _input_tab_typed, _input_tab_file = st.tabs(["✏️ Type / Paste", "📂 Upload CSV"])

    with _input_tab_typed:
        order_number = st.text_area(
            "order_number_input",
            placeholder=(
                "Paste or type order numbers — one per line, or comma-separated:\n"
                "140703\n140709\n140706\n\nor: 140703, 140709, 140706"
            ),
            height=130,
            label_visibility="collapsed",
        )

    with _input_tab_file:
        uploaded_file = st.file_uploader(
            "Upload CSV or TXT",
            type=["csv", "txt"],
            label_visibility="collapsed",
        )
        if uploaded_file:
            try:
                _file_nums = _parse_csv_upload(uploaded_file)
                st.success(f"**{len(_file_nums)} order(s)** detected in file.")
                if _file_nums:
                    st.caption(", ".join(_file_nums[:10]) + (f" … (+{len(_file_nums)-10} more)" if len(_file_nums) > 10 else ""))
            except Exception as _fe:
                _file_nums = []
                st.warning(f"Could not parse file: {_fe}")
        else:
            _file_nums = []

with col_td:
    target_date = st.date_input("Target Date (optional — for Lead Time)", value=None)

# Merge typed + file order numbers (deduped, order preserved)
_typed_nums = _parse_order_text(order_number) if order_number.strip() else []
_merged = list(dict.fromkeys(_typed_nums + _file_nums))
if _merged:
    _src_parts = []
    if _typed_nums: _src_parts.append(f"{len(_typed_nums)} typed")
    if _file_nums:  _src_parts.append(f"{len(_file_nums)} from file")
    st.caption(f"**{len(_merged)} unique order(s)** ready to validate — {' + '.join(_src_parts)}")

# Feature #3 — Failed-Orders-Only Filter
_show_failed_only = False
if st.session_state.last_order_health and _merged:
    _prev_failed = [n for n in _merged if st.session_state.last_order_health.get(n, {}).get("fail", 0) > 0]
    if _prev_failed:
        _show_failed_only = st.checkbox(
            f"🔴 Show failed orders only ({len(_prev_failed)} of {len(_merged)} failed in last run)",
            value=False, key="show_failed_only"
        )

validate_btn = st.button("Run Validation", type="primary", disabled=not st.session_state.sf_connected)

if not st.session_state.sf_connected:
    st.info("Connect to Salesforce using the sidebar before running validations.")

# ── Run validations ───────────────────────────────────────────────────────────
if validate_btn and _merged:

    # Use merged list (manual + file upload)
    order_nums = _merged

    # Feature #3 — Apply failed-orders filter
    if _show_failed_only and st.session_state.last_order_health:
        order_nums = [n for n in order_nums if st.session_state.last_order_health.get(n, {}).get("fail", 0) > 0]
        if not order_nums:
            st.info("No failed orders from last run to display.")
            st.stop()

    # Feature #2 — Batch Health Dashboard (show previous run data)
    if st.session_state.get("last_order_health"):
        st.markdown("### 📊 Batch Health Dashboard")
        _bh_rows = []
        for _on, _oh in st.session_state.last_order_health.items():
            _status = "✅ Clean" if _oh["fail"] == 0 else f"❌ {_oh['fail']} failed"
            _bh_rows.append({"Order": _on, "Passed": _oh["pass"], "Failed": _oh["fail"], "Total": _oh["total"], "Status": _status})
        st.dataframe(pd.DataFrame(_bh_rows), use_container_width=True, hide_index=True)

    # Initialize health dict for this run
    st.session_state.last_order_health = {}

    # Feature #10 — Set current run ID before loop
    _current_run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Compare mode: verify UAT org is also authenticated ─────────────────
    if compare_mode:
        with st.spinner("Verifying UAT org (uat-org)..."):
            _uat_user, _ = verify_sf_org("uat-org")
        if not _uat_user:
            st.error(
                "UAT org not connected. Run in terminal: "
                "sf org login device --alias uat-org "
                "--instance-url https://rubrikinc--rbkuat.sandbox.my.salesforce.com"
            )
            st.stop()


    # ── Feature #4: Pre-fetch all orders in parallel ────────────────────────
    _pf_aliases = []
    if compare_mode:
        for _on in order_nums:
            _pf_aliases.append((_on, "qa-org"))
            _pf_aliases.append((_on, "uat-org"))
    else:
        for _on in order_nums:
            _pf_aliases.append((_on, st.session_state.sf_alias))

    _all_prefetched = {}
    with st.spinner(f"Fetching SF data for {len(order_nums)} order(s)…"):
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(_pf_aliases), 8)) as _pf_pool:
            _pf_futures = {_pf_pool.submit(_prefetch_order_data, _on, _al): (_on, _al) for _on, _al in _pf_aliases}
            for _pf_fut in concurrent.futures.as_completed(_pf_futures):
                _pf_on, _pf_al = _pf_futures[_pf_fut]
                try:
                    _all_prefetched[(_pf_on, _pf_al)] = _pf_fut.result()
                except Exception as _pfe:
                    _all_prefetched[(_pf_on, _pf_al)] = {"error": str(_pfe)}

    # One tab per order; single order uses a plain container (no tab UI)
    if len(order_nums) > 1:
        def _tab_label(n):
            h = st.session_state.last_order_health.get(n)
            if h is None: return f"📋 {n}"
            return f"{'❌' if h['fail'] > 0 else '✅'} {n}"
        tab_labels = [_tab_label(n) for n in order_nums]
        tab_contexts = st.tabs(tab_labels)
    else:
        tab_contexts = [st.container()]

    all_dl_sections      = {}  # accumulate download data across all orders
    cross_order_failures = []
    _grand_total = _grand_passed = _grand_failed = 0

    for tab_ctx, order_num in zip(tab_contexts, order_nums):
        with tab_ctx:

            # ── Compare mode: run for each env in its own tab ──────────────
            if compare_mode:
                _env_tab_qa, _env_tab_uat = st.tabs(["🔵 QA", "🟠 UAT"])
                _env_runs = [("QA", "qa-org", _env_tab_qa), ("UAT", "uat-org", _env_tab_uat)]
            else:
                _env_runs = [(st.session_state.sf_env, st.session_state.sf_alias, st.container())]

            for _env_label, alias, _env_container in _env_runs:
                with _env_container:

                    # Feature #7 — Per-order health score banner (from previous run)
                    _prev_health = st.session_state.last_order_health.get(order_num)
                    if _prev_health and _prev_health.get("total", 0) > 0:
                        _hs_pct = round(_prev_health["pass"] / _prev_health["total"] * 100)
                        _hs_color = "#00b894" if _prev_health["fail"] == 0 else ("#fdcb6e" if _hs_pct >= 70 else "#d63031")
                        _hs_icon = "✅" if _prev_health["fail"] == 0 else ("⚠️" if _hs_pct >= 70 else "❌")
                        st.markdown(
                            f'<div style="background:{_hs_color}22;border-left:4px solid {_hs_color};'
                            f'border-radius:8px;padding:0.6rem 1rem;margin-bottom:0.8rem;">'
                            f'<span style="color:{_hs_color};font-weight:700;">{_hs_icon} Health Score: {_hs_pct}% '
                            f'({_prev_health["pass"]}/{_prev_health["total"]} passed)</span></div>',
                            unsafe_allow_html=True,
                        )

                    # ── Phase 1: Use pre-fetched SF data ────────────────────────────────
                    _pf_key  = (order_num, alias)
                    _pf_data = _all_prefetched.get(_pf_key, {})
                    if "error" in _pf_data:
                        _err = _pf_data["error"]
                        _login_url = ORG_CONFIG[st.session_state.get("sf_env", "QA")]["login_url"]
                        _auth_keywords = ("INVALID_SESSION_ID", "INVALID_AUTH_HEADER",
                                          "Expired session", "expired access", "expired refresh",
                                          "authentication failure", "SESSION_EXPIRED")
                        if any(kw in _err for kw in _auth_keywords):
                            st.error(
                                f"⚠️ **Salesforce session expired.** Re-authenticate by running:\n\n"
                                f"```\nsf org login device --alias {alias} --instance-url {_login_url}\n```\n\n"
                                f"Then click **Connect** in the sidebar and try again."
                            )
                            st.session_state.sf_connected = False
                        else:
                            st.error(f"SOQL query failed: {_err}")
                        all_dl_sections[f"{order_num} — Error"] = pd.DataFrame([{
                            "Order": order_num, "Status": f"Query failed: {_err[:120]}",
                        }])
                        continue
                    result          = _pf_data.get("result",       {"totalSize": 0, "records": []})
                    items_result    = _pf_data.get("items_result",  {"totalSize": 0, "records": []})
                    _metrics_result = _pf_data.get("metrics_result", {"totalSize": 0, "records": []})
                    metrics_record  = _metrics_result["records"][0] if _metrics_result.get("totalSize", 0) > 0 else {}

                    # ── Derive printable counts from items_result (replaces Q3) ──────────
                    # COUNT(field) in SOQL counts non-null values — replicated here in Python
                    # using the records already fetched by Q2, saving one API round-trip.
                    _items_recs           = items_result.get("records", [])
                    _count_printable      = sum(1 for r in _items_recs if r.get("Printable_Product__c"))
                    _count_opp_printable  = sum(1 for r in _items_recs
                                                if (r.get("Opportunity_Product__r") or {}).get("Printable_Product__c"))
                    printable_record = {
                        "countOppProduct":       _count_opp_printable,
                        "countPrintableProduct": _count_printable,
                    }

                    # ── Phase 2: Q6 (linked orders) — depends on Q1 quote ID ─────────────
                    _quote_id_for_agg  = (
                        (result["records"][0].get("SBQQ__Quote__r") or {}).get("Id")
                        if result.get("totalSize", 0) > 0 else None
                    )
                    agg_result         = {"totalSize": 0, "records": []}
                    linked_orders_list = []
                    if _quote_id_for_agg:
                        with st.spinner("Fetching Quote-linked Orders…"):
                            try:
                                soql_linked = f"""
                                    SELECT OrderNumber, TotalAmount
                                    FROM Order
                                    WHERE SBQQ__Quote__c = '{_quote_id_for_agg}'
                                    ORDER BY OrderNumber ASC
                                """
                                linked_result      = run_sf_query(alias, soql_linked)
                                linked_orders_list = linked_result.get("records", [])
                            except Exception as e:
                                st.warning(f"Linked orders query failed (skipped): {e}")

                            # Derive aggregate from linked records (replaces Q5) — saves one
                            # API round-trip since SUM/COUNT can be computed from fetched rows.
                            if linked_orders_list:
                                _agg_sum   = sum(r.get("TotalAmount") or 0 for r in linked_orders_list)
                                _agg_count = len(linked_orders_list)
                                agg_result = {
                                    "totalSize": 1,
                                    "records":   [{"SumOfOrderTotalAmount": _agg_sum, "OrderCount": _agg_count}],
                                }

                    if result["totalSize"] == 0:
                        st.warning(f"No Order found with OrderNumber = '{order_num}'")
                        all_dl_sections[f"{order_num} — Not Found"] = pd.DataFrame([{
                            "Order": order_num, "Status": f"No Order found with OrderNumber = '{order_num}'",
                        }])
                        continue

                    record = result["records"][0]

                    # ── Field extraction ───────────────────────────────────────────────
                    order_process_type = record.get("ProcessType__c") or ""
                    quote_record       = record.get("SBQQ__Quote__r") or {}
                    quote_name         = quote_record.get("Name", "—")
                    quote_process_type = quote_record.get("ProcessType__c") or ""
                    order_total_amount = record.get("TotalAmount")
                    quote_net_amount          = quote_record.get("SBQQ__NetAmount__c")
                    manual_fulfillment_quote  = quote_record.get("Manual_Fulfillment_Quote__c")
                    stage_po           = record.get("Stage_PO__c")
                    screen_status      = record.get("ScreenStatus__c") or ""
                    bill_to            = record.get("Bill_To_Name__r") or {}
                    bill_to_id         = bill_to.get("Id", "")
                    bill_to_name       = bill_to.get("Name", "(unknown)")
                    sf_order_type      = record.get("Type") or ""
                    order_sub_type     = record.get("Order_Sub_Type__c") or ""
                    line_types         = record.get("Line_Types__c") or ""
                    booking_status     = record.get("BookingStatus__c") or ""
                    order_status       = record.get("Order_Status__c") or ""
                    order_polaris      = record.get("Have_Polaris_Products__c")
                    opp_record         = record.get("Opportunity") or {}
                    opp_polaris        = opp_record.get("Has_Polaris_Product__c")
                    rscg_contact       = record.get("RSC_G_Contact__c") or ""
                    rscg_contact_email = record.get("RSC_G_Contact_Email__c") or ""
                    rscg_contact_phone = record.get("RSC_G_Contact_Phone__c") or ""
                    opp_gov_owner_id   = opp_record.get("Rubrik_Security_Cloud_Gov_t_Owner__c") or ""
                    opp_gov_owner      = opp_record.get("Rubrik_Security_Cloud_Gov_t_Owner__r") or {}
                    opp_gov_email      = opp_gov_owner.get("Email") or ""
                    opp_gov_phone      = opp_gov_owner.get("Phone") or ""
                    has_tph            = record.get("Has_Third_Party_Hardware_Product__c")
                    tph_status         = record.get("Third_Party_Hardware_fulfilment_status__c") or ""
                    rscg_enabled       = record.get("RSC_G_Enabled__c")
                    ready_for_gov_sync = record.get("Ready_for_Gov_Sync__c") or ""
                    order_accepted_raw = record.get("Order_Accepted_Timestamp__c") or ""
                    order_accepted     = order_accepted_raw[:10] if order_accepted_raw else ""
                    crsd_raw           = record.get("customer_required_ship_date__c") or ""
                    crsd               = crsd_raw[:10] if crsd_raw and crsd_raw != "0" else ""
                    est_ship_date      = (record.get("Est_Ship_Date__c") or "")[:10]
                    deliver_by         = (record.get("Deliver_By__c") or "")[:10]
                    actual_ship_date   = (record.get("Actual_Order_Ship_Date__c") or "")[:10]
                    welcome_first      = record.get("Welcome_letter_sent_for_the_first_time__c")
                    welcome_sw         = record.get("WelcomeEmailSentforSoftwareProducts__c")
                    sd_status          = record.get("SD_Status__c") or ""

                    lead_times = []
                    for item in items_result.get("records", []):
                        lt = item.get("Product2", {})
                        if lt:
                            val = lt.get("Shipping_Lead_Time__c")
                            if val is not None:
                                try:
                                    lead_times.append(int(val))
                                except (ValueError, TypeError):
                                    pass
                    max_lt = max(lead_times) if lead_times else 0
                    has_manual_product = any(
                        (item.get("Product2") or {}).get("Order_Fulfilment__c") == "Manual"
                        for item in items_result.get("records", [])
                    )

                    # ── Raw data ───────────────────────────────────────────────────────
                    with st.expander("Raw Salesforce Data", expanded=False):
                        st.markdown("**Order Fields**")
                        st.code(json.dumps({
                            "OrderNumber":               order_num,
                            "Order.ProcessType__c":      order_process_type,
                            "Order.Stage_PO__c":         stage_po,
                            "Order.ScreenStatus__c":     screen_status,
                            "Order.Type":                sf_order_type,
                            "Order.Order_Sub_Type__c":   order_sub_type,
                            "Order.Line_Types__c":       line_types,
                            "Order.Order_Status__c":     order_status,
                            "Order.BookingStatus__c":    booking_status,
                            "Order.Have_Polaris_Products__c":                  order_polaris,
                            "Opp.Has_Polaris_Product__c":                      opp_polaris,
                            "Order.Has_Third_Party_Hardware_Product__c":       has_tph,
                            "Order.Third_Party_Hardware_fulfilment_status__c": tph_status,
                            "Order.RSC_G_Enabled__c":                          rscg_enabled,
                            "Order.Ready_for_Gov_Sync__c":                     ready_for_gov_sync,
                            "Order.RSC_G_Contact__c":                          rscg_contact,
                            "Order.RSC_G_Contact_Email__c":                    rscg_contact_email,
                            "Order.RSC_G_Contact_Phone__c":                    rscg_contact_phone,
                            "Opp.Rubrik_Security_Cloud_Gov_t_Owner__c":        opp_gov_owner_id,
                            "Opp.Gov_Owner.Email":                             opp_gov_email,
                            "Opp.Gov_Owner.Phone":                             opp_gov_phone,
                            "Order.Order_Accepted_Timestamp__c":               order_accepted,
                            "Order.customer_required_ship_date__c":            crsd,
                            "Order.Est_Ship_Date__c":                          est_ship_date,
                            "Order.Deliver_By__c":                             deliver_by,
                            "Max Shipping_Lead_Time__c (weeks)":               max_lt,
                            "Bill_To.Id":                                      bill_to_id,
                            "Bill_To.Name":                                    bill_to_name,
                            "Order.TotalAmount":                               order_total_amount,
                            "Quote.Name":                                      quote_name,
                            "Quote.ProcessType__c":                            quote_process_type,
                            "Quote.SBQQ__NetAmount__c":                        quote_net_amount,
                            "Quote.Manual_Fulfillment_Quote__c":               manual_fulfillment_quote,
                            "Order.Welcome_letter_sent_for_the_first_time__c": welcome_first,
                            "Order.WelcomeEmailSentforSoftwareProducts__c":    welcome_sw,
                            "Order.SD_Status__c":                              sd_status or "(blank)",
                        }, indent=2), language="json")

                        st.info("ℹ️ Entitlement records are shown in the "
                                "**🔍 Raw Entitlement Data** expander inside the Entitlement Validations section below.")

                    # ── Validation Formulas & SOQL Queries reference ──────────────────
                    with st.expander("Validation Formulas & SOQL Queries", expanded=False):
                        _tab_hdr, _tab_oi, _tab_gc, _tab_ent, _tab_soql = st.tabs([
                            "Order Header Formulas",
                            "OrderItem Formulas",
                            "GC Offer Formulas",
                            "Entitlement Formulas",
                            "SOQL Queries",
                        ])

                        with _tab_hdr:
                            st.markdown("##### Order Header Validation Formulas")
                            st.markdown("""
        | # | Validation | Formula / Rule |
        |---|---|---|
        | 1 | Process Type Sync | `Quote.ProcessType__c == Order.ProcessType__c` |
        | 2 | Order Type | If `Stage_PO__c = true` AND Bill_To ∈ EDI list → **EDI**; else if Bill_To = Carahsoft → **Glynt PO**; else → **NON-EDI** |
        | 3 | GTC Screen Status | Mapped from `Order.ScreenStatus__c` values |
        | 4 | Lead Time | `max(Product2.Shipping_Lead_Time__c)` across all OrderItems (weeks) |
        | 5 | CESD | `max(Order_Accepted + max_lead_time weeks, CRSD, Target_Date)` |
        | 6 | EDD | `Est_Ship_Date__c (CESD) + 7 days` |
        | 7 | Booking Status | If `Order_Status__c ∈ {Order Accepted, Shipped}` → BookingStatus__c must be set |
        | 8 | Polaris Products Sync | `Opportunity.Has_Polaris_Product__c == Order.Have_Polaris_Products__c` |
        | 9 | Third Party Hardware Fulfilment | If `Has_Third_Party_Hardware_Product__c = true` → fulfilment status must be populated |
        | 10 | Manual Fulfillment | If `Quote.Manual_Fulfillment_Quote__c` set → use that; else derive from `Product2.Order_Fulfilment__c` |
        | 11 | Quote Net vs Orders Sum | `Quote.SBQQ__NetAmount__c == SUM(linked Orders.TotalAmount)` |
        | 12 | RSCG Sync | If `RSC_G_Enabled__c = true` → `Ready_for_Gov_Sync__c ∈ {Ready for Sync, Sync completed}` |
        | 13 | RSCG Contact Fields | `Order.RSC_G_Contact__c/Email/Phone == Opportunity Gov Owner fields` |
        | 14 | Welcome Letter (null ProcessType, Shipped) | `Welcome_letter_sent_for_the_first_time__c == True` |
        | 15 | Welcome Letter (ProcessType set, Shipped) | First-time and software welcome letter flags must be True |
        """)

                        with _tab_oi:
                            st.markdown("##### OrderItem (Line Item) Validation Formulas")
                            st.markdown("""
        | # | Validation | Formula / Rule |
        |---|---|---|
        | 1 | Product Name Match | `OrderItem.Printable_Product__c == Opportunity_Product__r.Printable_Product__c` |
        | 2 | Payment Options Match | `OrderItem.Payment_Options__c == QuoteLine.Product_Payment_Option__c` (case-insensitive) |
        | 3 | Subscription Term Match | `OrderItem.SBQQ__SubscriptionTerm__c == QuoteLine.SBQQ__SubscriptionTerm__c` *(skipped for GC Offer / GC OnDemand / GC Renewal)* |
        | 4 | Support Start Date (Renewal) | `OrderItem.Support_Start_Date__c == QuoteLine.SBQQ__StartDate__c` |
        | 5 | Support End Date (Renewal) | `OrderItem.Support_End_Date__c == QuoteLine.End_Date__c` |
        | 6 | Support Start Date (Non-Renewal) | `OrderItem.Support_Start_Date__c == Order.Actual_Order_Ship_Date__c` |
        | 7 | Support End Date (Non-Renewal) | If `Support_Term__c` is set → `Support_Start + Support_Term__c months − 1 day`; else → `Support_Start + SBQQ__SubscriptionTerm__c months − 1 day` |
        | 8 | UnitPrice × Quantity | `OrderItem.UnitPrice × Quantity == OrderItem.TotalPrice` |
        | 9 | Order Total Amount | `SUM(OrderItem.TotalPrice) == Order.TotalAmount` |
        | 10 | Serial Number vs Quantity | Hardware products: count of SerialNumber__c entries must equal Quantity |
        | 11 | Printable Product Count | `COUNT(OrderItem.Printable_Product__c) == COUNT(Opp_Product.Printable_Product__c)` |
        """)

                        with _tab_gc:
                            st.markdown("##### GC Offer — Support Start/End Date Formulas")
                            st.markdown("Applies when `Order.Order_Sub_Type__c = 'GC Offer'`. Items are processed in segment order.")
                            st.markdown("""
        | Segment_Label__c | Support Start Date | Support End Date |
        |---|---|---|
        | `Month 1` | `= Actual_Order_Ship_Date__c` | `= Support_Start + SBQQ__SubscriptionTerm__c months − 1 day` |
        | `Month N` (N > 1) | `= Support_End of Month (N−1) + 1 day` | `= Support_Start (Month N) + SBQQ__SubscriptionTerm__c months − 1 day` |
        | `null / blank` | `= Actual_Order_Ship_Date__c` (independent, not chained) | `= Support_Start + SBQQ__SubscriptionTerm__c months − 1 day` |
        """)
                            st.markdown("**Chain rule example** (term = 1 month, ship date = 2024-01-15):")
                            st.code("""\
        Month 1 → Start: 2024-01-15  |  End: 2024-02-14
        Month 2 → Start: 2024-02-15  |  End: 2024-03-14
        Month 3 → Start: 2024-03-15  |  End: 2024-04-14
          ...
        Month N → Start: prev_End + 1 day  |  End: Start + term − 1 day""", language="text")

                            st.markdown("---")
                            st.markdown("##### GC Offer — Segment Label & Quarter Formulas")
                            st.markdown("""
        | Validation | Field | Rule |
        |---|---|---|
        | Segment Label | `OrderItem.Segment_Label__c` | Must match `QuoteLine.SBQQ__SegmentLabel__c` |
        | Quarter | `OrderItem.Quarter__c` | Must equal the numeric part of `Segment_Label__c` — strip "Month ", keep the number |
        """)
                            st.markdown("**Quarter__c examples:**")
                            st.code("""\
        Segment_Label__c = "Month 1"   → Quarter__c must be "1"
        Segment_Label__c = "Month 12"  → Quarter__c must be "12"
        Segment_Label__c = "Month 36"  → Quarter__c must be "36"
        Segment_Label__c = null/blank  → Quarter__c must be blank""", language="text")

                        with _tab_ent:
                            st.markdown("##### Entitlement Validations — Formulas")
                            st.markdown("Applies when `Order.Order_Sub_Type__c != 'GC Offer'`. "
                                        "Entitlements are filtered by `Type` before validating.")

                            st.markdown("**Phone Support (`Type = 'Phone Support'`)**")
                            st.markdown("""
        | # | Validation | Rule |
        |---|---|---|
        | 1 | SubType | `SubType__c == "Rubrik Support"` |
        | 2 | Product | `Entitlement.Name == Order_Service_Item__r.Printable_Product__c` |
        | 3 | Base Product | `Product__r.Name == Order_Service_Item__r.Product2.Name` |
        | 4 | Subscription Term | `Subscription_Term__c == Order_Service_Item__r.SBQQ__SubscriptionTerm__c` |
        | 5 | Quantity | `Quantity__c == Order_Quantity__c` |
        """)

                            st.markdown("**Manufacturing Entitlement (`Type = 'Manufacturing Entitlement'`)**")
                            st.markdown("""
        | # | Validation | Rule |
        |---|---|---|
        | 1 | MFG Ent SubType | `SubType__c` must be **blank / null** |
        | 2 | MFG Ent BaseProductName | `Product__r.Name == "TPH-MFG-ENT"` |
        """)

                        with _tab_soql:
                            st.markdown("##### SOQL Queries Used")
                            st.markdown("**1 — Order (header fields)**")
                            st.code("""\
        SELECT ProcessType__c, Stage_PO__c, ScreenStatus__c, Type, Order_Sub_Type__c,
               Line_Types__c, Order_Status__c, BookingStatus__c,
               Have_Polaris_Products__c, Has_Third_Party_Hardware_Product__c,
               Third_Party_Hardware_fulfilment_status__c,
               RSC_G_Enabled__c, Ready_for_Gov_Sync__c,
               RSC_G_Contact__c, RSC_G_Contact_Email__c, RSC_G_Contact_Phone__c,
               Order_Accepted_Timestamp__c, customer_required_ship_date__c,
               Est_Ship_Date__c, Deliver_By__c, Actual_Order_Ship_Date__c,
               TotalAmount,
               Welcome_letter_sent_for_the_first_time__c,
               WelcomeEmailSentforSoftwareProducts__c, SD_Status__c,
               Bill_To_Name__r.Id, Bill_To_Name__r.Name,
               SBQQ__Quote__r.Name, SBQQ__Quote__r.ProcessType__c,
               SBQQ__Quote__r.SBQQ__NetAmount__c, SBQQ__Quote__r.Manual_Fulfillment_Quote__c,
               Opportunity.Has_Polaris_Product__c,
               Opportunity.Rubrik_Security_Cloud_Gov_t_Owner__c,
               Opportunity.Rubrik_Security_Cloud_Gov_t_Owner__r.Email,
               Opportunity.Rubrik_Security_Cloud_Gov_t_Owner__r.Phone
        FROM Order WHERE OrderNumber = '<order_num>'""", language="sql")

                            st.markdown("**2 — OrderItem (line items)**")
                            st.code("""\
        SELECT Product2.Shipping_Lead_Time__c, Product2.Order_Fulfilment__c,
               Product2.Name, Product2.Product_Type__c,
               Printable_Product__c, Opportunity_Product__r.Printable_Product__c,
               Payment_Options__c,
               SBQQ__QuoteLine__r.Product_Payment_Option__c,
               SBQQ__SubscriptionTerm__c,
               SBQQ__QuoteLine__r.SBQQ__SubscriptionTerm__c,
               SBQQ__QuoteLine__r.SBQQ__StartDate__c,
               SBQQ__QuoteLine__r.End_Date__c,
               SerialNumber__c,
               Support_Start_Date__c, Support_End_Date__c, Support_Term__c,
               Segment_Label__c,
               UnitPrice, Quantity, TotalPrice
        FROM OrderItem WHERE Order.OrderNumber = '<order_num>'""", language="sql")

                            st.markdown("**3 — Printable Product counts**")
                            st.code("""\
        SELECT COUNT(Opportunity_Product__r.Printable_Product__c) countOppProduct,
               COUNT(Printable_Product__c) countPrintableProduct
        FROM OrderItem WHERE Order.OrderNumber = '<order_num>'""", language="sql")

                            st.markdown("**4 — Order Success Metrics**")
                            st.code("""\
        SELECT Order_Creation_Metrics__c, Order_Booking_Metrics__c,
               Order_Provisioning_Metrics__c, Booking_Creation_Metrics__c,
               SC_creation_Metrics__c, Stage_PO_Submission_Metrics__c,
               CLI_creation_Metrics__c, Entitlement_Creation_Metrics__c, Comment__c
        FROM Order_Success_Metrics__c
        WHERE Order__r.Order_Number__c = '<order_num>'
        LIMIT 1""", language="sql")

                            st.markdown("**5 — Quote aggregate (all linked orders sum)**")
                            st.code("""\
        SELECT SUM(TotalAmount) totalLinkedAmount
        FROM Order
        WHERE SBQQ__Quote__c = '<quote_id>'
          AND Status != 'Cancelled'""", language="sql")

                            st.markdown("**6 — Entitlements (Phone Support & Manufacturing)**")
                            st.code("""\
        SELECT Name, Type, SubType__c,
               Order_Service_Item__r.Printable_Product__c,
               Product__r.Name,
               Order_Service_Item__r.Product2.Name,
               Subscription_Term__c,
               Order_Service_Item__r.SBQQ__SubscriptionTerm__c,
               Quantity__c,
               Order_Quantity__c
        FROM Entitlement
        WHERE Order_Service_Item__r.Order.Order_Number__c = '<order_num>'""", language="sql")
                            st.info("ℹ️ Note: This WHERE clause returns entitlements linked via "
                                    "`Order_Service_Item__r`. If Manufacturing Entitlements use a "
                                    "different relationship, the field may need to be updated.")

                    # Placeholder for overall summary table — filled after all validations are computed
                    overall_summary_placeholder = st.empty()

                    # ── Distributor lookup ─────────────────────────────────────────────
                    EDI_DISTRIBUTORS = {
                        "0018Y00002yRMhdQAG": "EDI & Ingram Distributor",
                        "0011W00001zHdYfQAK": "EDI & Arrow Distributor",
                        "0014000001gDigqAAC": "EDI & EXN UK Distributor",
                        "0014000001o5BNXAA2": "EDI & Carahsoft Distributor",
                    }
                    CARAHSOFT_ID = "0014000001o5BNXAA2"

                    # ── Validation rules ───────────────────────────────────────────────
                    results           = []
                    orderitem_results = []

                    # Order details — informational
                    for label, value in [
                        ("Type",              sf_order_type),
                        ("Order_Sub_Type__c", order_sub_type),
                        ("Line_Types__c",     line_types),
                        ("Order_Status__c",   order_status),
                    ]:
                        results.append({"#": "—", "Validation": f"Order Info — {label}",
                                         "Details": f"{label}: {value or '(blank)'}",
                                         "Expected": "—", "Actual": value or "(blank)",
                                         "Status": f"ℹ️ {value or '(blank)'}"})

                    # Order Success Metrics — informational
                    METRICS_FIELDS = [
                        ("Order_Creation_Metrics__c",       "Order Creation Metrics"),
                        ("Order_Booking_Metrics__c",        "Order Booking Metrics"),
                        ("Order_Provisioning_Metrics__c",   "Order Provisioning Metrics"),
                        ("Booking_Creation_Metrics__c",     "Booking Creation Metrics"),
                        ("SC_creation_Metrics__c",          "SC Creation Metrics"),
                        ("Stage_PO_Submission_Metrics__c",  "Stage PO Submission Metrics"),
                        ("CLI_creation_Metrics__c",         "CLI Creation Metrics"),
                        ("Entitlement_Creation_Metrics__c", "Entitlement Creation Metrics"),
                        ("Comment__c",                      "Comment"),
                    ]
                    for field, label in METRICS_FIELDS:
                        val = metrics_record.get(field) or "(blank)"
                        results.append({"#": "—", "Validation": f"Metrics — {label}",
                                         "Details": f"{field}: {val}", "Expected": "—",
                                         "Actual": val, "Status": f"ℹ️ {val}"})

                    # Validation 1 — Process Type Sync
                    _qt_aspen   = (quote_process_type or "").upper() == "ASPEN"
                    _qt_null    = not quote_process_type
                    _sub_null   = not order_sub_type
                    _ord_aspen  = (order_process_type or "").upper() == "ASPEN"
                    _ord_null   = not order_process_type
                    _pt_detail  = (f"Quote.ProcessType__c: {quote_process_type or '(blank)'} | "
                                   f"Order.ProcessType__c: {order_process_type or '(blank)'} | "
                                   f"Order_Sub_Type__c: {order_sub_type or '(blank)'}")

                    if _qt_aspen and _sub_null and _ord_aspen:
                        pt_status   = "✅ PASS"
                        pt_expected = "ASPEN"
                        pt_actual   = "ASPEN"
                    elif _qt_aspen and _sub_null and _ord_null:
                        pt_status   = "❌ FAIL"
                        pt_expected = "ASPEN"
                        pt_actual   = "(blank)"
                    elif _qt_aspen and not _sub_null and _ord_null:
                        pt_status   = "ℹ️ N/A (Order_Sub_Type__c is set, Order.ProcessType__c is null)"
                        pt_expected = "(blank)"
                        pt_actual   = "(blank)"
                    elif _qt_aspen and not _sub_null and not _ord_null:
                        pt_status   = "ℹ️ N/A (Order_Sub_Type__c is set — ProcessType not required)"
                        pt_expected = "—"
                        pt_actual   = order_process_type or "(blank)"
                    elif _qt_null and not _sub_null and _ord_null:
                        pt_status   = "✅ PASS"
                        pt_expected = "(blank)"
                        pt_actual   = "(blank)"
                    elif _qt_null and _sub_null and _ord_null:
                        pt_status   = "✅ PASS"
                        pt_expected = "(blank)"
                        pt_actual   = "(blank)"
                    else:
                        _match    = order_process_type == quote_process_type
                        pt_status = "✅ PASS" if _match else "❌ FAIL"
                        pt_expected = quote_process_type or "(blank)"
                        pt_actual   = order_process_type or "(blank)"

                    results.append({"#": "1", "Validation": "Process Type Sync (Quote → Order)",
                                     "Details":  _pt_detail,
                                     "Expected": pt_expected,
                                     "Actual":   pt_actual,
                                     "Status":   pt_status})

                    # Validation 2 — Order Type Classification
                    if stage_po is not None:
                        order_type = EDI_DISTRIBUTORS.get(bill_to_id, "Glynt PO (PO PDF)")
                    elif bill_to_id != CARAHSOFT_ID:
                        order_type = "NON EDI"
                    else:
                        order_type = "Unclassified"
                    results.append({"#": "2", "Validation": "Order Type Classification",
                                     "Details": f"Stage_PO__c: {'set' if stage_po else 'null'} | Bill To: {bill_to_name}",
                                     "Expected": "—", "Actual": order_type, "Status": f"ℹ️ {order_type}"})

                    # Process Type — ASPEN / Non ASPEN
                    process_type_label = "ASPEN" if order_process_type == "ASPEN" else "Non ASPEN"
                    results.append({"#": "—", "Validation": "Process Type",
                                     "Details": f"ProcessType__c: {order_process_type or '(blank)'}",
                                     "Expected": "—", "Actual": process_type_label,
                                     "Status": f"ℹ️ {process_type_label}"})

                    # Validation 3 — GTC Screen Status
                    SCREEN_STATUS_MAP = {"Approved": "GTC Screened", "Approved Bypassed": "GTC Screening bypassed", "On Hold": "GTC Screening OnHold"}
                    gtc_result = SCREEN_STATUS_MAP.get(screen_status, f"Unknown ({screen_status or 'blank'})")
                    results.append({"#": "3", "Validation": "GTC Screen Status",
                                     "Details": f"ScreenStatus__c: {screen_status or '(blank)'}",
                                     "Expected": "—", "Actual": gtc_result, "Status": f"ℹ️ {gtc_result}"})

                    # Validation 4 — Lead Time
                    results.append({"#": "4", "Validation": "Lead Time (Max across line items)",
                                     "Details": f"Product2.Shipping_Lead_Time__c max = {max_lt} week(s)",
                                     "Expected": "—", "Actual": f"{max_lt} week(s)", "Status": f"ℹ️ {max_lt} week(s)"})

                    # Validation 5 — CESD
                    td_str = target_date.strftime("%Y-%m-%d") if target_date else ""
                    cesd_candidates, cesd_sources = [], []
                    if max_lt > 0 and order_accepted:
                        lt_days  = max_lt * 7
                        acc_plus = add_days(order_accepted, lt_days)
                        cesd_candidates.append(acc_plus)
                        cesd_sources.append(f"OrderAccepted({order_accepted}) + {max_lt}w = {acc_plus}")
                    if crsd:
                        cesd_candidates.append(crsd)
                        cesd_sources.append(f"CRSD({crsd})")
                    if td_str:
                        cesd_candidates.append(td_str)
                        cesd_sources.append(f"TargetDate({td_str})")
                    if cesd_candidates:
                        valid_dates = [d for d in cesd_candidates if parse_date(d)]
                        cesd_calc   = max(valid_dates, key=lambda d: parse_date(d)) if valid_dates else ""
                    else:
                        cesd_calc = add_days(order_accepted, 7)
                        cesd_sources.append(f"OrderAccepted({order_accepted}) + 7d (no lead time/CRSD/target)")
                    cesd_pass   = cesd_calc == est_ship_date
                    cesd_detail = f"Calc: {' | '.join(cesd_sources)} → {cesd_calc} | SF Est_Ship_Date__c: {est_ship_date or '(blank)'}"
                    results.append({"#": "5", "Validation": "CESD (Current Est Ship Date)",
                                     "Details": cesd_detail, "Expected": cesd_calc,
                                     "Actual": est_ship_date or "(blank)", "Status": "✅ PASS" if cesd_pass else "❌ FAIL"})

                    # Validation 6 — EDD
                    edd_calc  = add_days(cesd_calc, 7) if max_lt > 0 else cesd_calc
                    edd_logic = f"CESD({cesd_calc}) + 7d" if max_lt > 0 else f"CESD({cesd_calc}) (Lead Time=0)"
                    edd_pass  = edd_calc == deliver_by
                    results.append({"#": "6", "Validation": "EDD (Est Delivery Date)",
                                     "Details": f"Calc: {edd_logic} = {edd_calc} | SF Deliver_By__c: {deliver_by or '(blank)'}",
                                     "Expected": edd_calc, "Actual": deliver_by or "(blank)",
                                     "Status": "✅ PASS" if edd_pass else "❌ FAIL"})

                    # Validation 7 — Booking Status
                    ORDER_ACTIVE_STATUSES = {"Order Accepted", "Shipped"}
                    order_status_active   = order_status in ORDER_ACTIVE_STATUSES
                    if booking_status == "Completed" and order_status_active:
                        booking_label, booking_status_val = "Bookings created", "✅ PASS"
                    elif booking_status in ("Booking Failed", "") and order_status_active:
                        booking_label, booking_status_val = "Bookings were not created", "❌ FAIL"
                    else:
                        booking_label, booking_status_val = f"N/A (Order Status: {order_status or '(blank)'})", "ℹ️ N/A"
                    results.append({"#": "7", "Validation": "Booking Status",
                                     "Details": f"BookingStatus__c: {booking_status or '(blank)'} | Order_Status__c: {order_status or '(blank)'}",
                                     "Expected": "Completed (when Order Accepted/Shipped)",
                                     "Actual": booking_label, "Status": booking_status_val})

                    # Validation 8 — Polaris Products Sync
                    opp_pol_bool   = bool(opp_polaris)
                    order_pol_bool = bool(order_polaris)
                    polaris_passed = opp_pol_bool == order_pol_bool

                    # Validation 9 — Third Party Hardware
                    has_tph_bool = bool(has_tph)
                    if has_tph_bool and tph_status == "Completed":
                        tph_label, tph_result = "Third Party Hardware fulfilment status — Completed", "✅ PASS"
                    elif has_tph_bool and tph_status != "Completed":
                        tph_label, tph_result = f"Third Party Hardware fulfilment status — {tph_status or '(blank)'} (expected Completed)", "❌ FAIL"
                    elif not has_tph_bool and tph_status == "Not Needed":
                        tph_label, tph_result = "Third Party Hardware fulfilment status — Not Needed", "✅ PASS"
                    else:
                        tph_label, tph_result = f"Third Party Hardware fulfilment status — {tph_status or '(blank)'} (expected Not Needed)", "❌ FAIL"
                    results.append({"#": "9", "Validation": "Third Party Hardware Fulfilment",
                                     "Details": f"Has_Third_Party_Hardware_Product__c: {has_tph_bool} | fulfilment_status: {tph_status or '(blank)'}",
                                     "Expected": "Completed" if has_tph_bool else "Not Needed",
                                     "Actual": tph_status or "(blank)", "Status": tph_result})

                    results.append({"#": "8", "Validation": "RSC Provisioning — Polaris Products Sync",
                                     "Details": f"Opp.Has_Polaris_Product__c: {opp_pol_bool} | Order.Have_Polaris_Products__c: {order_pol_bool}",
                                     "Expected": f"Order = {opp_pol_bool} (must match Opportunity)",
                                     "Actual": f"Order = {order_pol_bool}",
                                     "Status": "✅ PASS — Requires RSC Provisioning" if polaris_passed and opp_pol_bool
                                               else "✅ PASS — RSC Provisioning not required" if polaris_passed and not opp_pol_bool
                                               else "❌ FAIL — Requires RSC Provisioning (mismatch)"})

                    # ManualFulfilment
                    order_manual_fulfil = bool(record.get("ManualFulfilment__c"))
                    if manual_fulfillment_quote is not None:
                        # New logic: Quote.Manual_Fulfillment_Quote__c is set — check Order flag directly
                        if order_manual_fulfil:
                            mf_label  = f"Quote.Manual_Fulfillment_Quote__c is set, Order.ManualFulfilment__c = True"
                            mf_status = "✅ PASS"
                        else:
                            mf_label  = f"Quote.Manual_Fulfillment_Quote__c is set but Order.ManualFulfilment__c = False"
                            mf_status = "❌ FAIL"
                        mf_details  = (f"Quote.Manual_Fulfillment_Quote__c: {manual_fulfillment_quote} | "
                                       f"Order.ManualFulfilment__c: {order_manual_fulfil}")
                        mf_expected = "ManualFulfilment__c = True (Quote.Manual_Fulfillment_Quote__c is not null)"
                    else:
                        # Existing logic: derive from product Order_Fulfilment__c
                        if has_manual_product and order_manual_fulfil:
                            mf_label, mf_status = "Product requires manual fulfil, Order flag = True", "✅ PASS"
                        elif not has_manual_product and not order_manual_fulfil:
                            mf_label, mf_status = "No manual products, Order flag = False", "✅ PASS"
                        elif has_manual_product and not order_manual_fulfil:
                            mf_label, mf_status = "Product requires manual fulfil but Order flag = False", "❌ FAIL"
                        else:
                            mf_label, mf_status = "No manual products but Order flag = True", "❌ FAIL"
                        mf_details  = (f"Quote.Manual_Fulfillment_Quote__c: null | "
                                       f"Product2.Order_Fulfilment__c = Manual: {has_manual_product} | "
                                       f"Order.ManualFulfilment__c: {order_manual_fulfil}")
                        mf_expected = "ManualFulfilment__c = True when any product Order_Fulfilment__c = Manual"
                    orderitem_results.append({"#": "—", "Validation": "ManualFulfilment",
                                               "Details": mf_details,
                                               "Expected": mf_expected,
                                               "Actual": mf_label, "Status": mf_status})

                    # Product Name Match (per line item)
                    for item in items_result.get("records", []):
                        p2       = item.get("Product2") or {}
                        p2_name  = p2.get("Name") or "(unknown product)"
                        order_pp = (item.get("Printable_Product__c") or "").strip()
                        opp_r    = item.get("Opportunity_Product__r") or {}
                        opp_pp   = (opp_r.get("Printable_Product__c") or "").strip()
                        matched  = order_pp.lower() == opp_pp.lower()
                        orderitem_results.append({"#": "—", "Validation": f"Product Name Match — {p2_name}",
                                                   "Details": f"OrderItem: {order_pp or '(blank)'} | Opportunity: {opp_pp or '(blank)'}",
                                                   "Expected": opp_pp or "(blank)", "Actual": order_pp or "(blank)",
                                                   "Status": "✅ PASS — productName matched" if matched else "❌ FAIL — productName not matched"})

                    # Payment Options Match (per line item)
                    for item in items_result.get("records", []):
                        p2       = item.get("Product2") or {}
                        p2_name  = p2.get("Name") or "(unknown product)"
                        order_po = (item.get("Payment_Options__c") or "").strip()
                        ql_r     = item.get("SBQQ__QuoteLine__r") or {}
                        quote_po = (ql_r.get("Product_Payment_Option__c") or "").strip()
                        matched  = order_po.lower() == quote_po.lower()
                        orderitem_results.append({"#": "—", "Validation": f"Payment Options Match — {p2_name}",
                                                   "Details": f"OrderItem: {order_po or '(blank)'} | QuoteLine: {quote_po or '(blank)'}",
                                                   "Expected": quote_po or "(blank)", "Actual": order_po or "(blank)",
                                                   "Status": "✅ PASS — PaymentOptions matched" if matched else "❌ FAIL — PaymentOptions not matched"})

                    # Subscription Term Match (per line item)
                    # Excluded for GC Offer / GC OnDemand / GC Renewal orders
                    _ST_EXCLUDED_SUBTYPES = {"GC Offer", "GC OnDemand", "GC Renewal"}
                    for item in ([] if order_sub_type in _ST_EXCLUDED_SUBTYPES else items_result.get("records", [])):
                        p2            = item.get("Product2") or {}
                        p2_name       = p2.get("Name") or "(unknown product)"
                        oi_term       = item.get("SBQQ__SubscriptionTerm__c")
                        ql_r          = item.get("SBQQ__QuoteLine__r") or {}
                        ql_term       = ql_r.get("SBQQ__SubscriptionTerm__c")
                        oi_term_str   = str(int(oi_term)) if oi_term is not None else "(blank)"
                        ql_term_str   = str(int(ql_term)) if ql_term is not None else "(blank)"
                        matched       = oi_term_str == ql_term_str
                        orderitem_results.append({
                            "#":          "—",
                            "Validation": f"Subscription Term Match — {p2_name}",
                            "Details":    f"OrderItem: {oi_term_str} | QuoteLine: {ql_term_str}",
                            "Expected":   ql_term_str,
                            "Actual":     oi_term_str,
                            "Status":     "✅ PASS — Subscription Term matched" if matched else "❌ FAIL — Subscription Term not matched",
                        })

                    # Support Start & End Date (per line item)
                    # GC Offer orders use chained-segment logic handled separately below
                    for item in ([] if order_sub_type == "GC Offer" else items_result.get("records", [])):
                        p2           = item.get("Product2") or {}
                        p2_name      = p2.get("Name") or "(unknown product)"
                        oi_term      = item.get("SBQQ__SubscriptionTerm__c")
                        oi_start     = (item.get("Support_Start_Date__c") or "")[:10]
                        oi_end       = (item.get("Support_End_Date__c") or "")[:10]
                        support_term = item.get("Support_Term__c")
                        ql_r         = item.get("SBQQ__QuoteLine__r") or {}

                        if order_sub_type == "Renewal":
                            # Renewal: expected dates come from QuoteLine
                            exp_start = (ql_r.get("SBQQ__StartDate__c") or "")[:10]
                            exp_end   = (ql_r.get("End_Date__c") or "")[:10]

                            start_pass = oi_start == exp_start
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"Support Start Date — {p2_name}",
                                "Details":    f"Support_Start_Date__c: {oi_start or '(blank)'} | Expected: SBQQ__QuoteLine__r.SBQQ__StartDate__c ({exp_start or '(blank)'})",
                                "Expected":   exp_start or "(blank)",
                                "Actual":     oi_start or "(blank)",
                                "Status":     "✅ PASS — Support Start Date matched" if start_pass else "❌ FAIL — Support Start Date not matched",
                            })

                            end_pass = oi_end == exp_end
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"Support End Date — {p2_name}",
                                "Details":    f"Support_End_Date__c: {oi_end or '(blank)'} | Expected: SBQQ__QuoteLine__r.End_Date__c ({exp_end or '(blank)'})",
                                "Expected":   exp_end or "(blank)",
                                "Actual":     oi_end or "(blank)",
                                "Status":     "✅ PASS — Support End Date matched" if end_pass else "❌ FAIL — Support End Date not matched",
                            })

                        else:
                            # Non-Renewal: Support Start Date vs Actual_Order_Ship_Date__c
                            start_pass = oi_start == actual_ship_date
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"Support Start Date — {p2_name}",
                                "Details":    f"Support_Start_Date__c: {oi_start or '(blank)'} | Expected: Actual_Order_Ship_Date__c ({actual_ship_date or '(blank)'})",
                                "Expected":   actual_ship_date or "(blank)",
                                "Actual":     oi_start or "(blank)",
                                "Status":     "✅ PASS — Support Start Date matched" if start_pass else "❌ FAIL — Support Start Date not matched",
                            })

                            # Support End Date — requires oi_term; skip when SBQQ__SubscriptionTerm__c is null
                            if oi_term is None:
                                continue

                            if support_term is None:
                                # Support_Term__c is null → use SBQQ__SubscriptionTerm__c
                                exp_end   = add_days(add_months(oi_start, int(oi_term)), -1) if oi_start else ""
                                term_used = f"SBQQ__SubscriptionTerm__c ({int(oi_term)} month(s))"
                            else:
                                # Support_Term__c is not null → use Support_Term__c
                                exp_end   = add_days(add_months(oi_start, int(support_term)), -1) if oi_start else ""
                                term_used = f"Support_Term__c ({int(support_term)} month(s))"

                            end_pass = oi_end == exp_end
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"Support End Date — {p2_name}",
                                "Details":    f"Support_End_Date__c: {oi_end or '(blank)'} | Expected: {exp_end or '(blank)'} | Base: Support_Start_Date__c ({oi_start or '(blank)'}) | Term used: {term_used}",
                                "Expected":   exp_end or "(blank)",
                                "Actual":     oi_end or "(blank)",
                                "Status":     "✅ PASS — Support End Date matched" if end_pass else "❌ FAIL — Support End Date not matched",
                            })

                    # ── GC Offer: Segment Label Match + Support Start & End Date ──────────
                    if order_sub_type == "GC Offer":
                        # Segment Label Match — OrderItem.SBQQ__SegmentLabel__c vs QuoteLine.SBQQ__SegmentLabel__c
                        for _item in items_result.get("records", []):
                            _p2      = _item.get("Product2") or {}
                            _p2_name = _p2.get("Name") or "(unknown product)"
                            _ql_r    = _item.get("SBQQ__QuoteLine__r") or {}
                            _oi_seg_lbl = (_item.get("Segment_Label__c") or "").strip()
                            _ql_seg_lbl = (_ql_r.get("SBQQ__SegmentLabel__c") or "").strip()
                            _seg_match  = _oi_seg_lbl == _ql_seg_lbl
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"Segment Label — {_p2_name}",
                                "Details":    (f"OrderItem.Segment_Label__c: {_oi_seg_lbl or '(blank)'} | "
                                               f"QuoteLine.SBQQ__SegmentLabel__c: {_ql_seg_lbl or '(blank)'}"),
                                "Expected":   _ql_seg_lbl or "(blank)",
                                "Actual":     _oi_seg_lbl or "(blank)",
                                "Status":     "✅ PASS — Segment Label matched" if _seg_match else "❌ FAIL — Segment Label not matched",
                            })

                        # Quarter__c Match — Quarter__c must equal the number extracted from Segment_Label__c
                        # e.g. Segment_Label__c = "Month 3" → expected Quarter__c = "3"
                        #      Segment_Label__c = null/blank → expected Quarter__c = blank
                        for _item in items_result.get("records", []):
                            _p2      = _item.get("Product2") or {}
                            _p2_name = _p2.get("Name") or "(unknown product)"
                            _seg     = (_item.get("Segment_Label__c") or "").strip()

                            # Derive expected Quarter from segment label
                            if _seg:
                                try:
                                    _exp_qtr = str(int(_seg.split()[-1]))
                                except (ValueError, IndexError):
                                    _exp_qtr = ""
                            else:
                                _exp_qtr = ""

                            # Quarter__c may come back as a number (float) from Salesforce
                            _qtr_raw = _item.get("Quarter__c")
                            if _qtr_raw is not None:
                                try:
                                    _oi_qtr = str(int(float(_qtr_raw)))
                                except (ValueError, TypeError):
                                    _oi_qtr = str(_qtr_raw).strip()
                            else:
                                _oi_qtr = ""

                            _qtr_match = _oi_qtr == _exp_qtr
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"Quarter — {_p2_name}",
                                "Details":    (f"Quarter__c: {_oi_qtr or '(blank)'} | "
                                               f"Expected: {_exp_qtr or '(blank)'} | "
                                               f"Segment_Label__c: {_seg or '(blank)'}"),
                                "Expected":   _exp_qtr or "(blank)",
                                "Actual":     _oi_qtr or "(blank)",
                                "Status":     "✅ PASS — Quarter value matched" if _qtr_match else "❌ FAIL — Quarter value not matched",
                            })

                        # Separate items into null-segment and numbered-segment groups
                        _null_seg_items     = []
                        _numbered_seg_items = []
                        for _item in items_result.get("records", []):
                            _seg = (_item.get("Segment_Label__c") or "").strip()
                            if _seg:
                                try:
                                    _seg_num = int(_seg.split()[-1])
                                    _numbered_seg_items.append((_seg_num, _seg, _item))
                                except (ValueError, IndexError):
                                    _null_seg_items.append(("(unparseable)", _item))
                            else:
                                _null_seg_items.append(("(blank)", _item))
                        _numbered_seg_items.sort(key=lambda x: x[0])

                        def _gc_append(p2_name, seg_display, oi_start, oi_end, oi_term, exp_start,
                                       support_term=None, end_base=None):
                            """Compute expected end, append start + end validation rows.

                            Term priority: Support_Term__c wins when set, falls back to
                            SBQQ__SubscriptionTerm__c — same rule as the non-renewal path.
                            end_base: date used as the base for exp_end calculation (defaults
                            to exp_start so numbered segments chain correctly).
                            """
                            _end_base = end_base if end_base is not None else exp_start
                            if support_term is not None:
                                _eff_term  = int(support_term)
                                _term_info = f"Support_Term__c ({_eff_term} month(s))"
                            elif oi_term is not None:
                                _eff_term  = int(oi_term)
                                _term_info = f"SBQQ__SubscriptionTerm__c ({_eff_term} month(s))"
                            else:
                                _eff_term  = None
                                _term_info = "SBQQ__SubscriptionTerm__c (null)"

                            if _eff_term is not None and _end_base:
                                _exp_end = add_days(add_months(_end_base, _eff_term), -1)
                            else:
                                _exp_end = ""

                            _start_pass = oi_start == exp_start
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"Support Start Date — {p2_name} (Segment: {seg_display})",
                                "Details":    (f"Support_Start_Date__c: {oi_start or '(blank)'} | "
                                               f"Expected: Actual_Order_Ship_Date__c ({exp_start or '(blank)'}) | "
                                               f"Segment: {seg_display}"),
                                "Expected":   exp_start or "(blank)",
                                "Actual":     oi_start or "(blank)",
                                "Status":     "✅ PASS — Support Start Date matched" if _start_pass else "❌ FAIL — Support Start Date not matched",
                            })

                            if not _exp_end:
                                orderitem_results.append({
                                    "#":          "—",
                                    "Validation": f"Support End Date — {p2_name} (Segment: {seg_display})",
                                    "Details":    f"Cannot calculate expected end date — {_term_info}",
                                    "Expected":   "(blank — term null)",
                                    "Actual":     oi_end or "(blank)",
                                    "Status":     "ℹ️ N/A — SubscriptionTerm is null",
                                })
                            else:
                                _end_pass = oi_end == _exp_end
                                orderitem_results.append({
                                    "#":          "—",
                                    "Validation": f"Support End Date — {p2_name} (Segment: {seg_display})",
                                    "Details":    (f"Support_End_Date__c: {oi_end or '(blank)'} | "
                                                   f"Expected: {_exp_end} | "
                                                   f"Base: Actual_Order_Ship_Date__c ({_end_base}) | "
                                                   f"Term used: {_term_info}"),
                                    "Expected":   _exp_end,
                                    "Actual":     oi_end or "(blank)",
                                    "Status":     "✅ PASS — Support End Date matched" if _end_pass else "❌ FAIL — Support End Date not matched",
                                })
                            return _exp_end  # caller uses this to chain the next segment

                        # Validate null-segment items independently.
                        # Both start and end date are based on Actual_Order_Ship_Date__c:
                        #   Support_Start_Date__c = Actual_Order_Ship_Date__c
                        #   Support_End_Date__c   = Actual_Order_Ship_Date__c + effective_term - 1 day
                        #   (effective_term = Support_Term__c if set, else SBQQ__SubscriptionTerm__c)
                        for _seg_display, _item in _null_seg_items:
                            _p2           = _item.get("Product2") or {}
                            _p2_name      = _p2.get("Name") or "(unknown product)"
                            _oi_start     = (_item.get("Support_Start_Date__c") or "")[:10]
                            _oi_end       = (_item.get("Support_End_Date__c") or "")[:10]
                            _oi_term      = _item.get("SBQQ__SubscriptionTerm__c")
                            _support_term = _item.get("Support_Term__c")
                            _gc_append(_p2_name, _seg_display, _oi_start, _oi_end, _oi_term, actual_ship_date,
                                       support_term=_support_term)

                        # Validate numbered-segment items with chaining
                        _prev_exp_end = ""
                        for _seg_num, _seg_label, _item in _numbered_seg_items:
                            _p2           = _item.get("Product2") or {}
                            _p2_name      = _p2.get("Name") or "(unknown product)"
                            _oi_start     = (_item.get("Support_Start_Date__c") or "")[:10]
                            _oi_end       = (_item.get("Support_End_Date__c") or "")[:10]
                            _oi_term      = _item.get("SBQQ__SubscriptionTerm__c")
                            _support_term = _item.get("Support_Term__c")

                            if _seg_num == 1:
                                _exp_start = actual_ship_date
                            else:
                                _exp_start = add_days(_prev_exp_end, 1) if _prev_exp_end else ""

                            _prev_exp_end = _gc_append(_p2_name, _seg_label, _oi_start, _oi_end, _oi_term, _exp_start,
                                                       support_term=_support_term)

                    # Printable Product Count
                    count_opp_pp   = int(printable_record.get("countOppProduct", 0) or 0)
                    count_order_pp = int(printable_record.get("countPrintableProduct", 0) or 0)
                    if not printable_record:
                        pp_label, pp_status = "Query returned no data", "ℹ️ N/A (query returned no data)"
                    elif count_opp_pp == count_order_pp:
                        pp_label, pp_status = f"Product Count matched ({count_order_pp})", "✅ PASS"
                    else:
                        pp_label  = f"Product Count not matched — Order: {count_order_pp} | Opportunity: {count_opp_pp}"
                        pp_status = "❌ FAIL"
                    orderitem_results.append({"#": "—", "Validation": "Printable Product Count",
                                               "Details": f"OrderItem.Printable_Product__c count: {count_order_pp} | Opp_Product.Printable_Product__c count: {count_opp_pp}",
                                               "Expected": f"Counts match (Opportunity = {count_opp_pp})",
                                               "Actual": str(count_order_pp), "Status": pp_status})

                    # Welcome Letter validations
                    # Condition 1: ProcessType = null AND Order_Status = Shipped
                    if not order_process_type and order_status == "Shipped":
                        wl_pass = bool(welcome_first)
                        results.append({
                            "#": "—",
                            "Validation": "Welcome Letter Sent",
                            "Details": (f"Welcome_letter_sent_for_the_first_time__c: {welcome_first} | "
                                        f"ProcessType__c: (blank) | Order_Status__c: {order_status}"),
                            "Expected": "True",
                            "Actual": str(welcome_first),
                            "Status": "✅ PASS — Welcome Letter Sent" if wl_pass else "❌ FAIL — Welcome Letter Not Sent",
                        })

                    # Condition 2: ProcessType != null AND Order_Status = Shipped → First Welcome Letter
                    if order_process_type and order_status == "Shipped":
                        wl2_pass = bool(welcome_sw)
                        results.append({
                            "#": "—",
                            "Validation": "First Welcome Letter Sent",
                            "Details": (f"WelcomeEmailSentforSoftwareProducts__c: {welcome_sw} | "
                                        f"ProcessType__c: {order_process_type} | Order_Status__c: {order_status}"),
                            "Expected": "True",
                            "Actual": str(welcome_sw),
                            "Status": "✅ PASS — First Welcome Letter Sent" if wl2_pass else "❌ FAIL — First Welcome Letter Not Sent",
                        })

                    # Condition 3: ProcessType != null AND Order_Status = Shipped AND SD_Status = Success → Second Welcome Letter
                    if order_process_type and order_status == "Shipped" and sd_status == "Success":
                        wl3_pass = bool(welcome_first)
                        results.append({
                            "#": "—",
                            "Validation": "Second Welcome Letter Sent",
                            "Details": (f"Welcome_letter_sent_for_the_first_time__c: {welcome_first} | "
                                        f"ProcessType__c: {order_process_type} | "
                                        f"Order_Status__c: {order_status} | SD_Status__c: {sd_status}"),
                            "Expected": "True",
                            "Actual": str(welcome_first),
                            "Status": "✅ PASS — Second Welcome Letter Sent" if wl3_pass else "❌ FAIL — Second Welcome Letter Not Sent",
                        })

                    def fmt_amount(val):
                        return f"{val:,.2f}" if val is not None else "(blank)"

                    # Validation 10a — UnitPrice * Quantity = TotalPrice (per line item)
                    for item in items_result.get("records", []):
                        p2        = item.get("Product2") or {}
                        p2_name   = p2.get("Name") or "(unknown product)"
                        unit_price = item.get("UnitPrice")
                        quantity   = item.get("Quantity")
                        total_price = item.get("TotalPrice")
                        if unit_price is None or quantity is None or total_price is None:
                            tp_status = "ℹ️ N/A (blank field)"
                            tp_detail = (f"UnitPrice: {fmt_amount(unit_price)} | "
                                         f"Quantity: {quantity} | TotalPrice: {fmt_amount(total_price)}")
                            tp_expected = "—"
                            tp_actual   = "—"
                        else:
                            tp_calc   = round(float(unit_price) * float(quantity), 2)
                            tp_actual_val = round(float(total_price), 2)
                            tp_pass   = tp_calc == tp_actual_val
                            tp_status = "✅ PASS" if tp_pass else "❌ FAIL"
                            tp_detail = (f"UnitPrice: {fmt_amount(unit_price)} × "
                                         f"Quantity: {quantity} = {fmt_amount(tp_calc)} | "
                                         f"TotalPrice: {fmt_amount(total_price)}")
                            tp_expected = fmt_amount(tp_calc)
                            tp_actual   = fmt_amount(total_price)
                        orderitem_results.append({
                            "#":          "—",
                            "Validation": f"UnitPrice × Quantity = TotalPrice — {p2_name}",
                            "Details":    tp_detail,
                            "Expected":   tp_expected,
                            "Actual":     tp_actual,
                            "Status":     tp_status,
                        })

                    # Validation 10b — SUM(TotalPrice) = Order.TotalAmount
                    oi_total_prices = [
                        item.get("TotalPrice") for item in items_result.get("records", [])
                        if item.get("TotalPrice") is not None
                    ]
                    if not oi_total_prices:
                        results.append({"#": "—", "Validation": "SUM(OrderItem.TotalPrice) vs Order.TotalAmount",
                                         "Details": "No OrderItem TotalPrice values found — validation skipped",
                                         "Expected": fmt_amount(order_total_amount),
                                         "Actual": "(blank)",
                                         "Status": "ℹ️ N/A (no TotalPrice data)"})
                    else:
                        oi_sum      = round(sum(float(v) for v in oi_total_prices), 2)
                        oi_sum_pass = (order_total_amount is not None and
                                       oi_sum == round(float(order_total_amount), 2))
                        oi_breakdown = " + ".join(fmt_amount(v) for v in oi_total_prices)
                        results.append({"#": "—", "Validation": "SUM(OrderItem.TotalPrice) vs Order.TotalAmount",
                                         "Details": (f"SUM({oi_breakdown}) = {fmt_amount(oi_sum)} | "
                                                     f"Order.TotalAmount: {fmt_amount(order_total_amount)}"),
                                         "Expected": fmt_amount(order_total_amount),
                                         "Actual":   fmt_amount(oi_sum),
                                         "Status":   "✅ PASS" if oi_sum_pass else "❌ FAIL"})

                    # SerialNumber vs Quantity (per line item)
                    # SerialNumber__c stores comma-separated serials (e.g. "SN1,SN2,SN3")
                    # Rule: count of serial numbers must equal Quantity
                    # Hardware with no serial at all → FAIL
                    for item in items_result.get("records", []):
                        p2           = item.get("Product2") or {}
                        p2_name      = p2.get("Name") or "(unknown product)"
                        product_type = (p2.get("Product_Type__c") or "").strip()
                        serial_raw   = (item.get("SerialNumber__c") or "").strip()
                        qty          = item.get("Quantity") or 0
                        qty_int      = int(qty)

                        if serial_raw:
                            serial_list  = [s.strip() for s in serial_raw.split(",") if s.strip()]
                            serial_count = len(serial_list)
                            sn_pass      = serial_count == qty_int
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"SerialNumber vs Quantity — {p2_name}",
                                "Details":    f"Serial count: {serial_count} | Quantity: {qty_int} | Serials: {serial_raw[:60]}{'…' if len(serial_raw) > 60 else ''}",
                                "Expected":   str(qty_int),
                                "Actual":     str(serial_count),
                                "Status":     "✅ PASS — Serial count matches Qty" if sn_pass else f"❌ FAIL — {serial_count} serial(s) but Qty = {qty_int}",
                            })
                        elif product_type == "Hardware":
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"SerialNumber vs Quantity — {p2_name}",
                                "Details":    f"SerialNumber__c: (blank) | Quantity: {qty_int} | Product_Type: Hardware",
                                "Expected":   f"{qty_int} serial number(s)",
                                "Actual":     "(blank)",
                                "Status":     "❌ FAIL — Hardware product missing SerialNumber",
                            })
                        else:
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"SerialNumber vs Quantity — {p2_name}",
                                "Details":    f"Product_Type: {product_type or '(blank)'} — serial number not required",
                                "Expected":   "N/A",
                                "Actual":     "N/A",
                                "Status":     "ℹ️ N/A — Non-hardware, serial not required",
                            })

                    # Validation 15 — Quote Net Amount vs SUM of All Linked Orders
                    agg_records = agg_result.get("records", [])
                    if not _quote_id_for_agg:
                        agg_status = "ℹ️ N/A (no Quote linked to Order)"
                        agg_detail = "Order has no linked Quote — aggregate comparison not applicable"
                        agg_actual = "—"
                        agg_expected = "—"
                        results.append({"#": "—", "Validation": "Quote Net Amount vs All Linked Orders Sum",
                                         "Details": agg_detail, "Expected": agg_expected,
                                         "Actual": agg_actual, "Status": agg_status})
                    elif not agg_records:
                        agg_status = "ℹ️ N/A (aggregate query returned no results)"
                        agg_detail = "Aggregate query returned no results — validation skipped"
                        agg_actual = "(blank)"
                        agg_expected = fmt_amount(quote_net_amount)
                        results.append({"#": "—", "Validation": "Quote Net Amount vs All Linked Orders Sum",
                                         "Details": agg_detail, "Expected": agg_expected,
                                         "Actual": agg_actual, "Status": agg_status})
                    else:
                        _agg_rec   = agg_records[0]
                        _agg_sum   = _agg_rec.get("SumOfOrderTotalAmount")
                        _agg_count = int(_agg_rec.get("OrderCount", 0))
                        agg_expected = fmt_amount(quote_net_amount)
                        if _agg_count <= 1:
                            # Only 1 order linked — validation not applicable
                            agg_status = "ℹ️ N/A (only 1 order linked to Quote)"
                            agg_detail = (f"Quote {quote_name} has only {_agg_count} linked order — "
                                          f"multi-order sum validation not applicable")
                            agg_actual = f"{fmt_amount(_agg_sum)} ({_agg_count} order)"
                            results.append({"#": "—", "Validation": "Quote Net Amount vs All Linked Orders Sum",
                                             "Details": agg_detail, "Expected": agg_expected,
                                             "Actual": agg_actual, "Status": agg_status})
                        elif _agg_sum is None or quote_net_amount is None:
                            agg_status = "❌ FAIL"
                            agg_detail = (f"Quote.SBQQ__NetAmount__c: {fmt_amount(quote_net_amount)} | "
                                          f"SUM(TotalAmount): (blank) across {_agg_count} order(s)")
                            agg_actual = f"(blank) ({_agg_count} order(s))"
                            results.append({"#": "—", "Validation": "Quote Net Amount vs All Linked Orders Sum",
                                             "Details": agg_detail, "Expected": agg_expected,
                                             "Actual": agg_actual, "Status": agg_status})
                        else:
                            _agg_match = round(float(_agg_sum), 2) == round(float(quote_net_amount), 2)
                            agg_status = "✅ PASS" if _agg_match else "❌ FAIL"
                            _orders_breakdown = " | ".join(
                                f"{o.get('OrderNumber', '?')}: {fmt_amount(o.get('TotalAmount'))}"
                                for o in linked_orders_list
                            )
                            agg_detail = (f"Quote {quote_name} has {_agg_count} linked orders | "
                                          f"{_orders_breakdown} | "
                                          f"Quote.SBQQ__NetAmount__c: {fmt_amount(quote_net_amount)} | "
                                          f"SUM(Order.TotalAmount): {fmt_amount(_agg_sum)}")
                            agg_actual = f"{fmt_amount(_agg_sum)} ({_agg_count} order(s))"
                            results.append({"#": "—", "Validation": "Quote Net Amount vs All Linked Orders Sum",
                                             "Details": agg_detail, "Expected": agg_expected,
                                             "Actual": agg_actual, "Status": agg_status})

                    # Validation 11 — RSC-G Sync
                    GOV_SYNC_PASS_VALUES = {"Ready for Sync", "Sync completed"}
                    rscg_enabled_bool    = bool(rscg_enabled)
                    if not rscg_enabled_bool:
                        rscg_label, rscg_status = "RSC-G not enabled — validation not applicable", "ℹ️ N/A (RSC-G not enabled)"
                    elif order_status not in ORDER_ACTIVE_STATUSES:
                        rscg_label  = f"Order Status is '{order_status or '(blank)'}' — validation applies only when Order Accepted or Shipped"
                        rscg_status = "ℹ️ N/A (Order not active)"
                    elif ready_for_gov_sync in GOV_SYNC_PASS_VALUES:
                        rscg_label, rscg_status = f"RSCG Sync — {ready_for_gov_sync}", "✅ PASS"
                    else:
                        rscg_label  = f"RSCG Sync — {ready_for_gov_sync or '(blank)'} (expected Ready for Sync or Sync Completed)"
                        rscg_status = "❌ FAIL"
                    results.append({"#": "11", "Validation": "RSCG Sync",
                                     "Details": f"RSC_G_Enabled__c: {rscg_enabled_bool} | Ready_for_Gov_Sync__c: {ready_for_gov_sync or '(blank)'} | Order_Status__c: {order_status or '(blank)'}",
                                     "Expected": "Ready for Sync / Sync Completed (when RSC-G enabled & Order active)",
                                     "Actual": rscg_label, "Status": rscg_status})

                    # Validations 12-14 — RSC-G Contact fields
                    def rscg_contact_check(num, label, order_val, opp_val, optional=False):
                        if not rscg_enabled_bool:
                            return {"#": num, "Validation": label, "Details": "RSC_G_Enabled__c = False — not applicable",
                                    "Expected": "—", "Actual": "—", "Status": "ℹ️ N/A (RSC-G not enabled)"}
                        if optional and not order_val:
                            return {"#": num, "Validation": label, "Details": "Optional field — no value on Order",
                                    "Expected": opp_val or "(blank)", "Actual": "(blank)", "Status": "ℹ️ N/A (optional, not provided)"}
                        if not order_val:
                            return {"#": num, "Validation": label,
                                    "Details": f"Order value is blank | Opportunity: {opp_val or '(blank)'}",
                                    "Expected": opp_val or "(blank)", "Actual": "(blank)", "Status": "❌ FAIL (blank)"}
                        matched = order_val.strip().lower() == opp_val.strip().lower() if opp_val else False
                        return {"#": num, "Validation": label,
                                "Details": f"Order: {order_val} | Opportunity: {opp_val or '(blank)'}",
                                "Expected": opp_val or "(blank)", "Actual": order_val,
                                "Status": "✅ PASS" if matched else "❌ FAIL"}

                    results.append(rscg_contact_check("12", "RSCG Contact (vs Opp Gov Owner ID)", rscg_contact, opp_gov_owner_id))
                    results.append(rscg_contact_check("13", "RSCG Contact Email", rscg_contact_email, opp_gov_email))
                    results.append(rscg_contact_check("14", "RSCG Contact Phone", rscg_contact_phone, opp_gov_phone, optional=True))


                    # ── Entitlement query & validation rows ───────────────────────────────
                    # Run before _all so entitlement counts appear in the header summary.
                    _ent_rows    = []
                    _ent_records = []
                    if order_sub_type != "GC Offer":
                        with st.spinner("Fetching Entitlements…"):
                            try:
                                _soql_ent = f"""
                                    SELECT Name, Type, SubType__c,
                                           Order_Service_Item__r.Printable_Product__c,
                                           Product__r.Name,
                                           Order_Service_Item__r.Product2.Name,
                                           Subscription_Term__c,
                                           Order_Service_Item__r.SBQQ__SubscriptionTerm__c,
                                           Quantity__c,
                                           Order_Quantity__c
                                    FROM Entitlement
                                    WHERE Order_Service_Item__r.Order.Order_Number__c = '{order_num}'
                                """
                                _ent_result  = run_sf_query(alias, _soql_ent)
                                _ent_records = _ent_result.get("records", [])
                            except Exception as e:
                                st.warning(f"Entitlement query failed (skipped): {e}")

                        def _term_str_ent(v):
                            try:
                                return str(int(float(v))) if v is not None else ""
                            except (ValueError, TypeError):
                                return str(v).strip()

                        for _ent in _ent_records:
                            _ent_type       = (_ent.get("Type") or "").strip()
                            _ent_subtype    = (_ent.get("SubType__c") or "").strip()
                            _ent_name       = _ent.get("Name") or "(unknown)"
                            _osi_r          = _ent.get("Order_Service_Item__r") or {}
                            _printable_prod = (_osi_r.get("Printable_Product__c") or "").strip()
                            _ent_prod_r     = _ent.get("Product__r") or {}
                            _ent_prod_name  = (_ent_prod_r.get("Name") or "").strip()
                            _osi_prod2      = _osi_r.get("Product2") or {}
                            _osi_prod2_name = (_osi_prod2.get("Name") or "").strip()
                            _ent_sub_term   = _term_str_ent(_ent.get("Subscription_Term__c"))
                            _osi_sub_term   = _term_str_ent(_osi_r.get("SBQQ__SubscriptionTerm__c"))
                            _ent_qty        = _term_str_ent(_ent.get("Quantity__c"))
                            _ord_qty        = _term_str_ent(_ent.get("Order_Quantity__c"))

                            if _ent_type == "Phone Support":
                                _ent_rows.append({
                                    "#": "—", "Validation": f"SubType — {_ent_name}",
                                    "Details":  (f"Entitlement: {_ent_name} | Type: {_ent_type} | SubType__c: {_ent_subtype or '(blank)'}"),
                                    "Expected": "Rubrik Support", "Actual": _ent_subtype or "(blank)",
                                    "Status":   "✅ PASS — SubType is matched" if _ent_subtype == "Rubrik Support" else "❌ FAIL — SubType is not matched",
                                })
                                _ent_rows.append({
                                    "#": "—", "Validation": f"Product — {_ent_name}",
                                    "Details":  (f"Entitlement.Name: {_ent_name} | Order_Service_Item__r.Printable_Product__c: {_printable_prod or '(blank)'}"),
                                    "Expected": _printable_prod or "(blank)", "Actual": _ent_name,
                                    "Status":   "✅ PASS — Product matched" if _ent_name == _printable_prod else "❌ FAIL — Product not matched",
                                })
                                _ent_rows.append({
                                    "#": "—", "Validation": f"Base Product — {_ent_name}",
                                    "Details":  (f"Entitlement.Product__r.Name: {_ent_prod_name or '(blank)'} | Order_Service_Item__r.Product2.Name: {_osi_prod2_name or '(blank)'}"),
                                    "Expected": _osi_prod2_name or "(blank)", "Actual": _ent_prod_name or "(blank)",
                                    "Status":   "✅ PASS — Base Product matched" if _ent_prod_name == _osi_prod2_name else "❌ FAIL — Base Product not matched",
                                })
                                _ent_rows.append({
                                    "#": "—", "Validation": f"Subscription Term — {_ent_name}",
                                    "Details":  (f"Entitlement.Subscription_Term__c: {_ent_sub_term or '(blank)'} | Order_Service_Item__r.SBQQ__SubscriptionTerm__c: {_osi_sub_term or '(blank)'}"),
                                    "Expected": _osi_sub_term or "(blank)", "Actual": _ent_sub_term or "(blank)",
                                    "Status":   "✅ PASS — Subscription Term matched" if _ent_sub_term == _osi_sub_term else "❌ FAIL — Subscription Term not matched",
                                })
                                _ent_rows.append({
                                    "#": "—", "Validation": f"Quantity — {_ent_name}",
                                    "Details":  (f"Entitlement.Quantity__c: {_ent_qty or '(blank)'} | Entitlement.Order_Quantity__c: {_ord_qty or '(blank)'}"),
                                    "Expected": _ord_qty or "(blank)", "Actual": _ent_qty or "(blank)",
                                    "Status":   "✅ PASS — Quantity matched" if _ent_qty == _ord_qty else "❌ FAIL — Quantity not matched",
                                })

                            elif _ent_type == "Manufacturing Entitlement":
                                # Validation 1: SubType__c must be blank
                                _mfg_pass = _ent_subtype == ""
                                _ent_rows.append({
                                    "#":          "—",
                                    "Validation": f"MFG Ent SubType — {_ent_name}",
                                    "Details":    (f"Entitlement: {_ent_name} | "
                                                   f"Type: {_ent_type} | "
                                                   f"SubType__c: {_ent_subtype or '(blank)'}"),
                                    "Expected":   "(blank)",
                                    "Actual":     _ent_subtype or "(blank)",
                                    "Status":     "✅ PASS — MFG Ent SubType PASS" if _mfg_pass else "❌ FAIL — MFG Ent SubType is not null",
                                })

                                # Validation 2: Product__r.Name must be "TPH-MFG-ENT"
                                _mfg_prod_pass = _ent_prod_name == "TPH-MFG-ENT"
                                _ent_rows.append({
                                    "#":          "—",
                                    "Validation": f"MFG Ent BaseProductName — {_ent_name}",
                                    "Details":    (f"Entitlement.Product__r.Name: {_ent_prod_name or '(blank)'} | "
                                                   f"Expected: TPH-MFG-ENT"),
                                    "Expected":   "TPH-MFG-ENT",
                                    "Actual":     _ent_prod_name or "(blank)",
                                    "Status":     "✅ PASS — Mfg Ent BaseProductName matched" if _mfg_prod_pass else "❌ FAIL — Mfg Ent BaseProductName not matched",
                                })

                    # ── Overall summary table (fills placeholder after Raw SF Data) ──────
                    _all = results + orderitem_results + _ent_rows
                    _tot_pass  = len([r for r in _all if r["Status"].startswith("✅")])
                    _tot_fail  = len([r for r in _all if r["Status"].startswith("❌")])
                    _tot_info  = len([r for r in _all if r["Status"].startswith("ℹ️")])
                    _tot_checks = _tot_pass + _tot_fail
                    with overall_summary_placeholder.container():
                        st.markdown(
                            '<div style="overflow-x:auto; border-radius:8px; box-shadow:0 4px 16px rgba(0,0,0,0.3); margin-bottom:1rem; background:#0d1b2a;">'
                            '<table style="width:100%; border-collapse:collapse; font-family:Inter,sans-serif;">'
                            '<thead><tr>'
                            '<th style="padding:10px 20px; background:#1a1a2e; color:#fff; font-size:0.8rem; text-transform:uppercase; letter-spacing:0.5px; text-align:center;">Total Checks</th>'
                            '<th style="padding:10px 20px; background:#1a1a2e; color:#fff; font-size:0.8rem; text-transform:uppercase; letter-spacing:0.5px; text-align:center;">Passed ✅</th>'
                            '<th style="padding:10px 20px; background:#1a1a2e; color:#fff; font-size:0.8rem; text-transform:uppercase; letter-spacing:0.5px; text-align:center;">Failed ❌</th>'
                            '<th style="padding:10px 20px; background:#1a1a2e; color:#fff; font-size:0.8rem; text-transform:uppercase; letter-spacing:0.5px; text-align:center;">Info ℹ️</th>'
                            '</tr></thead>'
                            '<tbody><tr>'
                            f'<td style="padding:14px 20px; text-align:center; font-size:1.6rem; font-weight:700; color:#ffffff; border-bottom:1px solid rgba(255,255,255,0.1);">{_tot_checks}</td>'
                            f'<td style="padding:14px 20px; text-align:center; font-size:1.6rem; font-weight:700; color:#00b894; border-bottom:1px solid rgba(255,255,255,0.1);">{_tot_pass}</td>'
                            f'<td style="padding:14px 20px; text-align:center; font-size:1.6rem; font-weight:700; color:#d63031; border-bottom:1px solid rgba(255,255,255,0.1);">{_tot_fail}</td>'
                            f'<td style="padding:14px 20px; text-align:center; font-size:1.6rem; font-weight:700; color:#0984e3; border-bottom:1px solid rgba(255,255,255,0.1);">{_tot_info}</td>'
                            '</tr></tbody>'
                            '</table></div>',
                            unsafe_allow_html=True,
                        )
                        # Feature #1 — Consolidated detail table of all non-info checks
                        _all_checks = []
                        for _row in results:
                            if _row["Status"].startswith("ℹ️"): continue
                            _all_checks.append({"#": _row["#"], "Validation": _row["Validation"], "Status": _row["Status"], "Actual": _row.get("Actual", "")})
                        for _row in orderitem_results:
                            if _row["Status"].startswith("ℹ️"): continue
                            _all_checks.append({"#": "OI", "Validation": _row["Validation"], "Status": _row["Status"], "Actual": _row.get("Actual", "")})
                        if _all_checks:
                            st.dataframe(
                                pd.DataFrame(_all_checks),
                                use_container_width=True,
                                hide_index=True,
                            )

                    # ── Display results ────────────────────────────────────────────────
                    info_rows = [r for r in results if r["Status"].startswith("ℹ️")]
                    pass_rows = [r for r in results if r["Status"].startswith("✅")]
                    fail_rows = [r for r in results if r["Status"].startswith("❌")]

                    def renumber(rows):
                        for i, r in enumerate(rows, start=1):
                            r["#"] = str(i)
                        return rows

                    pass_rows = renumber(pass_rows)
                    fail_rows = renumber(fail_rows)

                    # Feature #8 — Skip specific checks
                    if _skipped_check_nums:
                        fail_rows = [r for r in fail_rows if r["#"] not in _skipped_check_nums]

                    # Known-issues suppression — split before any display or counting
                    _ki = st.session_state.known_issues
                    _hdr_suppressed = [r for r in fail_rows if r["Validation"] in _ki]
                    fail_rows       = [r for r in fail_rows if r["Validation"] not in _ki]

                    # Pin Order Type Classification → Process Type to top of Order Details
                    _pinned   = ("Order Type Classification", "Process Type")
                    info_rows = (
                        [r for r in info_rows if r["Validation"] == "Order Type Classification"] +
                        [r for r in info_rows if r["Validation"] == "Process Type"] +
                        [r for r in info_rows if r["Validation"] not in _pinned]
                    )
                    info_rows = renumber(info_rows)

                    if scope_header:
                        st.markdown("---")

                        st.markdown("### 🔵 Order Header Validations")
                        _metrics_rows    = [r for r in info_rows if r["Validation"].startswith("Metrics —")]
                        _non_metrics_rows = [r for r in info_rows if not r["Validation"].startswith("Metrics —")]

                        with st.expander(f"{len(_non_metrics_rows)} row(s)", expanded=True):
                            if _non_metrics_rows:
                                render_table(pd.DataFrame(_non_metrics_rows))
                            else:
                                st.caption("No info rows.")

                        if _metrics_rows:
                            with st.expander(f"Order Success Metrics — {len(_metrics_rows)} field(s)", expanded=False):
                                render_table(pd.DataFrame(_metrics_rows))

                        # Summary metric cards — shown after Order Header Validations
                        st.markdown(f"""
                        <div style="display:flex; gap:1rem; margin-bottom:1.2rem;">
                            <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                        box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0f3460;">
                                <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Total Checks</div>
                                <div style="font-size:2rem; font-weight:700; color:#1a1a2e;">{len(pass_rows) + len(fail_rows)}</div>
                            </div>
                            <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                        box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #00b894;">
                                <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Passed ✅</div>
                                <div style="font-size:2rem; font-weight:700; color:#00b894;">{len(pass_rows)}</div>
                            </div>
                            <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                        box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #d63031;">
                                <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Failed ❌</div>
                                <div style="font-size:2rem; font-weight:700; color:#d63031;">{len(fail_rows)}</div>
                            </div>
                            <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                        box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0984e3;">
                                <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Info ℹ️</div>
                                <div style="font-size:2rem; font-weight:700; color:#0984e3;">{len(info_rows)}</div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        with st.expander(f"✅ Passed — {len(pass_rows)} validation(s)", expanded=True):
                            if pass_rows:
                                render_table(pd.DataFrame(pass_rows))
                            else:
                                st.caption("No validations passed.")

                        with st.expander(f"❌ Failed — {len(fail_rows)} validation(s)", expanded=True):
                            if fail_rows:
                                render_table(pd.DataFrame(fail_rows))
                                _copy_buttons_html(fail_rows)
                                _jira_cfg = load_jira_config()
                                if _jira_cfg.get("token"):
                                    st.markdown("**Create JIRA tickets for failures:**")
                                    for _ji, _jr in enumerate(fail_rows):
                                        if st.button(f"🐛 {_jr['Validation']}", key=f"jira_hdr_{order_num}_{_ji}"):
                                            try:
                                                _jira_priority = "High" if _jr["Validation"] in ("CESD (Current Est Ship Date)", "Booking Status", "EDD (Est Delivery Date)") else "Medium"
                                                _jk, _ju = create_jira_issue(
                                                    _jira_cfg, _jira_cfg.get("project", "SPARK"),
                                                    f"[Order {order_num}] {_jr['Validation']} — {st.session_state.get('sf_env','QA')}",
                                                    f"Order: {order_num}\nEnvironment: {st.session_state.get('sf_env','QA')}\nValidation: {_jr['Validation']}\nExpected: {_jr.get('Expected','')}\nActual: {_jr.get('Actual','')}\nDetails: {_jr.get('Details','')}\nStatus: {_jr['Status']}",
                                                    priority=_jira_priority,
                                                    labels=["QA-Auto", "OrderValidation", st.session_state.get("sf_env", "QA")],
                                                    components=[_jira_cfg.get("component", "")] if _jira_cfg.get("component") else None,
                                                )
                                                st.success(f"Created [{_jk}]({_ju})")
                                            except Exception as _je:
                                                st.error(f"JIRA error: {_je}")
                            else:
                                st.success("All validations passed — no failures.")
                        if _hdr_suppressed:
                            with st.expander(f"⚠️ Suppressed (Known Issues) — {len(_hdr_suppressed)}", expanded=False):
                                for _sr in _hdr_suppressed:
                                    _ki_info = _ki.get(_sr["Validation"], {})
                                    st.markdown(f"⚠️ **{_sr['Validation']}** — Known Issue `{_ki_info.get('jira_key','(no ticket)')}`  \n_{_ki_info.get('note','')}_")
                        if fail_rows:
                            with st.expander("➕ Suppress a validation (mark as Known Issue)", expanded=False):
                                with st.form(f"suppress_hdr_{order_num}"):
                                    _s_val  = st.selectbox("Validation check", options=[r["Validation"] for r in fail_rows])
                                    _s_jira = st.text_input("JIRA key (e.g. SPARK-1234)")
                                    _s_note = st.text_input("Note (optional)")
                                    if st.form_submit_button("Mark as Known Issue"):
                                        st.session_state.known_issues[_s_val] = {
                                            "jira_key": _s_jira, "note": _s_note, "added": str(datetime.now().date())
                                        }
                                        save_known_issues(st.session_state.known_issues)
                                        st.success(f"Marked '{_s_val}' as known issue.")
                                        st.rerun()

                    oi_fail_rows = []; oi_pass_rows = []; oi_info_rows = []; _oi_suppressed = []

                    if scope_items:
                        # ── OrderItem Validations ──────────────────────────────────────────
                        st.markdown("---")
                        st.markdown("### 📦 OrderItem Validations")

                        oi_info_rows = renumber([r for r in orderitem_results if r["Status"].startswith("ℹ️")])
                        oi_pass_rows = renumber([r for r in orderitem_results if r["Status"].startswith("✅")])
                        oi_fail_rows = renumber([r for r in orderitem_results if r["Status"].startswith("❌")])

                        # Feature #8 — Skip specific checks (OI)
                        if _skipped_check_nums:
                            oi_fail_rows = [r for r in oi_fail_rows if r["#"] not in _skipped_check_nums]

                        _oi_suppressed = [r for r in oi_fail_rows if r["Validation"] in _ki]
                        oi_fail_rows   = [r for r in oi_fail_rows if r["Validation"] not in _ki]

                        st.markdown(f"""
                        <div style="display:flex; gap:1rem; margin-bottom:1.2rem;">
                            <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                        box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0f3460;">
                                <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Total Checks</div>
                                <div style="font-size:2rem; font-weight:700; color:#1a1a2e;">{len(oi_pass_rows) + len(oi_fail_rows)}</div>
                            </div>
                            <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                        box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #00b894;">
                                <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Passed ✅</div>
                                <div style="font-size:2rem; font-weight:700; color:#00b894;">{len(oi_pass_rows)}</div>
                            </div>
                            <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                        box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #d63031;">
                                <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Failed ❌</div>
                                <div style="font-size:2rem; font-weight:700; color:#d63031;">{len(oi_fail_rows)}</div>
                            </div>
                            <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                        box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0984e3;">
                                <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Info ℹ️</div>
                                <div style="font-size:2rem; font-weight:700; color:#0984e3;">{len(oi_info_rows)}</div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        if oi_info_rows:
                            st.markdown("#### 🔵 OrderItem Details")
                            render_table(pd.DataFrame(oi_info_rows))

                        with st.expander(f"✅ Passed — {len(oi_pass_rows)} validation(s)", expanded=True):
                            if oi_pass_rows:
                                render_oi_rows(oi_pass_rows)
                            else:
                                st.caption("No OrderItem validations passed.")

                        with st.expander(f"❌ Failed — {len(oi_fail_rows)} validation(s)", expanded=True):
                            if oi_fail_rows:
                                render_oi_rows(oi_fail_rows)
                                _copy_buttons_html(oi_fail_rows)
                                _jira_cfg_oi = load_jira_config()
                                if _jira_cfg_oi.get("token"):
                                    st.markdown("**Create JIRA tickets for failures:**")
                                    for _ji, _jr in enumerate(oi_fail_rows):
                                        if st.button(f"🐛 {_jr['Validation']}", key=f"jira_oi_{order_num}_{_ji}"):
                                            try:
                                                _jk, _ju = create_jira_issue(
                                                    _jira_cfg_oi, _jira_cfg_oi.get("project", "SPARK"),
                                                    f"[Order {order_num}] OI: {_jr['Validation']} — {st.session_state.get('sf_env','QA')}",
                                                    f"Order: {order_num}\nEnvironment: {st.session_state.get('sf_env','QA')}\nSection: OrderItem\nValidation: {_jr['Validation']}\nProduct: {_jr.get('Product','')}\nStatus: {_jr['Status']}",
                                                    priority="Medium",
                                                    labels=["QA-Auto", "OrderValidation", st.session_state.get("sf_env", "QA")],
                                                    components=[_jira_cfg_oi.get("component", "")] if _jira_cfg_oi.get("component") else None,
                                                )
                                                st.success(f"Created [{_jk}]({_ju})")
                                            except Exception as _je:
                                                st.error(f"JIRA error: {_je}")
                            else:
                                st.success("All OrderItem validations passed — no failures.")
                        if _oi_suppressed:
                            with st.expander(f"⚠️ Suppressed (Known Issues) — {len(_oi_suppressed)}", expanded=False):
                                for _sr in _oi_suppressed:
                                    _ki_info = _ki.get(_sr["Validation"], {})
                                    st.markdown(f"⚠️ **{_sr['Validation']}** — Known Issue `{_ki_info.get('jira_key','(no ticket)')}`  \n_{_ki_info.get('note','')}_")
                        if oi_fail_rows:
                            with st.expander("➕ Suppress a validation (mark as Known Issue)", expanded=False):
                                with st.form(f"suppress_oi_{order_num}"):
                                    _s_val  = st.selectbox("Validation check", options=[r["Validation"] for r in oi_fail_rows])
                                    _s_jira = st.text_input("JIRA key (e.g. SPARK-1234)")
                                    _s_note = st.text_input("Note (optional)")
                                    if st.form_submit_button("Mark as Known Issue"):
                                        st.session_state.known_issues[_s_val] = {
                                            "jira_key": _s_jira, "note": _s_note, "added": str(datetime.now().date())
                                        }
                                        save_known_issues(st.session_state.known_issues)
                                        st.success(f"Marked '{_s_val}' as known issue.")
                                        st.rerun()

                    if scope_ent:
                        # ── Entitlement Validations ────────────────────────────────────────
                        st.markdown("---")
                        st.markdown("### 📋 Entitlement Validations")

                        # _ent_rows and _ent_records were already built before _all (above).
                        # Debug expander — shows raw records returned by the entitlement query so
                        # mismatched Type strings or missing records can be spotted immediately.
                        with st.expander(f"🔍 Raw Entitlement Data — {len(_ent_records)} record(s) returned", expanded=False):
                            if _ent_records:
                                _raw_ent_rows = []
                                for _r in _ent_records:
                                    _osi = _r.get("Order_Service_Item__r") or {}
                                    _raw_ent_rows.append({
                                        "Name":                    _r.get("Name") or "(blank)",
                                        "Type":                    _r.get("Type") or "(blank)",
                                        "SubType__c":              _r.get("SubType__c") or "(blank)",
                                        "Product__r.Name":         (_r.get("Product__r") or {}).get("Name") or "(blank)",
                                        "Printable_Product__c":    _osi.get("Printable_Product__c") or "(blank)",
                                        "Subscription_Term__c":    str(_r.get("Subscription_Term__c") or "(blank)"),
                                        "Quantity__c":             str(_r.get("Quantity__c") or "(blank)"),
                                        "Order_Quantity__c":       str(_r.get("Order_Quantity__c") or "(blank)"),
                                    })
                                st.dataframe(pd.DataFrame(_raw_ent_rows), use_container_width=True)
                            else:
                                st.info("No entitlement records returned by the query. The WHERE clause "
                                        "`Order_Service_Item__r.Order.Order_Number__c` may not match "
                                        "Manufacturing Entitlements if they use a different relationship.")

                        if order_sub_type == "GC Offer":
                            st.info("Entitlement validations are not applicable for GC Offer orders.")
                        elif _ent_rows:
                            _ent_rows_disp   = renumber(list(_ent_rows))
                            _ent_fail_actual = [r for r in _ent_rows_disp if r["Status"].startswith("❌") and r["Validation"] not in _ki]
                            _ent_suppressed  = [r for r in _ent_rows_disp if r["Status"].startswith("❌") and r["Validation"] in _ki]
                            _ent_pass  = sum(1 for r in _ent_rows_disp if r["Status"].startswith("✅"))
                            _ent_fail  = len(_ent_fail_actual)
                            _ent_info  = sum(1 for r in _ent_rows_disp if r["Status"].startswith("ℹ️"))
                            _ent_total = _ent_pass + _ent_fail
                            st.markdown(f"""
                            <div style="display:flex; gap:1rem; margin-bottom:1.2rem;">
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0f3460;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Total Checks</div>
                                    <div style="font-size:2rem; font-weight:700; color:#1a1a2e;">{_ent_total}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #00b894;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Passed ✅</div>
                                    <div style="font-size:2rem; font-weight:700; color:#00b894;">{_ent_pass}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #d63031;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Failed ❌</div>
                                    <div style="font-size:2rem; font-weight:700; color:#d63031;">{_ent_fail}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0984e3;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Info ℹ️</div>
                                    <div style="font-size:2rem; font-weight:700; color:#0984e3;">{_ent_info}</div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                            with st.expander(f"✅ Passed — {_ent_pass} validation(s)", expanded=True):
                                _pass_rows = [r for r in _ent_rows_disp if r["Status"].startswith("✅")]
                                if _pass_rows:
                                    render_ent_rows(_pass_rows)
                                else:
                                    st.caption("No entitlement validations passed.")
                            with st.expander(f"❌ Failed — {_ent_fail} validation(s)", expanded=True):
                                if _ent_fail_actual:
                                    render_ent_rows(_ent_fail_actual)
                                    _copy_buttons_html(_ent_fail_actual)
                                    _jira_cfg_ent = load_jira_config()
                                    if _jira_cfg_ent.get("token"):
                                        st.markdown("**Create JIRA tickets for failures:**")
                                        for _ji, _jr in enumerate(_ent_fail_actual):
                                            if st.button(f"🐛 {_jr['Validation']}", key=f"jira_ent_{order_num}_{_ji}"):
                                                try:
                                                    _jk, _ju = create_jira_issue(
                                                        _jira_cfg_ent, _jira_cfg_ent.get("project", "SPARK"),
                                                        f"[Order {order_num}] Ent: {_jr['Validation']} — {st.session_state.get('sf_env','QA')}",
                                                        f"Order: {order_num}\nEnvironment: {st.session_state.get('sf_env','QA')}\nSection: Entitlement\nValidation: {_jr['Validation']}\nStatus: {_jr['Status']}",
                                                        priority="Medium",
                                                        labels=["QA-Auto", "OrderValidation", st.session_state.get("sf_env", "QA")],
                                                        components=[_jira_cfg_ent.get("component", "")] if _jira_cfg_ent.get("component") else None,
                                                    )
                                                    st.success(f"Created [{_jk}]({_ju})")
                                                except Exception as _je:
                                                    st.error(f"JIRA error: {_je}")
                                else:
                                    st.success("All entitlement validations passed — no failures.")
                            if _ent_suppressed:
                                with st.expander(f"⚠️ Suppressed (Known Issues) — {len(_ent_suppressed)}", expanded=False):
                                    for _sr in _ent_suppressed:
                                        _ki_info = _ki.get(_sr["Validation"], {})
                                        st.markdown(f"⚠️ **{_sr['Validation']}** — Known Issue `{_ki_info.get('jira_key','(no ticket)')}`  \n_{_ki_info.get('note','')}_")
                            if _ent_fail_actual:
                                with st.expander("➕ Suppress a validation (mark as Known Issue)", expanded=False):
                                    with st.form(f"suppress_ent_{order_num}"):
                                        _s_val  = st.selectbox("Validation check", options=[r["Validation"] for r in _ent_fail_actual])
                                        _s_jira = st.text_input("JIRA key (e.g. SPARK-1234)")
                                        _s_note = st.text_input("Note (optional)")
                                        if st.form_submit_button("Mark as Known Issue"):
                                            st.session_state.known_issues[_s_val] = {
                                                "jira_key": _s_jira, "note": _s_note, "added": str(datetime.now().date())
                                            }
                                            save_known_issues(st.session_state.known_issues)
                                            st.success(f"Marked '{_s_val}' as known issue.")
                                            st.rerun()
                        elif _ent_records:
                            st.info("ℹ️ No entitlement records linked to this order — entitlement validations are N/A.")
                        else:
                            st.info("No entitlements found for this order.")



                    # Feature #10 — Cross-run comparison
                    _prev_runs_for_order = [
                        r for r in st.session_state.run_history
                        if order_num in r.get("orders", []) and r.get("id") != _current_run_id
                    ]
                    if _prev_runs_for_order:
                        _prev_run_cmp = _prev_runs_for_order[-1]
                        _prev_fails_for_order = _prev_run_cmp.get("order_fails", {}).get(order_num, [])
                        _cur_fails_for_order  = st.session_state.get(f"_cur_fails_{order_num}", [])
                        _newly_failing = [v for v in _cur_fails_for_order if v not in _prev_fails_for_order]
                        _newly_passing = [v for v in _prev_fails_for_order if v not in _cur_fails_for_order]
                        if _newly_failing or _newly_passing:
                            with st.expander(f"🔄 Compare with previous run ({_prev_run_cmp['timestamp'][:16]})", expanded=False):
                                if _newly_failing:
                                    st.error(f"**Newly failing** (regressions): {', '.join(_newly_failing)}")
                                if _newly_passing:
                                    st.success(f"**Newly passing** (fixed): {', '.join(_newly_passing)}")

                    # ── Cross-order failures + grand totals ───────────────────────────
                    for _r in fail_rows:
                        cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "Order Header"})
                    for _r in oi_fail_rows:
                        cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "OrderItem"})
                    for _r in _ent_rows:
                        if _r["Status"].startswith("❌") and _r["Validation"] not in _ki:
                            cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "Entitlement"})
                    _order_pass   = len(pass_rows) + len(oi_pass_rows)
                    _order_fail   = len(fail_rows) + len(oi_fail_rows)
                    _order_total  = _order_pass + _order_fail
                    _grand_total  += _order_total
                    _grand_passed += _order_pass
                    _grand_failed += _order_fail

                    # Feature #2 — Store health data per order
                    st.session_state.last_order_health[order_num] = {
                        "pass":  _order_pass,
                        "fail":  _order_fail,
                        "total": _order_total,
                    }

                    # Feature #10 — Store current fails per order for cross-run comparison
                    st.session_state[f"_cur_fails_{order_num}"] = [r["Validation"] for r in fail_rows + oi_fail_rows]

                    # ── Accumulate download data for this order ────────────────────────
                    prefix = f"{order_num} ({_env_label}) — " if compare_mode else f"{order_num} — "
                    if info_rows:    all_dl_sections[f"{prefix}Details"]   = pd.DataFrame(info_rows)
                    if pass_rows:    all_dl_sections[f"{prefix}Passed"]    = pd.DataFrame(pass_rows)
                    if fail_rows:    all_dl_sections[f"{prefix}Failed"]    = pd.DataFrame(fail_rows)
                    if oi_pass_rows: all_dl_sections[f"{prefix}OI Pass"]   = pd.DataFrame(oi_pass_rows)
                    if oi_fail_rows: all_dl_sections[f"{prefix}OI Fail"]   = pd.DataFrame(oi_fail_rows)

    # ── Post-loop: Run history + Cross-order summary ──────────────────────────
    if order_nums:
        _run_record = {
            "id":        _current_run_id,
            "timestamp": datetime.now().isoformat(),
            "env":       st.session_state.get("sf_env", "QA"),
            "orders":    order_nums,
            "total":     _grand_total,
            "passed":    _grand_passed,
            "failed":    _grand_failed,
            "order_fails": {on: st.session_state.get(f"_cur_fails_{on}", []) for on in order_nums},
        }
        append_history(_run_record)
        st.session_state.run_history = load_history()

    if len(order_nums) > 1 and cross_order_failures:
        st.markdown("---")
        st.markdown("## 📊 Cross-Order Failure Summary")
        _cof_df = pd.DataFrame(cross_order_failures)
        _pivot  = _cof_df.groupby("Validation")["Order"].apply(list).reset_index()
        _pivot.columns = ["Validation Check", "Failed On Orders"]
        _pivot["Failure Count"]    = _pivot["Failed On Orders"].apply(len)
        _pivot["Failed On Orders"] = _pivot["Failed On Orders"].apply(lambda x: ", ".join(x))
        _pivot = _pivot.sort_values("Failure Count", ascending=False).reset_index(drop=True)
        st.dataframe(_pivot, use_container_width=True)
        all_dl_sections["Cross-Order Summary"] = _pivot

    # ── Download Section (outside the per-order loop) ─────────────────────────
    if all_dl_sections:
        st.markdown("---")
        st.markdown("""
        <div style="background:#fff; border-radius:12px; padding:1.2rem 1.5rem;
                    box-shadow:0 2px 10px rgba(0,0,0,0.08); border-top:3px solid #0f3460;
                    margin-bottom:1rem;">
            <p style="margin:0 0 0.3rem; font-weight:700; color:#1a1a2e; font-size:1.05rem;">
                ⬇️ Download Validation Results
            </p>
            <p style="margin:0; color:#5a6a7a; font-size:0.85rem;">
                Select a format to download all validation sections as a single file.
            </p>
        </div>
        """, unsafe_allow_html=True)

        # Build CSV
        csv_buf = io.StringIO()
        for section, df in all_dl_sections.items():
            csv_buf.write(f"=== {section} ===\n")
            df.to_csv(csv_buf, index=False)
            csv_buf.write("\n")
        csv_data = csv_buf.getvalue()

        # Build Excel
        excel_buf = io.BytesIO()
        with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
            for section, df in all_dl_sections.items():
                sheet_name = section[:31]
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                ws = writer.sheets[sheet_name]
                for col_cells in ws.columns:
                    max_len = max((len(str(c.value)) for c in col_cells if c.value), default=10)
                    ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 60)
        excel_data = excel_buf.getvalue()

        fname = "order_validation_" + "_".join(order_nums)
        html_report = generate_html_report(
            order_nums, all_dl_sections,
            st.session_state.get("sf_env", "QA"),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            _grand_total, _grand_passed, _grand_failed,
        )
        dl_col1, dl_col2, dl_col3, _ = st.columns([1, 1, 1, 3])
        with dl_col1:
            st.download_button("📥 Download CSV",   data=csv_data,   file_name=f"{fname}.csv",  mime="text/csv",                                                                             use_container_width=True)
        with dl_col2:
            st.download_button("📊 Download Excel", data=excel_data, file_name=f"{fname}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        with dl_col3:
            st.download_button("🌐 Download HTML",  data=html_report, file_name=f"{fname}.html", mime="text/html", use_container_width=True)
