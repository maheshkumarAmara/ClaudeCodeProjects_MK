import streamlit as st
import json
import io
import concurrent.futures
from datetime import datetime
import pandas as pd

from theme import apply_theme

from ov.booking_compare import (
    bk_compare_bli,
    bk_compare_booking_header,
    bk_fetch_booking_data,
    bk_rows_to_app_rows,
    bk_safe_float,
    bk_soql_in,
)
from ov.calc import add_days, add_months, compute_expected_metrics, end_of_month, fmt_amount, parse_date
from ov.parsing import _clean_sf, _parse_csv_upload, _parse_order_text
from ov.report import generate_html_report
from ov.sf_client import _prefetch_order_data, run_sf_query, verify_sf_org
from ov.storage import (
    MATRIX_FILE,
    _DEFAULT_MATRIX_ROWS,
    _load_fulfillment_matrix,
    append_history,
    load_history,
)


st.set_page_config(page_title="Order Validation · Rubrik", page_icon="📋", layout="wide")

# ── CSS styles ────────────────────────────────────────────────────────────────
apply_theme("main")

# ── App header ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="app-header">
    <div class="app-header-icon">📋</div>
    <div class="app-header-text">
        <h1>Order Validation App</h1>
        <p>Real-time Salesforce order validation against business rules &nbsp;·&nbsp; Rubrik ProdOps</p>
    </div>
    <div class="app-header-tags">
        <span class="app-tag">⚡ Salesforce CLI</span>
        <span class="app-tag">📦 Multi-Order</span>
        <span class="app-tag">🔒 QA &amp; UAT</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Org config ────────────────────────────────────────────────────────────────
ORG_CONFIG = {
    "QA":  {"alias": "qa-org",  "login_url": "https://rubrikinc--rbkqa.sandbox.my.salesforce.com",             "label": "QA Sandbox"},
    "UAT": {"alias": "uat-org", "login_url": "https://rubrikinc--rbkuat.sandbox.my.salesforce.com",            "label": "UAT Sandbox"},
}

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
        <div class="sidebar-brand-title">📋 Order Validation</div>
        <div class="sidebar-brand-sub">Rubrik ProdOps · Salesforce CLI</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section-label">Salesforce Connection</div>', unsafe_allow_html=True)

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
if "sf_connected"      not in st.session_state: st.session_state.sf_connected      = False
if "sf_username"       not in st.session_state: st.session_state.sf_username       = ""
if "sf_alias"          not in st.session_state: st.session_state.sf_alias          = ""
if "auto_target_date_org" not in st.session_state: st.session_state.auto_target_date_org = ""
if "target_date_input" not in st.session_state: st.session_state.target_date_input = None
if "run_history"       not in st.session_state: st.session_state.run_history       = load_history()
if "last_run_orders"   not in st.session_state: st.session_state.last_run_orders   = []
if "last_order_health" not in st.session_state: st.session_state.last_order_health = {}
# ── Helpers ───────────────────────────────────────────────────────────────────


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

# ── Auto-fetch Target Date from Order_Configuration__c ───────────────────────
if (st.session_state.sf_connected
        and st.session_state.sf_alias != st.session_state.auto_target_date_org):
    try:
        _oc_res = run_sf_query(
            st.session_state.sf_alias,
            "SELECT Id, End_Date__c, Target_Date__c FROM Order_Configuration__c "
            "WHERE End_Date__c > TODAY ORDER BY End_Date__c ASC LIMIT 1"
        )
        _oc_recs = _oc_res.get("records", [])
        if _oc_recs and _oc_recs[0].get("Target_Date__c"):
            import datetime as _dt
            st.session_state.target_date_input = _dt.date.fromisoformat(
                _oc_recs[0]["Target_Date__c"][:10]
            )
        else:
            st.session_state.target_date_input = None
    except Exception:
        st.session_state.target_date_input = None
    st.session_state.auto_target_date_org = st.session_state.sf_alias

# ── Validation Scope ──────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.markdown('<div class="sidebar-section-label">Validation Scope</div>', unsafe_allow_html=True)
scope_quote_header          = st.sidebar.checkbox("Quote Header",          value=True, key="scope_quote_header")
scope_quote_lines           = st.sidebar.checkbox("QuoteLines",            value=True, key="scope_quote_lines")
scope_opportunity_header    = st.sidebar.checkbox("Opportunity Header",    value=True, key="scope_opportunity_header")
scope_opportunity_lineitems = st.sidebar.checkbox("Opportunity Lineitems", value=True, key="scope_opportunity_lineitems")
scope_header = st.sidebar.checkbox("Order Header",  value=True, key="scope_header")
scope_items  = st.sidebar.checkbox("OrderItem",     value=True, key="scope_items")
scope_booking_header     = st.sidebar.checkbox("Booking Header",     value=True, key="scope_booking_header")
scope_booking_lineitems  = st.sidebar.checkbox("Booking Lineitems",  value=True, key="scope_booking_lineitems")
scope_contract_lineitems = st.sidebar.checkbox("Contract Lineitems", value=True, key="scope_contract_lineitems")
scope_ent         = st.sidebar.checkbox("Entitlements",      value=True, key="scope_ent")
scope_linked_assets      = st.sidebar.checkbox("LinkedAssets",       value=True, key="scope_linked_assets")

# ── Scenario Matrix ───────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.markdown('<div class="sidebar-section-label">Scenario Matrix</div>', unsafe_allow_html=True)

_matrix_source_label = "📂 Custom (uploaded)" if MATRIX_FILE.exists() else "📌 Default (built-in)"
st.sidebar.caption(_matrix_source_label)

_MATRIX_REQUIRED_COLS = {
    "Scenario Key", "Booking Bucket", "Fulfillment Date",
    "Support Start", "Support End", "New Ent Start",
    "New Ent End", "Old Ent Termination",
}

_uploaded_matrix_file = st.sidebar.file_uploader(
    "Replace matrix (.xlsx)",
    type=["xlsx"],
    key="matrix_upload",
    help=(
        "Upload an Excel file to update the fulfillment scenario matrix.\n"
        "Required columns: " + ", ".join(sorted(_MATRIX_REQUIRED_COLS))
    ),
)
if _uploaded_matrix_file is not None:
    try:
        _mdf = pd.read_excel(_uploaded_matrix_file, engine="openpyxl")
        _missing_cols = _MATRIX_REQUIRED_COLS - set(_mdf.columns)
        if _missing_cols:
            st.sidebar.error(f"Missing columns: {', '.join(sorted(_missing_cols))}")
        else:
            _new_rows = _mdf[sorted(_MATRIX_REQUIRED_COLS)].to_dict("records")
            MATRIX_FILE.write_text(json.dumps(_new_rows, indent=2))
            st.sidebar.success(f"✅ Matrix saved — {len(_new_rows)} rows loaded")
            st.rerun()
    except Exception as _exc:
        st.sidebar.error(f"Parse error: {_exc}")

_tmpl_buf = io.BytesIO()
pd.DataFrame(_DEFAULT_MATRIX_ROWS).to_excel(_tmpl_buf, index=False, engine="openpyxl")
_tmpl_buf.seek(0)
st.sidebar.download_button(
    "⬇️ Download Template",
    data=_tmpl_buf,
    file_name="fulfillment_matrix_template.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)
if MATRIX_FILE.exists():
    if st.sidebar.button("🔄 Reset to Default", use_container_width=True, key="matrix_reset"):
        MATRIX_FILE.unlink()
        st.rerun()

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

def _skip_select_all():
    for _n, _ in _SKIPPABLE_VALIDATIONS:
        st.session_state[f"skip_v_{_n}"] = True

def _skip_deselect_all():
    for _n, _ in _SKIPPABLE_VALIDATIONS:
        st.session_state[f"skip_v_{_n}"] = False

with st.sidebar.expander("🔬 Skip Specific Checks"):
    _sc1, _sc2 = st.columns(2)
    _sc1.button("✅ Select All",   on_click=_skip_select_all,   use_container_width=True, key="skip_all_btn")
    _sc2.button("❌ Deselect All", on_click=_skip_deselect_all, use_container_width=True, key="skip_none_btn")
    st.markdown("---")
    for _sv_num, _sv_name in _SKIPPABLE_VALIDATIONS:
        st.checkbox(f"#{_sv_num} — {_sv_name}", key=f"skip_v_{_sv_num}")

_skipped_check_nums = {num for num, _ in _SKIPPABLE_VALIDATIONS
                       if st.session_state.get(f"skip_v_{num}", False)}

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
    _collapsible = ("Product Name Match", "Payment Options Match", "Subscription Term Match", "Support Start Date", "Support End Date", "UnitPrice × Quantity", "SerialNumber vs Quantity", "Segment Label", "Quarter", "Upgraded From", "MSP Pay Go Fulfillment")
    pn_rows    = [r for r in rows if r["Validation"].startswith("Product Name Match")]
    po_rows    = [r for r in rows if r["Validation"].startswith("Payment Options Match")]
    st_rows    = [r for r in rows if r["Validation"].startswith("Subscription Term Match")]
    ss_rows    = [r for r in rows if r["Validation"].startswith("Support Start Date")]
    se_rows    = [r for r in rows if r["Validation"].startswith("Support End Date")]
    tp_rows    = [r for r in rows if r["Validation"].startswith("UnitPrice × Quantity")]
    sn_rows    = [r for r in rows if r["Validation"].startswith("SerialNumber vs Quantity")]
    sl_rows    = [r for r in rows if r["Validation"].startswith("Segment Label")]
    qtr_rows   = [r for r in rows if r["Validation"].startswith("Quarter")]
    uf_rows    = [r for r in rows if r["Validation"].startswith("Upgraded From")]
    pg_rows    = [r for r in rows if r["Validation"].startswith("MSP Pay Go Fulfillment")]
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

    if uf_rows:
        uf_pass = sum(1 for r in uf_rows if "✅" in r["Status"])
        uf_fail = sum(1 for r in uf_rows if "❌" in r["Status"])
        badge = (f" · ✅ {uf_pass} passed" if uf_pass else "") + (f" · ❌ {uf_fail} failed" if uf_fail else "")
        with st.expander(f"Upgraded From (Replaced From) — {len(uf_rows)} line item(s){badge}", expanded=False):
            render_table(pd.DataFrame(uf_rows))

    if pg_rows:
        pg_pass = sum(1 for r in pg_rows if "✅" in r["Status"])
        pg_fail = sum(1 for r in pg_rows if "❌" in r["Status"])
        badge = (f" · ✅ {pg_pass} passed" if pg_pass else "") + (f" · ❌ {pg_fail} failed" if pg_fail else "")
        with st.expander(f"MSP Pay Go Fulfillment — {len(pg_rows)} line item(s){badge}", expanded=False):
            render_table(pd.DataFrame(pg_rows))

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

# ── Helper: Scale_Entitlement__c (LinkedAssets) rows grouped by validation type ──
def render_linked_asset_rows(rows):
    _groups = [
        ("Asset Presence",             "Asset Presence"),
        ("Order Product Presence",     "Order Product Presence"),
        ("Entitlement Type",           "Entitlement Type"),
        ("Contract Line Item Match",   "Contract Line Item Match"),
        ("Type Sub-Type",              "Type Sub-Type"),
        ("RequiredByLineItem Sync",    "RequiredByLineItem Sync"),
        ("Renewal Category",           "Renewal Category"),
        ("Status",                     "Status"),
    ]
    for prefix, label in _groups:
        grp = [r for r in rows if r["Validation"].startswith(prefix)]
        if not grp:
            continue
        grp_pass = sum(1 for r in grp if "✅" in r["Status"])
        grp_fail = sum(1 for r in grp if "❌" in r["Status"])
        badge = (f" · ✅ {grp_pass} passed" if grp_pass else "") + (f" · ❌ {grp_fail} failed" if grp_fail else "")
        with st.expander(f"{label} — {len(grp)} record(s){badge}", expanded=False):
            render_table(pd.DataFrame(grp))

# ── Helper: ContractLineItem rows grouped by validation type ──
def render_contract_lineitem_rows(rows):
    _groups = [
        ("Order Product Link",    "Order Product Link"),
        ("Service Contract Link", "Service Contract Link"),
        ("Quantity Match",        "Quantity Match"),
        ("Product Match",         "Product Match"),
        ("Start Date Match",      "Start Date Match"),
        ("End Date Match",        "End Date Match"),
        ("TPH Fields Sync",             "TPH Fields Sync"),
        ("POT Parent Source Match",     "POT Parent Source Match"),
        ("POT Parent List Price Match", "POT Parent List Price Match"),
        ("AMER FED Exception Match",    "AMER FED Exception Match"),
        ("Max Commit Consistency",      "Max Commit Consistency"),
        ("Resync Flag",                 "Resync Flag"),
    ]
    for prefix, label in _groups:
        grp = [r for r in rows if r["Validation"].startswith(prefix)]
        if not grp:
            continue
        grp_pass = sum(1 for r in grp if "✅" in r["Status"])
        grp_fail = sum(1 for r in grp if "❌" in r["Status"])
        badge = (f" · ✅ {grp_pass} passed" if grp_pass else "") + (f" · ❌ {grp_fail} failed" if grp_fail else "")
        with st.expander(f"{label} — {len(grp)} lineitem(s){badge}", expanded=False):
            render_table(pd.DataFrame(grp))

# ── Helper: QuoteLine rows grouped by validation type ──────────────────────
def render_quote_line_rows(rows):
    _groups = [
        ("Term-Price Consistency",    "Term-Price Consistency (Fixed Price)"),
        ("Additional Discount Formula", "Additional Discount Formula"),
        ("Net vs Regular Price Sanity", "Net vs Regular Price Sanity"),
        ("Discount % Consistency",      "Discount % Consistency"),
    ]
    for prefix, label in _groups:
        grp = [r for r in rows if r["Validation"].startswith(prefix)]
        if not grp:
            continue
        grp_pass = sum(1 for r in grp if "✅" in r["Status"])
        grp_fail = sum(1 for r in grp if "❌" in r["Status"])
        badge = (f" · ✅ {grp_pass} passed" if grp_pass else "") + (f" · ❌ {grp_fail} failed" if grp_fail else "")
        with st.expander(f"{label} — {len(grp)} line(s){badge}", expanded=False):
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

# ── Booking Header / Booking Lineitems — ported from Bookings-metrics-comparision skill ────


# ── Main input area ───────────────────────────────────────────────────────────


col_on, col_td = st.columns([3, 1])
with col_on:
    st.markdown('<p style="font-size:0.78rem;font-weight:600;text-transform:uppercase;letter-spacing:0.6px;color:#4d7a96;margin-bottom:0.3rem;">Order Number(s)</p>', unsafe_allow_html=True)
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
    target_date = st.date_input("Target Date (optional — for Lead Time)", key="target_date_input")

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

    # ── Feature #4: Pre-fetch all orders in parallel ────────────────────────
    _pf_aliases = []
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
                    result           = _pf_data.get("result",        {"totalSize": 0, "records": []})
                    items_result     = _pf_data.get("items_result",   {"totalSize": 0, "records": []})
                    _metrics_result  = _pf_data.get("metrics_result", {"totalSize": 0, "records": []})
                    _ent_prefetched  = _pf_data.get("ent_result",     {"totalSize": 0, "records": []})
                    _scale_ent_prefetched = _pf_data.get("scale_ent_result", {"totalSize": 0, "records": []})
                    _cli_prefetched  = _pf_data.get("cli_result",     {"totalSize": 0, "records": []})
                    _history_result  = _pf_data.get("history_result", {"totalSize": 0, "records": []})
                    _sc_result       = _pf_data.get("sc_result",      {"totalSize": 0, "records": []})
                    _orderitem_gate_result = _pf_data.get("orderitem_gate_result", {"totalSize": 0, "records": []})
                    _mdt_result      = _pf_data.get("mdt_result",     {"totalSize": 0, "records": []})
                    _ql_result       = _pf_data.get("ql_result",      {"totalSize": 0, "records": []})
                    metrics_record   = _metrics_result["records"][0] if _metrics_result.get("totalSize", 0) > 0 else {}

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
                    order_contracted        = record.get("SBQQ__Contracted__c")
                    sc_or_ent_stage         = record.get("SC_or_Entitlement_Stage__c") or ""
                    sc_or_ent_stage_values  = [v.strip() for v in sc_or_ent_stage.split(";") if v.strip()]
                    sc_ent_ready            = bool(order_contracted) and "SC Creation Successful" in sc_or_ent_stage_values
                    bill_to            = record.get("Bill_To_Name__r") or {}
                    bill_to_id         = bill_to.get("Id", "")
                    bill_to_name       = bill_to.get("Name", "(unknown)")
                    sf_order_type      = record.get("Type") or ""
                    order_sub_type     = record.get("Order_Sub_Type__c") or ""
                    line_types         = record.get("Line_Types__c") or ""
                    booking_status     = record.get("BookingStatus__c") or ""
                    order_status       = record.get("Order_Status__c") or ""
                    order_account_id   = record.get("AccountId") or ""
                    order_mfg_partner  = record.get("Manufacturing_Integration_Partner__c") or ""
                    order_polaris      = record.get("Have_Polaris_Products__c")
                    opp_record         = record.get("Opportunity") or {}
                    opp_polaris        = opp_record.get("Has_Polaris_Product__c")
                    opp_recordtype_dev_name = ((opp_record.get("RecordType") or {}).get("DeveloperName") or "")
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
                    primary_contact_screen_status = record.get("Primary_Contact_Screen_Status__c") or ""
                    shipping_carrier              = record.get("Shipping_Carrier__c") or ""
                    scac                          = record.get("SCAC__c") or ""
                    smart_hands_provider          = record.get("Smart_Hands_Provider__c") or ""
                    price_calc_status             = record.get("SBQQ__PriceCalcStatus__c") or ""
                    have_hardware                 = record.get("Have_Hardware_Products__c")
                    order_split_type              = record.get("Order_Split_Type__c") or ""
                    polaris_fulfill_status        = record.get("Polaris_Fulfillment_Status__c") or ""
                    poc_completion_date           = (record.get("POC_Completion_Date__c") or "")[:10]
                    poc_type                      = record.get("POC_Type__c") or ""
                    _poc_opp                      = record.get("POC_Opportunity__r") or {}
                    _poc_distributor              = _poc_opp.get("Distributor_Lookup__r") or {}
                    poc_opp_distributor_id        = _poc_opp.get("Distributor_Lookup__c") or ""
                    poc_opp_distributor_nm        = _poc_distributor.get("Name") or ""

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

                    # ── Replacement order data ─────────────────────────────────────────
                    _replacement_items = []
                    if line_types:
                        for _ri_item in _items_recs:
                            _ptr      = _ri_item.get("Previous_Transaction_Reference__c")
                            _rtype    = _ri_item.get("Replacement_Type__c")
                            _credit   = _ri_item.get("Credit_Amount__c")
                            _prodname = _ri_item.get("Product_Name__c") or "(blank)"
                            _printprd = _ri_item.get("Printable_Product__c") or _prodname
                            if _ptr:
                                try:
                                    _ptr_list = json.loads(_ptr)
                                    if isinstance(_ptr_list, list):
                                        for _e in _ptr_list:
                                            _eid = _e.get("entId")
                                            if _eid:
                                                _replacement_items.append({
                                                    "entId":               _eid,
                                                    "Replacement_Type__c": _rtype or "(blank)",
                                                    "creditAmount":        _credit,
                                                    "printableProduct":    _printprd,
                                                    "productName":         _prodname,
                                                    "orderNumber":         _e.get("orderNumber") or "",
                                                    "orderItemId":         _e.get("orderItemId") or "",
                                                    "usedQty":             _e.get("usedEntitlementQuantity"),
                                                    "remainingQty":        _e.get("orderItemRemainingQuantity"),
                                                    "isMisMatched":        _e.get("isMisMatched"),
                                                })
                                except (json.JSONDecodeError, TypeError):
                                    pass

                    _repl_rows = []
                    _repl_ent_map = {}
                    if _replacement_items:
                        _ent_ids  = list({r["entId"] for r in _replacement_items})
                        _ids_in   = "', '".join(_ent_ids)
                        _repl_soql = (
                            f"SELECT Id, Order_Service_Item__r.Payment_Options__c "
                            f"FROM Entitlement WHERE Id IN ('{_ids_in}')"
                        )
                        try:
                            _repl_result  = run_sf_query(alias, _repl_soql)
                            _repl_ent_map = {r["Id"]: r for r in _repl_result.get("records", [])}
                        except Exception as _repl_err:
                            _repl_rows.append({
                                "#": "!", "Prev Order": "—", "Entitlement ID": "—",
                                "Replacement_Type__c": "—", "Payment_Options__c": "—",
                                "Used Qty": "—", "Remaining Qty": "—", "Is Mismatched": "—",
                                "Status": f"❌ Entitlement fetch error: {str(_repl_err)[:100]}",
                            })

                        for _ri in _replacement_items:
                            _ent_rec  = _repl_ent_map.get(_ri["entId"]) or {}
                            _osi      = (_ent_rec.get("Order_Service_Item__r") or {})
                            _pay_opt  = _osi.get("Payment_Options__c") or "(blank)"
                            _rtype    = _ri["Replacement_Type__c"]
                            _cr       = _ri["creditAmount"]

                            # ── Classify ──────────────────────────────────────────────────
                            _rtype_norm   = (_rtype or "").strip().lower()
                            _rtype_label  = ("Full"    if _rtype_norm == "full"
                                             else "Partial" if _rtype_norm == "partial"
                                             else _rtype or "(blank)")
                            _credit_label = ("Without Credits"
                                             if (_cr is None or _cr == 0)
                                             else "With Credits")
                            _pay_lower    = (_pay_opt or "").lower()
                            _pay_prefix   = ("PP" if "prepay"  in _pay_lower
                                             else "PA" if "annual" in _pay_lower
                                             else _pay_opt)
                            _credit_short = "with credit" if _credit_label == "With Credits" else "without credit"
                            _scenario     = f"{_pay_prefix} {_credit_short}"

                            _repl_rows.append({
                                "#":                   str(len(_repl_rows) + 1),
                                "Replacement Type":    _rtype_label,
                                "Scenario":            _scenario,
                                "Credit Status":       _credit_label,
                                "Printable Product":   _ri["printableProduct"],
                                "Product Name":        _ri["productName"],
                                "Payment Option":      _pay_opt,
                                "Prev Order":          _ri["orderNumber"],
                                "Entitlement ID":      _ri["entId"],
                                "Credit_Amount__c":    str(_cr) if _cr is not None else "—",
                                "Used Qty":            str(_ri["usedQty"])      if _ri["usedQty"]      is not None else "—",
                                "Remaining Qty":       str(_ri["remainingQty"]) if _ri["remainingQty"] is not None else "—",
                                "Is Mismatched":       str(_ri["isMisMatched"]),
                                "Status":              f"ℹ️ {_rtype_label} · {_scenario}",
                            })

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
        | 10 | Serial Number vs Quantity | If `Line_Types__c` is set: `SerialNumber__c == Arroyo_Subscribed_Asset_Name__c`; else Hardware: count of serial entries must equal Quantity; else Non-hardware: vs QLI Subscribed Asset Name |
        | 10a | Upgraded From (Replaced From) | If `Line_Types__c` is set: `Upgraded_From__c == SerialNumber__c` |
        | 11 | Printable Product Count | `COUNT(OrderItem.Printable_Product__c) == COUNT(Opp_Product.Printable_Product__c)` |
        | A1 | Ordered Quantity | `OrderItem.SBQQ__OrderedQuantity__c == Quantity` |
        | A2 | Actual Sales Price | `OrderItem.Actual_Sales_Price__c == QuoteLine.SBQQ__ListPrice__c` |
        | A3 | Sales Price | `OrderItem.Sales_Price__c == QuoteLine.SBQQ__CustomerPrice__c` |
        | A4 | TPH Fields (OrderItem-level) | `OrderItem.TPH_Drive_Size__c/TPH_Models_Gen__c/TPH_OEM__c == QuoteLine`'s same-named fields |
        | A5 | Entitlement Id | `OrderItem.Entitlement_Id__c == String(QuoteLine.Account_s_Entitlement__c)` when `QuoteLine.SBQQ__Product__r.Upgrade_Path__c` is set; else blank |
        | A6 | Credit Amount | `OrderItem.Credit_Amount__c == (QuoteLine.Prepayment_Credit__c / QuoteLine.SBQQ__Quantity__c) × oi.Quantity` when set; else blank |
        | A7 | Previous Contract Line (consistency) | `Previous_Contract_Line__c == first comma-token of Previous_Contract_Line_Items__c, trimmed to 15 chars` |
        | A8 | ACV Fields (Revenue orders) | `RBOB_ACV__c / Renewal_Target_Amount_ACV__c / PromoDiscTCV__c / Oppty_Trade_Up_Discount__c == Opportunity_Product__r.<field> × qtyFactor` |
        | A9 | ServiceDate / EndDate | Mirrors `Support_Start_Date__c`/`Support_End_Date__c`, except on GC Offer + Renewal Opportunity orders, where they mirror `QuoteLine.SBQQ__StartDate__c`/`SBQQ__EndDate__c` |

        **Reference Only (displayed, not asserted)** — `Buyer_Part_Number__c`, `EDI_Line_Number__c`, `Opportunity_Product__c`,
        `TPH_Quantity__c`, `Previous_Contract_Line_Items__c`, `Licence_Type__c`, `Cluster_Order_Type__c`, `Program__c`,
        `Additional_Term__c`, `Surviving_Amount__c`, `SBQQ__RequiredBy__c`, `Has_PSTask__c`, `Task_Created__c`,
        `Global_Commit_ID__c`/`Global_Commit_Split_ID__c` (OrderItem-level), `SBQQ__Contracted__c` (OrderItem-level),
        `Trade_Up_SerialNumber__c` — these depend on Custom Labels/Metadata and multi-hop relationship chains too
        fragile to hard-code as pass/fail; shown for manual review instead.
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
                            st.markdown("Applies to all order sub-types including GC Offer. "
                                        "Entitlements are filtered by `Type` before validating.")

                            st.markdown("**Phone Support (`Type = 'Phone Support'`)**")
                            st.markdown("""
        | # | Validation | Rule |
        |---|---|---|
        | 1 | SubType | `SubType__c == "Rubrik Support"` |
        | 2 | Product | `Entitlement.Name == Order_Service_Item__r.Printable_Product__c` |
        | 3 | Base Product | `Product__r.Name == Order_Service_Item__r.Product2.Name` |
        | 4 | Subscription Term | `Subscription_Term__c == Order_Service_Item__r.SBQQ__SubscriptionTerm__c` *(if `Order.ProcessType__c == "ASPEN"`, compare against `Order_Service_Item__r.Support_Term__c` instead)* |
        | 5 | Quantity | `Quantity__c == Order_Quantity__c` |
        """)

                            st.markdown("**Manufacturing Entitlement (`Type = 'Manufacturing Entitlement'`)**")
                            st.markdown("""
        | # | Validation | Rule |
        |---|---|---|
        | 1 | MFG Ent SubType | `SubType__c` must be **blank / null** |
        | 2 | MFG Ent BaseProductName | `Product__r.Name == "TPH-MFG-ENT"` |
        | 3 | MFG Ent Quantity | `Quantity__c > 0` |
        | 4 | MFG Ent Account Match | `Entitlement.AccountId == Order.AccountId` |
        | 5 | MFG Ent Partner Match | `Entitlement.Manufacturing_Integration_Partner__c == Order.Manufacturing_Integration_Partner__c` |
        | 6 | MFG Ent Start/End Date | If `Order.Order_Status__c == "Shipped"`, `StartDate` and `EndDate` must be populated (blank is OK before shipping) |
        | 7 | MFG Ent Unique Per Order Line | At most one Manufacturing Entitlement per `Order_Service_Item__c` |
        """)

                        with _tab_soql:
                            st.markdown("##### SOQL Queries Used")
                            st.info(
                                "All three primary queries run **in parallel** per order. "
                                "The Replacement Entitlement query runs sequentially only when `Line_Types__c` is set."
                            )

                            st.markdown("**Q1 — Order + OrderItems (single combined query, run in parallel)**")
                            st.code("""\
        SELECT Id, OrderNumber, ProcessType__c,
               SBQQ__Contracted__c, SC_or_Entitlement_Stage__c,
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
               WelcomeEmailSentforSoftwareProducts__c, SD_Status__c,
               Primary_Contact_Screen_Status__c, Shipping_Carrier__c, SCAC__c, Smart_Hands_Provider__c,
               SBQQ__PriceCalcStatus__c, Have_Hardware_Products__c, Polaris_Fulfillment_Status__c,
               Order_Split_Type__c, POC_Opportunity__c, POC_Completion_Date__c, POC_Type__c,
               POC_Opportunity__r.Distributor_Lookup__c, POC_Opportunity__r.Distributor_Lookup__r.Name,
               (SELECT Product2.Shipping_Lead_Time__c, Product2.Order_Fulfilment__c, Product2.Name,
                       Printable_Product__c, Opportunity_Product__r.Printable_Product__c,
                       Payment_Options__c, SBQQ__QuoteLine__r.Product_Payment_Option__c,
                       SBQQ__SubscriptionTerm__c, SBQQ__QuoteLine__r.SBQQ__SubscriptionTerm__c,
                       SBQQ__QuoteLine__r.SBQQ__StartDate__c, SBQQ__QuoteLine__r.SBQQ__EndDate__c,
                       SBQQ__QuoteLine__r.End_Date__c,
                       SerialNumber__c, Upgraded_From__c,
                       Support_Start_Date__c, Support_End_Date__c,
                       Support_Term__c, Segment_Label__c, Quarter__c,
                       SBQQ__QuoteLine__r.SBQQ__SegmentLabel__c, Product2.Product_Type__c,
                       SBQQ__QuoteLine__r.Subscribed_Asset_Name__c,
                       SBQQ__QuoteLine__r.SubscribedAssetNames__c,
                       SBQQ__QuoteLine__r.Arroyo_Subscribed_Asset_Name__c,
                       UnitPrice, Quantity, TotalPrice,
                       Previous_Transaction_Reference__c, Replacement_Type__c, Credit_Amount__c,
                       Product_Name__c
                FROM OrderItems)
        FROM Order WHERE OrderNumber = '<order_num>' LIMIT 1""", language="sql")

                            st.markdown("**Q2 — Order Success Metrics (run in parallel)**")
                            st.code("""\
        SELECT Order_Creation_Metrics__c, Order_Booking_Metrics__c,
               Order_Provisioning_Metrics__c, Booking_Creation_Metrics__c,
               SC_creation_Metrics__c, Stage_PO_Submission_Metrics__c,
               CLI_creation_Metrics__c, Entitlement_Creation_Metrics__c, Comment__c
        FROM Order_Success_Metrics__c
        WHERE Order__r.Order_Number__c = '<order_num>'
        LIMIT 1""", language="sql")

                            st.markdown("**Q3 — Entitlements (run in parallel)**")
                            st.code("""\
        SELECT Name, Type, SubType__c,
               Order_Service_Item__r.Printable_Product__c,
               Product__r.Name,
               Order_Service_Item__r.Product2.Name,
               Subscription_Term__c,
               Order_Service_Item__r.SBQQ__SubscriptionTerm__c,
               Order_Service_Item__r.Support_Term__c,
               Quantity__c, Order_Quantity__c,
               AccountId, Manufacturing_Integration_Partner__c,
               Order_Service_Item__c, StartDate, EndDate
        FROM Entitlement
        WHERE Order_Service_Item__r.Order.Order_Number__c = '<order_num>'""", language="sql")

                            st.markdown("**Q4 — Linked Orders by Quote (sequential — depends on Quote ID from Q1)**")
                            st.code("""\
        SELECT OrderNumber, TotalAmount
        FROM Order
        WHERE SBQQ__Quote__c = '<quote_id>'
        ORDER BY OrderNumber ASC""", language="sql")

                            st.markdown("---")
                            st.markdown("**Replacement Order Queries** *(only when `Line_Types__c` is set)*")

                            st.markdown("**R1 — Replacement line items** *(already returned inside Q1 `OrderItems` subquery)*")
                            st.caption(
                                "Fields used: `Previous_Transaction_Reference__c`, `Replacement_Type__c`, "
                                "`Credit_Amount__c`, `Product_Name__c`, `Printable_Product__c`"
                            )

                            st.markdown("**R2 — Entitlement lookup for Previous Transactions (sequential)**")
                            st.caption(
                                "Runs after parsing the JSON `entId` values from `Previous_Transaction_Reference__c`"
                            )
                            st.code("""\
        SELECT Id,
               Order_Service_Item__r.Payment_Options__c
        FROM Entitlement
        WHERE Id IN ('<entId_1>', '<entId_2>', ...)""", language="sql")

                    # Placeholder for overall summary table — filled after all validations are computed
                    overall_summary_placeholder = st.empty()

                    # ── Order Type gate ────────────────────────────────────────────────
                    is_rma_order = sf_order_type.lower() == "rma"
                    RMA_SKIP_MSG = ("ℹ️ This is RMA order hence Booking's, Contract line items, "
                                    "Entitlements & Linked Assets are not required")

                    is_poc_order = sf_order_type.lower() == "poc"
                    POC_SKIP_MSG = ("🚧 POC orders use a distinct Evaluation-stage lifecycle (no Booking/Contract/"
                                    "Entitlement records in the standard Revenue shape) — this tab is not applicable.")

                    # ── Distributor lookup ─────────────────────────────────────────────
                    EDI_DISTRIBUTORS = {
                        "0018Y00002yRMhdQAG": "EDI & Ingram Distributor",
                        "0011W00001zHdYfQAK": "EDI & Arrow Distributor",
                        "0014000001gDigqAAC": "EDI & EXN UK Distributor",
                        "0014000001o5BNXAA2": "EDI & Carahsoft Distributor",
                    }
                    CARAHSOFT_ID = "0014000001o5BNXAA2"

                    # ── Validation rules ───────────────────────────────────────────────
                    results             = []
                    orderitem_results   = []
                    quote_header_results = []

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

                    # RMA Check A — Primary Contact Screening (order-level, always-true for RMA)
                    if is_rma_order:
                        _pcs_status = "✅ PASS" if primary_contact_screen_status == "NA" else "❌ FAIL"
                        results.append({
                            "#": "—", "Validation": "RMA — Primary Contact Screening",
                            "Details": "Order.Type=RMA → Primary_Contact_Screen_Status__c should be 'NA' "
                                       "(RMA orders are exempt from primary-contact GTC screening; "
                                       "Constants.ORDER_SCREEN_STATUS_NA)",
                            "Expected": "NA", "Actual": primary_contact_screen_status or "(blank)",
                            "Status": _pcs_status,
                        })

                    # RMA Check B — TSP Smart Hands Shipping Fields (order-level, conditional)
                    if is_rma_order and order_sub_type == "Tech Order" and smart_hands_provider == "TSP Inc.":
                        _tsp_ok = shipping_carrier == "TSP" and scac == "TPSCHD"
                        if _tsp_ok:
                            _tsp_status = "✅ PASS"
                        else:
                            _mismatches = []
                            if shipping_carrier != "TSP":
                                _mismatches.append(f"Shipping_Carrier__c={shipping_carrier or '(blank)'}")
                            if scac != "TPSCHD":
                                _mismatches.append(f"SCAC__c={scac or '(blank)'}")
                            _tsp_status = "❌ FAIL (" + ", ".join(_mismatches) + ")"
                        results.append({
                            "#": "—", "Validation": "RMA — TSP Smart Hands Shipping Fields",
                            "Details": "Order_Sub_Type__c=Tech Order & Smart_Hands_Provider__c=TSP Inc. → "
                                       "Shipping_Carrier__c should be 'TSP' and SCAC__c should be 'TPSCHD'",
                            "Expected": "TSP / TPSCHD",
                            "Actual": f"{shipping_carrier or '(blank)'} / {scac or '(blank)'}",
                            "Status": _tsp_status,
                        })

                    # POC Check A — Price Calc Status (order-level, always-true for POC)
                    if is_poc_order:
                        _pcs2_status = "✅ PASS" if price_calc_status == "Not Needed" else "❌ FAIL"
                        results.append({
                            "#": "—", "Validation": "POC — Price Calc Status",
                            "Details": "Order.Type=POC → SBQQ__PriceCalcStatus__c should always be 'Not Needed'",
                            "Expected": "Not Needed", "Actual": price_calc_status or "(blank)",
                            "Status": _pcs2_status,
                        })

                    # POC Check B — Primary Contact Screening Required (order-level, always-true for non-RMA)
                    if is_poc_order:
                        _pcr_status = "✅ PASS" if primary_contact_screen_status == "Required" else "❌ FAIL"
                        results.append({
                            "#": "—", "Validation": "POC — Primary Contact Screening",
                            "Details": "Order.Type=POC (non-RMA) → Primary_Contact_Screen_Status__c should be "
                                       "'Required' (Constants.ORDER_SCREEN_STATUS_REQUIRED)",
                            "Expected": "Required", "Actual": primary_contact_screen_status or "(blank)",
                            "Status": _pcr_status,
                        })

                    # POC Check C — Bill To / Distributor consistency (conditional on no order split)
                    if is_poc_order and order_split_type == "Not needed":
                        _bill_ok = bool(bill_to_id) and bill_to_id == poc_opp_distributor_id
                        results.append({
                            "#": "—", "Validation": "POC — Bill To / Distributor Consistency",
                            "Details": "Order_Split_Type__c='Not needed' → Bill_To_Name__c should equal "
                                       "POC_Opportunity__r.Distributor_Lookup__c",
                            "Expected": poc_opp_distributor_nm or "(blank)",
                            "Actual": bill_to_name or "(blank)",
                            "Status": "✅ PASS" if _bill_ok else "❌ FAIL",
                        })

                    # POC informational row — shipPOCOrder auto-ship eligibility (not PASS/FAIL)
                    if is_poc_order:
                        _poc_manual_fulfil = bool(record.get("ManualFulfilment__c"))
                        _poc_ship_eligible = (
                            not have_hardware
                            and order_sub_type != "GC OnDemand"
                            and not _poc_manual_fulfil
                            and (not order_polaris or polaris_fulfill_status == "Completed")
                            and screen_status in ("Approved", "Approved Bypassed")
                        )
                        _poc_ship_note = ""
                        if _poc_ship_eligible and order_status != "Shipped":
                            _poc_ship_note = " — eligible but not yet Shipped (worth a look; trigger timing isn't observable from a snapshot)"
                        results.append({
                            "#": "—", "Validation": "POC — Auto-Ship (shipPOCOrder) Eligibility",
                            "Details": "Software-only POC orders that meet all fast-path conditions "
                                       "(no hardware, not GC OnDemand, not manual fulfilment, Polaris fulfilment "
                                       "complete or N/A, screening Approved/Approved Bypassed) auto-ship via "
                                       "shipPOCOrder instead of the standard path. Informational only.",
                            "Expected": "—",
                            "Actual": ("Eligible" if _poc_ship_eligible else "Not eligible") + _poc_ship_note,
                            "Status": f"ℹ️ {'Eligible' if _poc_ship_eligible else 'Not eligible'}{_poc_ship_note}",
                        })

                    # Order Success Metrics — independently recomputed vs. stored record
                    METRICS_FIELDS = [
                        ("Order_Creation_Metrics__c",       "Order Creation Metrics"),
                        ("Order_Booking_Metrics__c",        "Order Booking Metrics"),
                        ("Order_Provisioning_Metrics__c",   "Order Provisioning Metrics"),
                        ("Booking_Creation_Metrics__c",     "Booking Creation Metrics"),
                        ("SC_creation_Metrics__c",          "SC Creation Metrics"),
                        ("Stage_PO_Submission_Metrics__c",  "Stage PO Submission Metrics"),
                        ("CLI_creation_Metrics__c",         "CLI Creation Metrics"),
                        ("Entitlement_Creation_Metrics__c", "Entitlement Creation Metrics"),
                    ]
                    _expected_metrics = compute_expected_metrics(
                        record,
                        _history_result.get("records", []),
                        _sc_result.get("records", []),
                        _orderitem_gate_result.get("records", []),
                        _mdt_result.get("records", []),
                    )
                    _has_osm_record = bool(metrics_record)
                    for field, label in METRICS_FIELDS:
                        expected_val = _expected_metrics.get(field)
                        actual_val = metrics_record.get(field)
                        if not _has_osm_record:
                            status = f"⏳ No Order_Success_Metrics__c record yet (expected: {expected_val or 'blank'})"
                        elif (expected_val or None) == (actual_val or None):
                            status = "✅ PASS"
                        else:
                            status = f"❌ MISMATCH — expected {expected_val or 'blank'}, actual {actual_val or 'blank'}"
                        results.append({"#": "—", "Validation": f"Metrics — {label}",
                                         "Details": f"{field}: {actual_val or '(blank)'}",
                                         "Expected": expected_val or "(blank)",
                                         "Actual": actual_val or "(blank)", "Status": status})

                    _comment_val = metrics_record.get("Comment__c") or "(blank)"
                    results.append({"#": "—", "Validation": "Metrics — Comment",
                                     "Details": f"Comment__c: {_comment_val}", "Expected": "—",
                                     "Actual": _comment_val, "Status": f"ℹ️ {_comment_val}"})

                    # ── Quote Header validations ────────────────────────────────────────
                    # Tier A = real pass/fail checks for logic confirmed against this org's
                    # validation rules / formula fields / Apex (QuoteTriggerHelper.cls,
                    # MetricsCalculatorUtil.cls). Tier B = reference-only display for fields
                    # whose value is either a native CPQ rollup (no local source of truth to
                    # assert against) or governed by logic too org-specific/brittle to assert
                    # (e.g. a hardcoded User Id in a formula field).
                    if quote_record:
                        _qh_opp_r      = record.get("Opportunity") or {}
                        _qh_opp_acct_r = _qh_opp_r.get("Account") or {}
                        _qh_net_amt    = quote_record.get("SBQQ__NetAmount__c")
                        _qh_opp_amt    = _qh_opp_r.get("Amount")
                        _qh_is_equal_stored = quote_record.get("Is_Quote_Amount_Equal_to_Oppty_Amount__c")

                        # A1 — Is_Quote_Amount_Equal_to_Oppty_Amount__c formula:
                        # IF(SBQQ__NetAmount__c == Opportunity.Amount, true, false)
                        if _qh_net_amt is None or _qh_opp_amt is None:
                            _qh_a1_status = "ℹ️ N/A (SBQQ__NetAmount__c or Opportunity.Amount is blank)"
                        else:
                            _qh_a1_expected = round(float(_qh_net_amt), 2) == round(float(_qh_opp_amt), 2)
                            _qh_a1_matched  = bool(_qh_is_equal_stored) == _qh_a1_expected
                            _qh_a1_status = ("✅ PASS — Is_Quote_Amount_Equal_to_Oppty_Amount__c matches recomputed formula"
                                              if _qh_a1_matched else
                                              "❌ FAIL — Is_Quote_Amount_Equal_to_Oppty_Amount__c does not match recomputed formula")
                        quote_header_results.append({
                            "#": "—",
                            "Validation": "Is_Quote_Amount_Equal_to_Oppty_Amount__c",
                            "Details": (f"SBQQ__NetAmount__c: {fmt_amount(_qh_net_amt) if _qh_net_amt is not None else '(blank)'} | "
                                        f"Opportunity.Amount: {fmt_amount(_qh_opp_amt) if _qh_opp_amt is not None else '(blank)'} | "
                                        f"Stored checkbox: {_qh_is_equal_stored}"),
                            "Expected": str(_qh_a1_expected) if _qh_net_amt is not None and _qh_opp_amt is not None else "—",
                            "Actual": str(_qh_is_equal_stored),
                            "Status": _qh_a1_status,
                        })

                        # A2 — Approval_Status_Invalid rule: ApprovalStatus__c == 'Invalid'
                        # iff SBQQ__Status__c == 'Invalid'
                        _qh_approval_status = quote_record.get("ApprovalStatus__c") or ""
                        _qh_quote_status    = quote_record.get("SBQQ__Status__c") or ""
                        _qh_a2_mismatch = (_qh_approval_status == "Invalid") != (_qh_quote_status == "Invalid")
                        quote_header_results.append({
                            "#": "—",
                            "Validation": "Approval/Quote Status 'Invalid' Consistency",
                            "Details": f"ApprovalStatus__c: {_qh_approval_status or '(blank)'} | SBQQ__Status__c: {_qh_quote_status or '(blank)'}",
                            "Expected": "Both or neither = 'Invalid'",
                            "Actual": f"{_qh_approval_status or '(blank)'} / {_qh_quote_status or '(blank)'}",
                            "Status": ("❌ FAIL — one is 'Invalid' and the other isn't (violates Approval_Status_Invalid rule)"
                                       if _qh_a2_mismatch else
                                       "✅ PASS — consistent with Approval_Status_Invalid rule"),
                        })

                        # A3 — RCDMT_EOL_Date__c == Opportunity.Account.RCDMT_EOL_Date__c
                        # (QuoteTriggerHelper.cls:340)
                        _qh_quote_eol = quote_record.get("RCDMT_EOL_Date__c")
                        _qh_acct_eol  = _qh_opp_acct_r.get("RCDMT_EOL_Date__c")
                        _qh_eol_matched = _qh_quote_eol == _qh_acct_eol
                        quote_header_results.append({
                            "#": "—",
                            "Validation": "RCDMT_EOL_Date__c vs Account",
                            "Details": f"Quote.RCDMT_EOL_Date__c: {_qh_quote_eol or '(blank)'} | Opportunity.Account.RCDMT_EOL_Date__c: {_qh_acct_eol or '(blank)'}",
                            "Expected": _qh_acct_eol or "(blank)", "Actual": _qh_quote_eol or "(blank)",
                            "Status": "✅ PASS — RCDMT_EOL_Date__c matched" if _qh_eol_matched else "❌ FAIL — RCDMT_EOL_Date__c not matched",
                        })

                        # A4 — Since this Order exists for this Quote, either the Quote's own
                        # SBQQ__Ordered__c or the Opportunity's SBQQ__Ordered__c must be true
                        # (order creation is actually triggered off the Opportunity flag, not
                        # the Quote's — see Cannot_Update_Quote_if_Order_is_created rule, which
                        # checks the same OR condition)
                        _qh_quote_ordered = bool(quote_record.get("SBQQ__Ordered__c"))
                        _qh_opp_ordered   = bool(_qh_opp_r.get("SBQQ__Ordered__c"))
                        _qh_a4_ok = _qh_quote_ordered or _qh_opp_ordered
                        quote_header_results.append({
                            "#": "—",
                            "Validation": "Ordered Flag Consistency (Order exists)",
                            "Details": (f"Quote.SBQQ__Ordered__c: {_qh_quote_ordered} | Opportunity.SBQQ__Ordered__c: {_qh_opp_ordered} | "
                                        f"An Order exists for this Quote (this validation run), so at least one should be true"),
                            "Expected": "At least one = true", "Actual": f"Quote={_qh_quote_ordered} / Opportunity={_qh_opp_ordered}",
                            "Status": ("✅ PASS — Opportunity.SBQQ__Ordered__c is true (Quote-level flag isn't the trigger field in this org)"
                                       if _qh_a4_ok else
                                       "❌ FAIL — neither Ordered flag is true despite an Order existing"),
                        })

                        # A5 — Enforce_Quote_Type_Opportunity_Alignment rule
                        _qh_type     = quote_record.get("SBQQ__Type__c") or ""
                        _qh_opp_sub  = quote_record.get("OpportunitySubType__c") or ""
                        _QH_RENEWAL_SUBTYPES = {"Renewal", "MSP Consumption Renewal", "GC Renewal"}
                        _qh_misaligned = (
                            (_qh_type in ("Renewal+Expansion", "Quote") and _qh_opp_sub in _QH_RENEWAL_SUBTYPES) or
                            (_qh_type == "Renewal" and _qh_opp_sub not in _QH_RENEWAL_SUBTYPES and _qh_opp_sub != "")
                        )
                        quote_header_results.append({
                            "#": "—",
                            "Validation": "Quote Type / Opportunity Sub-Type Alignment",
                            "Details": f"SBQQ__Type__c: {_qh_type or '(blank)'} | Opportunity Sub-Type: {_qh_opp_sub or '(blank)'}",
                            "Expected": "Aligned per Enforce_Quote_Type_Opportunity_Alignment rule",
                            "Actual": f"{_qh_type or '(blank)'} / {_qh_opp_sub or '(blank)'}",
                            "Status": ("❌ FAIL — would violate Enforce_Quote_Type_Opportunity_Alignment"
                                       if _qh_misaligned else "✅ PASS — Type/Opportunity Sub-Type aligned"),
                        })

                        # ── Tier B — Reference Only ────────────────────────────────────
                        # Native CPQ rollups (Amounts) and org-specific/brittle logic
                        # (hardcoded-Id approval bypass, async-computed renewal metrics) —
                        # shown for visibility, not asserted.
                        _QUOTE_REFERENCE_FIELDS = [
                            ("SBQQ__Status__c", "Status"),
                            ("SBQQ__Type__c", "Type"),
                            ("SBQQ__Primary__c", "Primary"),
                            ("SBQQ__ContractingMethod__c", "Contracting Method"),
                            ("SBQQ__PaymentTerms__c", "Payment Terms"),
                            ("SBQQ__StartDate__c", "Start Date"),
                            ("SBQQ__EndDate__c", "End Date"),
                            ("SBQQ__ExpirationDate__c", "Expiration Date"),
                            ("SBQQ__SubscriptionTerm__c", "Subscription Term"),
                            ("SBQQ__NetAmount__c", "Net Amount"),
                            ("SBQQ__ListAmount__c", "List Amount"),
                            ("SBQQ__CustomerAmount__c", "Customer Amount"),
                            ("SBQQ__RegularAmount__c", "Regular Amount"),
                            ("SBQQ__AdditionalDiscountAmount__c", "Additional Discount Amount"),
                            ("SBQQ__PricebookId__c", "Pricebook Id"),
                            ("Commit_Type__c", "Commit Type"),
                            ("Skip_Theatre_Approval_Step__c", "Skip Theatre Approval Step (hardcoded VP User Id formula)"),
                            ("MetricCalcStatus__c", "Metric Calc Status"),
                            ("TotalACV__c", "Total ACV"),
                            ("RTA__c", "Renewal Target Amount (RTA)"),
                            ("SBQQ__Ordered__c", "Ordered (Quote-level — not the order-creation trigger field in this org)"),
                        ]
                        for _fld, _label in _QUOTE_REFERENCE_FIELDS:
                            _val = quote_record.get(_fld)
                            _val_str = str(_val) if _val not in (None, "") else "(blank)"
                            quote_header_results.append({
                                "#": "—",
                                "Validation": f"{_label} (Reference Only)",
                                "Details": f"{_fld}: {_val_str} — native CPQ rollup / org-specific logic, not independently validated here",
                                "Expected": "—", "Actual": _val_str,
                                "Status": f"ℹ️ {_val_str}",
                            })

                    # ── QuoteLine validations ───────────────────────────────────────────
                    # Tier A = real pass/fail checks grounded in standard Salesforce CPQ
                    # (SteelBrick managed package) field semantics and formulas confirmed
                    # against force-app/main/default/objects/SBQQ__QuoteLine__c/fields/*
                    # metadata — e.g. SBQQ__AdditionalDiscount__c's own formula is
                    # (SBQQ__RegularPrice__c - SBQQ__CustomerPrice__c) * SBQQ__EffectiveQuantity__c.
                    # Tier B = reference-only display for fields with no independently
                    # assertable formula in this org (bundle/charge-type/date metadata).
                    _ql_records = _ql_result.get("records", [])
                    quote_line_results = []

                    def _ql_num_eq(a, b, tol=0.01):
                        if a is None or b is None:
                            return False
                        try:
                            return abs(float(a) - float(b)) <= tol
                        except (TypeError, ValueError):
                            return False

                    for _ql in _ql_records:
                        _ql_prod_r   = _ql.get("SBQQ__Product__r") or {}
                        _ql_name     = _ql.get("Name") or "(unknown)"
                        _ql_prod_nm  = _ql_prod_r.get("Name") or _ql.get("SBQQ__ProductCode__c") or "(unknown product)"
                        _ql_label    = f"{_ql_name} ({_ql_prod_nm})"

                        _ql_list_price   = _ql.get("SBQQ__ListPrice__c")
                        _ql_reg_price    = _ql.get("SBQQ__RegularPrice__c")
                        _ql_net_price    = _ql.get("SBQQ__NetPrice__c")
                        _ql_cust_price   = _ql.get("SBQQ__CustomerPrice__c")
                        _ql_term         = _ql.get("SBQQ__SubscriptionTerm__c")
                        _ql_eff_qty      = _ql.get("SBQQ__EffectiveQuantity__c")
                        _ql_add_disc     = _ql.get("SBQQ__AdditionalDiscount__c")
                        _ql_disc_pct     = _ql.get("SBQQ__Discount__c")
                        _ql_partner_disc = _ql.get("SBQQ__PartnerDiscount__c")
                        _ql_sub_pricing  = _ql_prod_r.get("SBQQ__SubscriptionPricing__c") or ""

                        # 1. Term-Price Consistency — Fixed Price subscription products:
                        # native CPQ pricing engine computes RegularPrice = ListPrice × SubscriptionTerm
                        # (Product2.SBQQ__SubscriptionPricing__c = "Fixed Price").
                        if _ql_sub_pricing != "Fixed Price" or _ql_list_price is None or _ql_term is None:
                            quote_line_results.append({
                                "#": "—",
                                "Validation": f"Term-Price Consistency — {_ql_label}",
                                "Details": "Not applicable — requires Product.SBQQ__SubscriptionPricing__c = 'Fixed Price' "
                                           "with ListPrice and SubscriptionTerm populated",
                                "Expected": "—", "Actual": f"SubscriptionPricing: {_ql_sub_pricing or '(blank)'}",
                                "Status": "ℹ️ N/A (not a Fixed Price subscription line)",
                            })
                        else:
                            _ql_expected_reg = round(float(_ql_list_price) * float(_ql_term), 2)
                            _ql_reg_match = _ql_num_eq(_ql_expected_reg, _ql_reg_price)
                            quote_line_results.append({
                                "#": "—",
                                "Validation": f"Term-Price Consistency — {_ql_label}",
                                "Details": (f"ListPrice ({fmt_amount(_ql_list_price)}) × SubscriptionTerm ({_ql_term}) "
                                            f"= {fmt_amount(_ql_expected_reg)} | Stored RegularPrice: {fmt_amount(_ql_reg_price)}"),
                                "Expected": fmt_amount(_ql_expected_reg), "Actual": fmt_amount(_ql_reg_price),
                                "Status": ("✅ PASS — RegularPrice matches ListPrice × Term" if _ql_reg_match else
                                           "❌ FAIL — RegularPrice does not match ListPrice × Term"),
                            })

                            # When there's no discount, Net/Customer Price should equal RegularPrice too.
                            _ql_no_discount = (_ql_add_disc in (None, 0)) and not _ql_partner_disc
                            if _ql_no_discount:
                                _ql_net_match = _ql_num_eq(_ql_expected_reg, _ql_net_price)
                                quote_line_results.append({
                                    "#": "—",
                                    "Validation": f"Term-Price Consistency (NetPrice, no discount) — {_ql_label}",
                                    "Details": (f"No discount applied — NetPrice should equal ListPrice × Term "
                                                f"({fmt_amount(_ql_expected_reg)}) | Stored NetPrice: {fmt_amount(_ql_net_price)}"),
                                    "Expected": fmt_amount(_ql_expected_reg), "Actual": fmt_amount(_ql_net_price),
                                    "Status": ("✅ PASS — NetPrice matches ListPrice × Term" if _ql_net_match else
                                               "❌ FAIL — NetPrice does not match ListPrice × Term"),
                                })

                        # 2. Additional Discount Formula — matches the field's own formula:
                        # SBQQ__AdditionalDiscount__c = (RegularPrice - CustomerPrice) × EffectiveQuantity
                        if _ql_reg_price is None or _ql_cust_price is None or _ql_eff_qty is None:
                            quote_line_results.append({
                                "#": "—",
                                "Validation": f"Additional Discount Formula — {_ql_label}",
                                "Details": "Not applicable — RegularPrice, CustomerPrice, or EffectiveQuantity is blank",
                                "Expected": "—", "Actual": fmt_amount(_ql_add_disc) if _ql_add_disc is not None else "(blank)",
                                "Status": "ℹ️ N/A (inputs blank)",
                            })
                        else:
                            _ql_expected_add_disc = round((float(_ql_reg_price) - float(_ql_cust_price)) * float(_ql_eff_qty), 2)
                            _ql_add_disc_match = _ql_num_eq(_ql_expected_add_disc, _ql_add_disc)
                            quote_line_results.append({
                                "#": "—",
                                "Validation": f"Additional Discount Formula — {_ql_label}",
                                "Details": (f"(RegularPrice {fmt_amount(_ql_reg_price)} - CustomerPrice {fmt_amount(_ql_cust_price)}) "
                                            f"× EffectiveQuantity ({_ql_eff_qty}) = {fmt_amount(_ql_expected_add_disc)} | "
                                            f"Stored AdditionalDiscount: {fmt_amount(_ql_add_disc)}"),
                                "Expected": fmt_amount(_ql_expected_add_disc), "Actual": fmt_amount(_ql_add_disc),
                                "Status": ("✅ PASS — matches field formula" if _ql_add_disc_match else
                                           "❌ FAIL — does not match field formula"),
                            })

                        # 3. Net vs Regular Price Sanity — NetPrice should never exceed RegularPrice
                        if _ql_net_price is None or _ql_reg_price is None:
                            quote_line_results.append({
                                "#": "—",
                                "Validation": f"Net vs Regular Price Sanity — {_ql_label}",
                                "Details": "Not applicable — NetPrice or RegularPrice is blank",
                                "Expected": "—", "Actual": "—",
                                "Status": "ℹ️ N/A (inputs blank)",
                            })
                        else:
                            _ql_sane = float(_ql_net_price) <= float(_ql_reg_price) + 0.01
                            quote_line_results.append({
                                "#": "—",
                                "Validation": f"Net vs Regular Price Sanity — {_ql_label}",
                                "Details": f"NetPrice: {fmt_amount(_ql_net_price)} | RegularPrice: {fmt_amount(_ql_reg_price)}",
                                "Expected": "NetPrice <= RegularPrice", "Actual": f"{fmt_amount(_ql_net_price)} / {fmt_amount(_ql_reg_price)}",
                                "Status": "✅ PASS" if _ql_sane else "❌ FAIL — NetPrice exceeds RegularPrice",
                            })

                        # 4. Discount % Consistency — NetPrice = RegularPrice × (1 - Discount/100)
                        if _ql_disc_pct is None or _ql_reg_price is None or _ql_net_price is None:
                            quote_line_results.append({
                                "#": "—",
                                "Validation": f"Discount % Consistency — {_ql_label}",
                                "Details": "Not applicable — SBQQ__Discount__c, RegularPrice, or NetPrice is blank",
                                "Expected": "—", "Actual": fmt_amount(_ql_net_price) if _ql_net_price is not None else "(blank)",
                                "Status": "ℹ️ N/A (inputs blank)",
                            })
                        else:
                            _ql_expected_net = round(float(_ql_reg_price) * (1 - float(_ql_disc_pct) / 100), 2)
                            _ql_disc_match = _ql_num_eq(_ql_expected_net, _ql_net_price)
                            quote_line_results.append({
                                "#": "—",
                                "Validation": f"Discount % Consistency — {_ql_label}",
                                "Details": (f"RegularPrice ({fmt_amount(_ql_reg_price)}) × (1 - Discount {_ql_disc_pct}%) "
                                            f"= {fmt_amount(_ql_expected_net)} | Stored NetPrice: {fmt_amount(_ql_net_price)}"),
                                "Expected": fmt_amount(_ql_expected_net), "Actual": fmt_amount(_ql_net_price),
                                "Status": ("✅ PASS — NetPrice matches Discount %" if _ql_disc_match else
                                           "❌ FAIL — NetPrice does not match Discount %"),
                            })

                        # Tier B — Reference Only fields (native CPQ metadata, not asserted)
                        _QL_REFERENCE_FIELDS = [
                            ("SBQQ__Quantity__c", "Quantity"),
                            ("SBQQ__PricingMethod__c", "Pricing Method"),
                            ("SBQQ__SpecialPrice__c", "Special Price"),
                            ("SBQQ__ChargeType__c", "Charge Type"),
                            ("SBQQ__Bundle__c", "Bundle"),
                            ("SBQQ__BundledQuantity__c", "Bundled Quantity"),
                            ("SBQQ__RequiredBy__c", "Required By (Bundle Parent)"),
                            ("SBQQ__StartDate__c", "Start Date"),
                            ("SBQQ__EndDate__c", "End Date"),
                        ]
                        for _fld, _label in _QL_REFERENCE_FIELDS:
                            _val = _ql.get(_fld)
                            _val_str = str(_val) if _val not in (None, "") else "(blank)"
                            quote_line_results.append({
                                "#": "—",
                                "Validation": f"{_label} (Reference Only) — {_ql_label}",
                                "Details": f"{_fld}: {_val_str} — native CPQ field, not independently validated here",
                                "Expected": "—", "Actual": _val_str,
                                "Status": f"ℹ️ {_val_str}",
                            })

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
                    if is_rma_order:
                        results.append({"#": "5", "Validation": "CESD (Current Est Ship Date)",
                                         "Details": "Order.Type=RMA → CESD/Est_Ship_Date__c not required",
                                         "Expected": "—", "Actual": est_ship_date or "(blank)",
                                         "Status": "ℹ️ N/A (RMA order)"})
                    else:
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
                    if is_rma_order:
                        results.append({"#": "6", "Validation": "EDD (Est Delivery Date)",
                                         "Details": "Order.Type=RMA → EDD/Deliver_By__c not required",
                                         "Expected": "—", "Actual": deliver_by or "(blank)",
                                         "Status": "ℹ️ N/A (RMA order)"})
                    else:
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
                    if is_rma_order:
                        booking_label, booking_status_val = "N/A (RMA order — Bookings not required)", "ℹ️ N/A"
                    elif booking_status == "Completed" and order_status_active:
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
                    manual_fulfilment_reason = record.get("Manual_Fulfilment_Selection_Reason__c")
                    if manual_fulfillment_quote is not None:
                        # New logic: Quote.Manual_Fulfillment_Quote__c is a semicolon-delimited
                        # multi-value picklist. Order.ManualFulfilment__c should be True iff the
                        # Order-level Manual_Fulfilment_Selection_Reason__c is one of the values
                        # listed in the Quote field (membership check, not naive equality).
                        _mfq_values = [v.strip() for v in str(manual_fulfillment_quote).split(";") if v.strip()]
                        reason_in_list = (manual_fulfilment_reason or "").strip() in _mfq_values
                        if reason_in_list and order_manual_fulfil:
                            mf_label  = "Selection Reason is in Quote's Manual Fulfillment list, Order.ManualFulfilment__c = True"
                            mf_status = "✅ PASS"
                        elif not reason_in_list and not order_manual_fulfil:
                            mf_label  = "Selection Reason is not in Quote's Manual Fulfillment list, Order.ManualFulfilment__c = False"
                            mf_status = "✅ PASS"
                        elif reason_in_list and not order_manual_fulfil:
                            mf_label  = "Selection Reason is in Quote's Manual Fulfillment list but Order.ManualFulfilment__c = False"
                            mf_status = "❌ FAIL"
                        else:
                            mf_label  = "Selection Reason is not in Quote's Manual Fulfillment list but Order.ManualFulfilment__c = True"
                            mf_status = "❌ FAIL"
                        mf_details  = (f"Quote.Manual_Fulfillment_Quote__c: {manual_fulfillment_quote} | "
                                       f"Order.Manual_Fulfilment_Selection_Reason__c: {manual_fulfilment_reason} | "
                                       f"Order.ManualFulfilment__c: {order_manual_fulfil}")
                        mf_expected = "ManualFulfilment__c = True iff Manual_Fulfilment_Selection_Reason__c is one of the ';'-delimited values in Quote.Manual_Fulfillment_Quote__c"
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
                        order_pp = _clean_sf(item.get("Printable_Product__c"))
                        opp_r    = item.get("Opportunity_Product__r") or {}
                        opp_pp   = _clean_sf(opp_r.get("Printable_Product__c"))
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
                    # Excluded for GC Offer / GC OnDemand / GC Renewal orders.
                    # POC orders: the real Apex comparison is POC-order-specific and
                    # segment-conditional (SBQQ__SegmentIndex__c / Additional_Term__c),
                    # sourced via OrderItem.POC_Line_Item__c rather than SBQQ__QuoteLine__c
                    # (SBQQ__QuoteLine__r is always null on POC OrderItems, so the flat
                    # QuoteLine comparison below is structurally invalid for them). The
                    # exact POC_Line_Item__c relationship/field path was not confirmed
                    # against live Apex, so POC lines are reported N/A rather than
                    # asserting an unconfirmed formula.
                    _ST_EXCLUDED_SUBTYPES = {"GC Offer", "GC OnDemand", "GC Renewal"}
                    for item in ([] if order_sub_type in _ST_EXCLUDED_SUBTYPES else items_result.get("records", [])):
                        p2            = item.get("Product2") or {}
                        p2_name       = p2.get("Name") or "(unknown product)"
                        if is_poc_order:
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"Subscription Term Match — {p2_name}",
                                "Details":    ("POC order: real Apex logic is POC-specific and segment-conditional "
                                               "(SBQQ__SegmentIndex__c / Additional_Term__c) via OrderItem.POC_Line_Item__c, "
                                               "not SBQQ__QuoteLine__c (always null for POC lines). Exact field/relationship "
                                               "path not confirmed against live Apex — not validated here."),
                                "Expected":   "N/A (POC order)",
                                "Actual":     "N/A (POC order)",
                                "Status":     "ℹ️ N/A — POC order (segment-conditional formula not confirmed)",
                            })
                            continue
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

                        # If SBQQ__SubscriptionTerm__c is null the product does not carry a
                        # subscription term (e.g. hardware / one-time SKU) — skip both date checks.
                        if oi_term is None:
                            _pp_label = (item.get("Printable_Product__c") or "").strip() or p2_name
                            _pt_label = (p2.get("Product_Type__c") or "").strip() or "(blank)"
                            _start_exp = (f"❯ expected: Support Start Date: {_pp_label} sku not required "
                                          f"the support start date logic becoz sku type is {_pt_label} "
                                          f"and Term is blank.")
                            _end_exp   = (f"❯ expected: Support end Date: {_pp_label} sku not required "
                                          f"the support end date logic becoz sku type is {_pt_label} "
                                          f"and Term is blank.")
                            for _vlabel, _exp_msg in (("Support Start Date", _start_exp),
                                                      ("Support End Date",   _end_exp)):
                                orderitem_results.append({
                                    "#":          "—",
                                    "Validation": f"{_vlabel} — {p2_name}",
                                    "Details":    (f"SBQQ__SubscriptionTerm__c is null — date validation skipped. "
                                                   f"Printable_Product__c: {_pp_label}, Product_Type__c: {_pt_label}"),
                                    "Expected":   _exp_msg,
                                    "Actual":     "N/A",
                                    "Status":     "ℹ️ N/A — SubscriptionTerm is null",
                                })
                            continue

                        if order_sub_type == "Renewal":
                            # Renewal: Support Start Date vs SBQQ__QuoteLine__r.SBQQ__StartDate__c
                            exp_start = (ql_r.get("SBQQ__StartDate__c") or "")[:10]
                            start_pass = oi_start == exp_start
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"Support Start Date — {p2_name}",
                                "Details":    f"Support_Start_Date__c: {oi_start or '(blank)'} | Expected: SBQQ__QuoteLine__r.SBQQ__StartDate__c ({exp_start or '(blank)'})",
                                "Expected":   exp_start or "(blank)",
                                "Actual":     oi_start or "(blank)",
                                "Status":     "✅ PASS — Support Start Date matched" if start_pass else "❌ FAIL — Support Start Date not matched",
                            })

                            # Renewal: Support End Date vs SBQQ__QuoteLine__r.SBQQ__EndDate__c
                            exp_end  = (ql_r.get("SBQQ__EndDate__c") or "")[:10]
                            end_pass = oi_end == exp_end
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"Support End Date — {p2_name}",
                                "Details":    f"Support_End_Date__c: {oi_end or '(blank)'} | Expected: SBQQ__QuoteLine__r.SBQQ__EndDate__c ({exp_end or '(blank)'})",
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

                            if is_poc_order and order_sub_type != "Try N Buy" and poc_type != "Ransomware Recovery Software":
                                # POC: Support_End_Date__c = Order.POC_Completion_Date__c + 7 days
                                # (OrderUpdateHelper.cls processOrderItem — independent of Subscription Term)
                                if poc_completion_date:
                                    exp_end  = add_days(poc_completion_date, 7)
                                    end_pass = oi_end == exp_end
                                    orderitem_results.append({
                                        "#":          "—",
                                        "Validation": f"Support End Date — {p2_name}",
                                        "Details":    (f"Support_End_Date__c: {oi_end or '(blank)'} | Expected: "
                                                       f"Order.POC_Completion_Date__c + 7 days "
                                                       f"({poc_completion_date} + 7 = {exp_end})"),
                                        "Expected":   exp_end or "(blank)",
                                        "Actual":     oi_end or "(blank)",
                                        "Status":     "✅ PASS — Support End Date matched" if end_pass else "❌ FAIL — Support End Date not matched",
                                    })
                                else:
                                    orderitem_results.append({
                                        "#":          "—",
                                        "Validation": f"Support End Date — {p2_name}",
                                        "Details":    "Order.POC_Completion_Date__c is blank — cannot compute expected POC Support End Date.",
                                        "Expected":   "(blank — POC_Completion_Date__c not set)",
                                        "Actual":     oi_end or "(blank)",
                                        "Status":     "ℹ️ N/A — POC_Completion_Date__c is blank",
                                    })
                            elif is_poc_order:
                                # Try N Buy / Ransomware Recovery Software POC sub-cases derive Support End Date
                                # from the POC__c request record (POCRequestTriggerHelper), not POC_Completion_Date__c.
                                orderitem_results.append({
                                    "#":          "—",
                                    "Validation": f"Support End Date — {p2_name}",
                                    "Details":    (f"Order_Sub_Type__c={order_sub_type or '(blank)'!r} / POC_Type__c={poc_type or '(blank)'!r} "
                                                   f"— Support End Date is set from the POC__c request record via a separate "
                                                   f"code path, not Order.POC_Completion_Date__c + 7. Not validated here."),
                                    "Expected":   "—",
                                    "Actual":     oi_end or "(blank)",
                                    "Status":     "ℹ️ N/A — alternate POC sub-case (not modeled)",
                                })
                            else:
                                _pp_for_end = item.get("Printable_Product__c")
                                if _pp_for_end in ("RS-PAYGO-NC", "RS-PAYGO-C"):
                                    # Pay-Go SKUs extend Support End Date to end-of-month when the ship
                                    # date isn't the 1st — this naive "always -1 day" formula doesn't
                                    # model that exception, so defer to the dedicated check below.
                                    orderitem_results.append({
                                        "#":          "—",
                                        "Validation": f"Support End Date — {p2_name}",
                                        "Details":    f"Printable_Product__c: {_pp_for_end} — Pay-Go SKU; see 'MSP Pay Go Fulfillment' check below for the correct expected date.",
                                        "Expected":   "—",
                                        "Actual":     oi_end or "(blank)",
                                        "Status":     "ℹ️ N/A — validated by MSP Pay Go Fulfillment check",
                                    })
                                else:
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

                    # MSP Pay Go Fulfillment (per line item) — RS-PAYGO-NC / RS-PAYGO-C SKUs only
                    _PAYGO_SKUS = ("RS-PAYGO-NC", "RS-PAYGO-C")
                    for item in items_result.get("records", []):
                        product = item.get("Printable_Product__c")
                        if product not in _PAYGO_SKUS:
                            continue

                        p2      = item.get("Product2") or {}
                        p2_name = p2.get("Name") or "(unknown product)"
                        term_raw = item.get("Support_Term__c")
                        term_used_label = "Support_Term__c"
                        if term_raw is None:
                            term_raw = item.get("SBQQ__SubscriptionTerm__c")
                            term_used_label = "SBQQ__SubscriptionTerm__c"

                        if not actual_ship_date or term_raw is None:
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"MSP Pay Go Fulfillment — {p2_name}",
                                "Details":    f"Printable_Product__c: {product} | Actual_Order_Ship_Date__c: {actual_ship_date or '(blank)'} | Term: {term_raw if term_raw is not None else '(blank)'}",
                                "Expected":   "—",
                                "Actual":     "—",
                                "Status":     "ℹ️ N/A — Missing ship date or term",
                            })
                            continue

                        term_months = int(term_raw)
                        ship_dt     = parse_date(actual_ship_date)
                        is_first    = bool(ship_dt) and ship_dt.day == 1
                        exp_start   = actual_ship_date
                        if is_first:
                            exp_end = add_days(add_months(actual_ship_date, term_months), -1)
                        else:
                            exp_end = end_of_month(add_months(actual_ship_date, term_months))

                        oi_start = (item.get("Support_Start_Date__c") or "")[:10]
                        oi_end   = (item.get("Support_End_Date__c") or "")[:10]

                        if not oi_start and not oi_end:
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"MSP Pay Go Fulfillment — {p2_name}",
                                "Details":    f"Printable_Product__c: {product} | Ship Date: {actual_ship_date} | Term: {term_months} month(s) ({term_used_label})",
                                "Expected":   f"Start: {exp_start} | End: {exp_end}",
                                "Actual":     "Start: (blank) | End: (blank)",
                                "Status":     "ℹ️ N/A — No SFDC Support Start/End to compare",
                            })
                            continue

                        mismatches = []
                        if oi_start and oi_start != exp_start:
                            mismatches.append("Start mismatch")
                        if oi_end and oi_end != exp_end:
                            mismatches.append("End mismatch")

                        status = "✅ PASS — dates match" if not mismatches else f"❌ FAIL — {', '.join(mismatches)}"

                        orderitem_results.append({
                            "#":          "—",
                            "Validation": f"MSP Pay Go Fulfillment — {p2_name}",
                            "Details":    f"Printable_Product__c: {product} | Ship Date: {actual_ship_date} | Term: {term_months} month(s) ({term_used_label}) | 1st-of-month rule: {'1 day before' if is_first else 'end of month'}",
                            "Expected":   f"Start: {exp_start} | End: {exp_end}",
                            "Actual":     f"Start: {oi_start or '(blank)'} | End: {oi_end or '(blank)'}",
                            "Status":     status,
                        })

                    # Contract Line Item — every OrderItem should have a linked ContractLineItem
                    # (rendered in the "Contract Lineitems" tab, not here — see _cli_link_rows below)
                    # Products with SBQQ__SubscriptionTerm__c = null don't carry a Contract Line
                    # Item, so they're excluded from this validation entirely.
                    _cli_link_rows = []
                    for item in items_result.get("records", []):
                        if item.get("SBQQ__SubscriptionTerm__c") is None:
                            continue
                        p2      = item.get("Product2") or {}
                        p2_name = p2.get("Name") or item.get("Product_Name__c") or "(unknown product)"
                        cli_id  = item.get("SBQQSC__ContractLineItem__c")
                        _cli_link_rows.append({
                            "#":          "—",
                            "Validation": f"Contract Line Item — {p2_name}",
                            "Details":    "OrderItem.SBQQSC__ContractLineItem__c lookup to ContractLineItem",
                            "Expected":   "(populated)",
                            "Actual":     cli_id or "(blank)",
                            "Status":     "✅ PASS — Contract Line Item is linked" if cli_id else "❌ FAIL — No Contract Line Item linked",
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
                            """Append start + end rows as NA/informational (reference only).

                            NOTE: The exact GC Offer segment-chaining formula used by live Apex
                            could not be confirmed — the closest matching code found in the Apex
                            codebase is dead/commented-out. These rows are therefore marked NA
                            and show the actual value alongside a best-effort reference value,
                            without asserting PASS/FAIL against an unconfirmed formula.

                            Term priority: Support_Term__c wins when set, falls back to
                            SBQQ__SubscriptionTerm__c — same rule as the non-renewal path.
                            end_base: date used as the base for the reference end-date calculation
                            (defaults to exp_start so numbered segments chain correctly).
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

                            _na_status = "ℹ️ N/A — GC Offer segment-chaining formula not confirmed against live Apex (closest match is dead/commented-out code)"
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"Support Start Date — {p2_name} (Segment: {seg_display})",
                                "Details":    (f"Support_Start_Date__c: {oi_start or '(blank)'} | "
                                               f"Reference (unconfirmed) value: Actual_Order_Ship_Date__c ({exp_start or '(blank)'}) | "
                                               f"Segment: {seg_display}"),
                                "Expected":   "N/A — formula unconfirmed",
                                "Actual":     oi_start or "(blank)",
                                "Status":     _na_status,
                            })

                            if not _exp_end:
                                orderitem_results.append({
                                    "#":          "—",
                                    "Validation": f"Support End Date — {p2_name} (Segment: {seg_display})",
                                    "Details":    f"Cannot calculate reference end date — {_term_info}",
                                    "Expected":   "(blank — term null)",
                                    "Actual":     oi_end or "(blank)",
                                    "Status":     "ℹ️ N/A — SubscriptionTerm is null",
                                })
                            else:
                                orderitem_results.append({
                                    "#":          "—",
                                    "Validation": f"Support End Date — {p2_name} (Segment: {seg_display})",
                                    "Details":    (f"Support_End_Date__c: {oi_end or '(blank)'} | "
                                                   f"Reference (unconfirmed) value: {_exp_end} | "
                                                   f"Base: Actual_Order_Ship_Date__c ({_end_base}) | "
                                                   f"Term used: {_term_info}"),
                                    "Expected":   "N/A — formula unconfirmed",
                                    "Actual":     oi_end or "(blank)",
                                    "Status":     _na_status,
                                })
                            return _exp_end  # still returned so caller can chain the reference for the next segment

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

                    # Printable Product Count — per-line SKU-mapped flag comparison.
                    # Real Apex mechanism copies Printable_Product__c per line from the
                    # linked Opportunity Product; it is not a COUNT() aggregate across the order.
                    for item in items_result.get("records", []):
                        _pp_p2      = item.get("Product2") or {}
                        _pp_p2_name = _pp_p2.get("Name") or "(unknown product)"
                        _pp_order   = _clean_sf(item.get("Printable_Product__c"))
                        _pp_opp_r   = item.get("Opportunity_Product__r") or {}
                        _pp_opp     = _clean_sf(_pp_opp_r.get("Printable_Product__c"))
                        _pp_matched = _pp_order.lower() == _pp_opp.lower()
                        orderitem_results.append({"#": "—", "Validation": f"Printable Product Count — {_pp_p2_name}",
                                                   "Details": f"OrderItem.Printable_Product__c: {_pp_order or '(blank)'} | Opportunity_Product__r.Printable_Product__c: {_pp_opp or '(blank)'}",
                                                   "Expected": _pp_opp or "(blank)", "Actual": _pp_order or "(blank)",
                                                   "Status": "✅ PASS — Printable Product flag matched" if _pp_matched else "❌ FAIL — Printable Product flag not matched"})

                    # Welcome Letter validations — not required for RMA orders
                    # Condition 1: ProcessType = null AND Order_Status = Shipped
                    if not is_rma_order and not order_process_type and order_status == "Shipped":
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
                    if not is_rma_order and order_process_type and order_status == "Shipped":
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
                    if not is_rma_order and order_process_type and order_status == "Shipped" and sd_status == "Success":
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

                    if is_rma_order:
                        results.append({
                            "#": "—",
                            "Validation": "Welcome Letter Sent",
                            "Details": "Order.Type=RMA → Welcome Letter is not required",
                            "Expected": "—", "Actual": "—",
                            "Status": "ℹ️ N/A (RMA order)",
                        })

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

                    # SerialNumber validation — logic branches on Line_Types__c:
                    # • Line_Types__c set  → compare SerialNumber__c vs Arroyo_Subscribed_Asset_Name__c (QLI match)
                    # • Line_Types__c null → Hardware: count vs Quantity; Non-hardware: vs QLI subscribed asset names
                    def _normalise_serials(s: str) -> list:
                        return sorted(t.strip().lower() for t in s.split(",") if t.strip())

                    for item in items_result.get("records", []):
                        p2           = item.get("Product2") or {}
                        p2_name      = p2.get("Name") or "(unknown product)"
                        product_type = (p2.get("Product_Type__c") or "").strip()
                        serial_raw   = (item.get("SerialNumber__c") or "").strip()
                        qty          = item.get("Quantity") or 0
                        qty_int      = int(qty)

                        if line_types:
                            # When Line_Types__c is set: compare SerialNumber__c vs QuoteLine.Arroyo_Subscribed_Asset_Name__c
                            ql_r       = item.get("SBQQ__QuoteLine__r") or {}
                            arroyo_san = _clean_sf(ql_r.get("Arroyo_Subscribed_Asset_Name__c") or "").strip()
                            if not arroyo_san and not serial_raw:
                                orderitem_results.append({
                                    "#":          "—",
                                    "Validation": f"SerialNumber vs Quantity — {p2_name}",
                                    "Details":    f"Line_Types__c: {line_types} | SerialNumber__c: (blank) | QLI.Arroyo_Subscribed_Asset_Name__c: (blank)",
                                    "Expected":   "N/A",
                                    "Actual":     "N/A",
                                    "Status":     "ℹ️ N/A — No serial or Arroyo asset name to compare",
                                })
                            else:
                                sn_match = _normalise_serials(serial_raw) == _normalise_serials(arroyo_san)
                                orderitem_results.append({
                                    "#":          "—",
                                    "Validation": f"SerialNumber vs Quantity — {p2_name}",
                                    "Details":    (f"Line_Types__c: {line_types} | "
                                                   f"SerialNumber__c: {serial_raw or '(blank)'} | "
                                                   f"QLI.Arroyo_Subscribed_Asset_Name__c: {arroyo_san or '(blank)'}"),
                                    "Expected":   arroyo_san or "(blank)",
                                    "Actual":     serial_raw or "(blank)",
                                    "Status":     "✅ PASS — Serial Numbers matched with QLI" if sn_match else "❌ FAIL — Serial Numbers not matched with QLI",
                                })
                        elif product_type != "Hardware":
                            # Non-hardware (no Line_Types__c): validate vs QLI subscribed asset names
                            ql_r          = item.get("SBQQ__QuoteLine__r") or {}
                            qli_san       = _clean_sf(ql_r.get("Subscribed_Asset_Name__c") or "").strip()
                            qli_sans      = _clean_sf(ql_r.get("SubscribedAssetNames__c") or "").strip()
                            qli_expected  = qli_san or qli_sans
                            sn_actual     = serial_raw

                            if not qli_expected and not sn_actual:
                                orderitem_results.append({
                                    "#":          "—",
                                    "Validation": f"SerialNumber vs Quantity — {p2_name}",
                                    "Details":    f"Product_Type: {product_type or '(blank)'} | SerialNumber__c: (blank) | QLI Subscribed Asset: (blank)",
                                    "Expected":   "N/A",
                                    "Actual":     "N/A",
                                    "Status":     "ℹ️ N/A — No serial or QLI asset name to compare",
                                })
                            else:
                                sn_match = _normalise_serials(sn_actual) == _normalise_serials(qli_expected)
                                qli_field_used = "Subscribed_Asset_Name__c" if qli_san else "SubscribedAssetNames__c"
                                orderitem_results.append({
                                    "#":          "—",
                                    "Validation": f"SerialNumber vs Quantity — {p2_name}",
                                    "Details":    f"Product_Type: {product_type or '(blank)'} | SerialNumber__c: {sn_actual or '(blank)'} | QLI.{qli_field_used}: {qli_expected or '(blank)'}",
                                    "Expected":   qli_expected or "(blank)",
                                    "Actual":     sn_actual or "(blank)",
                                    "Status":     "✅ PASS — Serial Numbers matches with QLI" if sn_match else "❌ FAIL — Serial Numbers not matched with QLI",
                                })
                        elif not serial_raw:
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"SerialNumber vs Quantity — {p2_name}",
                                "Details":    f"SerialNumber__c: (blank) | Quantity: {qty_int} | Product_Type: Hardware",
                                "Expected":   f"{qty_int} serial number(s)",
                                "Actual":     "(blank)",
                                "Status":     "❌ FAIL — Hardware product missing SerialNumber",
                            })
                        else:
                            serial_list  = [s.strip() for s in serial_raw.split(",") if s.strip()]
                            serial_count = len(serial_list)
                            sn_pass      = serial_count == qty_int
                            orderitem_results.append({
                                "#":          "—",
                                "Validation": f"SerialNumber vs Quantity — {p2_name}",
                                "Details":    f"Serial count: {serial_count} | Quantity: {qty_int} | Serials: {serial_raw[:80]}{'…' if len(serial_raw) > 80 else ''}",
                                "Expected":   str(qty_int),
                                "Actual":     str(serial_count),
                                "Status":     "✅ PASS — Serial count matches Qty" if sn_pass else f"❌ FAIL — {serial_count} serial(s) but Qty = {qty_int}",
                            })

                    # Upgraded_From__c vs SerialNumber__c (only when Line_Types__c is set)
                    if line_types:
                        for item in items_result.get("records", []):
                            p2            = item.get("Product2") or {}
                            p2_name       = p2.get("Name") or "(unknown product)"
                            serial_raw    = (item.get("SerialNumber__c") or "").strip()
                            upgraded_from = (item.get("Upgraded_From__c") or "").strip()

                            if not upgraded_from and not serial_raw:
                                orderitem_results.append({
                                    "#":          "—",
                                    "Validation": f"Upgraded From — {p2_name}",
                                    "Details":    f"Line_Types__c: {line_types} | Upgraded_From__c: (blank) | SerialNumber__c: (blank)",
                                    "Expected":   "N/A",
                                    "Actual":     "N/A",
                                    "Status":     "ℹ️ N/A — Both Upgraded_From__c and SerialNumber__c are blank",
                                })
                            else:
                                uf_match = _normalise_serials(upgraded_from) == _normalise_serials(serial_raw)
                                orderitem_results.append({
                                    "#":          "—",
                                    "Validation": f"Upgraded From — {p2_name}",
                                    "Details":    (f"Line_Types__c: {line_types} | "
                                                   f"Upgraded_From__c: {upgraded_from or '(blank)'} | "
                                                   f"SerialNumber__c: {serial_raw or '(blank)'}"),
                                    "Expected":   serial_raw or "(blank)",
                                    "Actual":     upgraded_from or "(blank)",
                                    "Status":     "✅ PASS — Replaced From value Match" if uf_match else "❌ FAIL — Replaced From value Not matched",
                                })

                    # ── NEW — OrderItem Apex-field validations (from the rbk-sfdx-release ──
                    # Complete OrderItem Field Reference audit). Tier A = real pass/fail
                    # checks for deterministic Apex logic; Tier B (further below) = reference-
                    # only display for fields whose logic depends on Custom Labels/Metadata
                    # and multi-hop relationship chains too fragile to hard-code safely.

                    # A1 — SBQQ__OrderedQuantity__c = Quantity (OrderItemTriggerHelper.cls:729)
                    for item in items_result.get("records", []):
                        p2 = item.get("Product2") or {}
                        p2_name = p2.get("Name") or "(unknown product)"
                        qty = item.get("Quantity")
                        ordered_qty = item.get("SBQQ__OrderedQuantity__c")
                        if qty is None or ordered_qty is None:
                            status = "ℹ️ N/A (Quantity or SBQQ__OrderedQuantity__c is blank)"
                        else:
                            matched = float(ordered_qty) == float(qty)
                            status = ("✅ PASS — OrderedQuantity matches Quantity" if matched
                                      else "❌ FAIL — OrderedQuantity does not match Quantity")
                        orderitem_results.append({
                            "#": "—",
                            "Validation": f"SBQQ__OrderedQuantity__c vs Quantity — {p2_name}",
                            "Details": f"Quantity: {qty} | SBQQ__OrderedQuantity__c: {ordered_qty}",
                            "Expected": str(qty) if qty is not None else "(blank)",
                            "Actual": str(ordered_qty) if ordered_qty is not None else "(blank)",
                            "Status": status,
                        })

                    # A2 — Actual_Sales_Price__c = QuoteLine.SBQQ__ListPrice__c (:1359)
                    for item in items_result.get("records", []):
                        p2 = item.get("Product2") or {}
                        p2_name = p2.get("Name") or "(unknown product)"
                        ql_r = item.get("SBQQ__QuoteLine__r") or {}
                        actual_sp = item.get("Actual_Sales_Price__c")
                        exp_sp = ql_r.get("SBQQ__ListPrice__c")
                        if actual_sp is None or exp_sp is None:
                            status = "ℹ️ N/A (Actual_Sales_Price__c or QuoteLine.SBQQ__ListPrice__c is blank)"
                        else:
                            matched = round(float(actual_sp), 2) == round(float(exp_sp), 2)
                            status = ("✅ PASS — Actual Sales Price matched" if matched
                                      else "❌ FAIL — Actual Sales Price not matched")
                        orderitem_results.append({
                            "#": "—",
                            "Validation": f"Actual_Sales_Price__c vs QuoteLine.SBQQ__ListPrice__c — {p2_name}",
                            "Details": (f"Actual_Sales_Price__c: {fmt_amount(actual_sp)} | "
                                        f"QuoteLine.SBQQ__ListPrice__c: {fmt_amount(exp_sp)}"),
                            "Expected": fmt_amount(exp_sp), "Actual": fmt_amount(actual_sp),
                            "Status": status,
                        })

                    # A3 — Sales_Price__c = QuoteLine.SBQQ__CustomerPrice__c (:1360)
                    for item in items_result.get("records", []):
                        p2 = item.get("Product2") or {}
                        p2_name = p2.get("Name") or "(unknown product)"
                        ql_r = item.get("SBQQ__QuoteLine__r") or {}
                        sales_price = item.get("Sales_Price__c")
                        exp_cp = ql_r.get("SBQQ__CustomerPrice__c")
                        if sales_price is None or exp_cp is None:
                            status = "ℹ️ N/A (Sales_Price__c or QuoteLine.SBQQ__CustomerPrice__c is blank)"
                        else:
                            matched = round(float(sales_price), 2) == round(float(exp_cp), 2)
                            status = ("✅ PASS — Sales Price matched" if matched
                                      else "❌ FAIL — Sales Price not matched")
                        orderitem_results.append({
                            "#": "—",
                            "Validation": f"Sales_Price__c vs QuoteLine.SBQQ__CustomerPrice__c — {p2_name}",
                            "Details": (f"Sales_Price__c: {fmt_amount(sales_price)} | "
                                        f"QuoteLine.SBQQ__CustomerPrice__c: {fmt_amount(exp_cp)}"),
                            "Expected": fmt_amount(exp_cp), "Actual": fmt_amount(sales_price),
                            "Status": status,
                        })

                    # A4 — TPH_Drive_Size__c / TPH_Models_Gen__c / TPH_OEM__c = QuoteLine's
                    # same-named fields, OrderItem-level copy (:1362-1364) — distinct from the
                    # existing ContractLineItem-level TPH check elsewhere in this app.
                    for item in items_result.get("records", []):
                        p2 = item.get("Product2") or {}
                        p2_name = p2.get("Name") or "(unknown product)"
                        ql_r = item.get("SBQQ__QuoteLine__r") or {}
                        for _fld, _label in (("TPH_Drive_Size__c", "TPH Drive Size"),
                                              ("TPH_Models_Gen__c", "TPH Models/Gen"),
                                              ("TPH_OEM__c", "TPH OEM")):
                            oi_val = (item.get(_fld) or "").strip()
                            ql_val = (ql_r.get(_fld) or "").strip()
                            matched = oi_val == ql_val
                            orderitem_results.append({
                                "#": "—",
                                "Validation": f"{_label} vs QuoteLine (OrderItem-level) — {p2_name}",
                                "Details": f"OrderItem.{_fld}: {oi_val or '(blank)'} | QuoteLine.{_fld}: {ql_val or '(blank)'}",
                                "Expected": ql_val or "(blank)", "Actual": oi_val or "(blank)",
                                "Status": "✅ PASS — matched QuoteLine" if matched else "❌ FAIL — does not match QuoteLine",
                            })

                    # A5 — Entitlement_Id__c = String(QuoteLine.Account_s_Entitlement__c) when
                    # QuoteLine.SBQQ__Product__r.Upgrade_Path__c is set; else blank (:1287-1288)
                    for item in items_result.get("records", []):
                        p2 = item.get("Product2") or {}
                        p2_name = p2.get("Name") or "(unknown product)"
                        ql_r = item.get("SBQQ__QuoteLine__r") or {}
                        upgrade_path = (ql_r.get("SBQQ__Product__r") or {}).get("Upgrade_Path__c")
                        account_ent = ql_r.get("Account_s_Entitlement__c")
                        oi_ent_id = (item.get("Entitlement_Id__c") or "").strip()
                        expected = str(account_ent) if (upgrade_path and account_ent is not None) else ""
                        matched = oi_ent_id == expected
                        orderitem_results.append({
                            "#": "—",
                            "Validation": f"Entitlement_Id__c — {p2_name}",
                            "Details": (f"QuoteLine.SBQQ__Product__r.Upgrade_Path__c: {upgrade_path or '(blank)'} | "
                                        f"QuoteLine.Account_s_Entitlement__c: {account_ent if account_ent is not None else '(blank)'} | "
                                        f"OrderItem.Entitlement_Id__c: {oi_ent_id or '(blank)'}"),
                            "Expected": expected or "(blank)", "Actual": oi_ent_id or "(blank)",
                            "Status": "✅ PASS — Entitlement_Id__c matched" if matched else "❌ FAIL — Entitlement_Id__c not matched",
                        })

                    # A6 — Credit_Amount__c = (QuoteLine.Prepayment_Credit__c / QuoteLine.SBQQ__Quantity__c)
                    # * oi.Quantity, when Prepayment_Credit__c is set; else blank (:769 / :1271)
                    for item in items_result.get("records", []):
                        p2 = item.get("Product2") or {}
                        p2_name = p2.get("Name") or "(unknown product)"
                        ql_r = item.get("SBQQ__QuoteLine__r") or {}
                        prepay_credit = ql_r.get("Prepayment_Credit__c")
                        ql_qty = ql_r.get("SBQQ__Quantity__c")
                        oi_qty = item.get("Quantity")
                        oi_credit = item.get("Credit_Amount__c")
                        expected = None
                        if prepay_credit is None:
                            status = ("✅ PASS — blank as expected" if oi_credit is None
                                      else "❌ FAIL — expected blank (QuoteLine.Prepayment_Credit__c is blank)")
                        elif not ql_qty or oi_qty is None:
                            status = "ℹ️ N/A (QuoteLine.SBQQ__Quantity__c or OrderItem.Quantity is blank)"
                        else:
                            expected = round((float(prepay_credit) / float(ql_qty)) * float(oi_qty), 2)
                            matched = oi_credit is not None and round(float(oi_credit), 2) == expected
                            status = "✅ PASS — Credit Amount matched" if matched else "❌ FAIL — Credit Amount not matched"
                        orderitem_results.append({
                            "#": "—",
                            "Validation": f"Credit_Amount__c — {p2_name}",
                            "Details": (f"QuoteLine.Prepayment_Credit__c: {fmt_amount(prepay_credit)} | "
                                        f"QuoteLine.SBQQ__Quantity__c: {ql_qty if ql_qty is not None else '(blank)'} | "
                                        f"OrderItem.Quantity: {oi_qty if oi_qty is not None else '(blank)'} | "
                                        f"OrderItem.Credit_Amount__c: {fmt_amount(oi_credit)}"),
                            "Expected": fmt_amount(expected) if expected is not None else "(blank)",
                            "Actual": fmt_amount(oi_credit),
                            "Status": status,
                        })

                    # A7 — Previous_Contract_Line__c internal consistency: first comma-token of
                    # Previous_Contract_Line_Items__c, trimmed to 15 chars (:779-782)
                    for item in items_result.get("records", []):
                        p2 = item.get("Product2") or {}
                        p2_name = p2.get("Name") or "(unknown product)"
                        prev_cli_items = (item.get("Previous_Contract_Line_Items__c") or "").strip()
                        prev_cli = (item.get("Previous_Contract_Line__c") or "").strip()
                        if not prev_cli_items:
                            status = "ℹ️ N/A (Previous_Contract_Line_Items__c is blank)"
                            expected = ""
                        else:
                            expected = prev_cli_items.split(",")[0].strip()[:15]
                            matched = prev_cli == expected
                            status = ("✅ PASS — Previous_Contract_Line__c matched" if matched
                                      else "❌ FAIL — Previous_Contract_Line__c not matched")
                        orderitem_results.append({
                            "#": "—",
                            "Validation": f"Previous_Contract_Line__c — {p2_name}",
                            "Details": (f"Previous_Contract_Line_Items__c: {prev_cli_items or '(blank)'} | "
                                        f"Previous_Contract_Line__c: {prev_cli or '(blank)'}"),
                            "Expected": expected or "(blank)", "Actual": prev_cli or "(blank)",
                            "Status": status,
                        })

                    # A8 — RBOB_ACV__c / Renewal_Target_Amount_ACV__c / PromoDiscTCV__c /
                    # Oppty_Trade_Up_Discount__c = Opportunity_Product__r.<field> * qtyFactor,
                    # Revenue orders only (:823-829)
                    if sf_order_type == "Revenue":
                        for item in items_result.get("records", []):
                            p2 = item.get("Product2") or {}
                            p2_name = p2.get("Name") or "(unknown product)"
                            oli_r = item.get("Opportunity_Product__r")
                            oi_qty = item.get("Quantity")
                            if not oli_r:
                                orderitem_results.append({
                                    "#": "—",
                                    "Validation": f"ACV Fields (RBOB/Renewal/Promo/TradeUp) — {p2_name}",
                                    "Details": "Opportunity_Product__c is blank — cannot independently verify these fields",
                                    "Expected": "—", "Actual": "—",
                                    "Status": "ℹ️ N/A (Opportunity_Product__c is blank)",
                                })
                                continue
                            oli_qty = oli_r.get("Quantity")
                            qty_factor = (float(oi_qty) / float(oli_qty)
                                          if (oi_qty not in (None, 0) and oli_qty not in (None, 0)) else 1.0)
                            for _fld, _oli_fld, _label in (
                                ("RBOB_ACV__c", "RBOBACV__c", "RBOB ACV"),
                                ("Renewal_Target_Amount_ACV__c", "Renewal_Target_Amount__c", "Renewal Target Amount ACV"),
                                ("PromoDiscTCV__c", "PromoDiscTCV__c", "Promo Disc TCV"),
                                ("Oppty_Trade_Up_Discount__c", "Oppty_Trade_Up_Discount__c", "Trade-Up Discount"),
                            ):
                                oli_val = oli_r.get(_oli_fld)
                                oi_val = item.get(_fld)
                                expected = round(float(oli_val) * qty_factor, 2) if oli_val is not None else 0.0
                                actual = round(float(oi_val), 2) if oi_val is not None else 0.0
                                matched = actual == expected
                                orderitem_results.append({
                                    "#": "—",
                                    "Validation": f"{_label} — {p2_name}",
                                    "Details": (f"Opportunity_Product__r.{_oli_fld}: {fmt_amount(oli_val)} × qtyFactor "
                                                f"({oi_qty}/{oli_qty}={qty_factor:.4f}) = {fmt_amount(expected)} | "
                                                f"OrderItem.{_fld}: {fmt_amount(oi_val)}"),
                                    "Expected": fmt_amount(expected), "Actual": fmt_amount(actual),
                                    "Status": f"✅ PASS — {_label} matched" if matched else f"❌ FAIL — {_label} not matched",
                                })

                    # A9 — ServiceDate/EndDate mirror Support_Start/End_Date__c, except on
                    # GC-Offer orders off a Renewal Opportunity, where they mirror
                    # QuoteLine.SBQQ__StartDate__c/SBQQ__EndDate__c instead (:787-793, :1310-1313)
                    _is_gc_renewal = (order_sub_type == "GC Offer" and opp_recordtype_dev_name == "Renewal_Opportunity")
                    for item in items_result.get("records", []):
                        p2 = item.get("Product2") or {}
                        p2_name = p2.get("Name") or "(unknown product)"
                        oi_service = (item.get("ServiceDate") or "")[:10]
                        oi_end = (item.get("EndDate") or "")[:10]
                        support_start = (item.get("Support_Start_Date__c") or "")[:10]
                        support_end = (item.get("Support_End_Date__c") or "")[:10]
                        ql_r = item.get("SBQQ__QuoteLine__r") or {}
                        if _is_gc_renewal:
                            exp_service = (ql_r.get("SBQQ__StartDate__c") or "")[:10]
                            exp_end = (ql_r.get("SBQQ__EndDate__c") or "")[:10]
                            source_label = "QuoteLine.SBQQ__StartDate__c/SBQQ__EndDate__c (GC Offer + Renewal Opportunity)"
                        else:
                            exp_service = support_start
                            exp_end = support_end
                            source_label = "Support_Start_Date__c/Support_End_Date__c"
                        service_match = oi_service == exp_service
                        end_match = oi_end == exp_end
                        orderitem_results.append({
                            "#": "—",
                            "Validation": f"ServiceDate — {p2_name}",
                            "Details": f"ServiceDate: {oi_service or '(blank)'} | Expected ({source_label}): {exp_service or '(blank)'}",
                            "Expected": exp_service or "(blank)", "Actual": oi_service or "(blank)",
                            "Status": "✅ PASS — ServiceDate matched" if service_match else "❌ FAIL — ServiceDate not matched",
                        })
                        orderitem_results.append({
                            "#": "—",
                            "Validation": f"EndDate — {p2_name}",
                            "Details": f"EndDate: {oi_end or '(blank)'} | Expected ({source_label}): {exp_end or '(blank)'}",
                            "Expected": exp_end or "(blank)", "Actual": oi_end or "(blank)",
                            "Status": "✅ PASS — EndDate matched" if end_match else "❌ FAIL — EndDate not matched",
                        })

                    # ── Tier B — Reference Only ────────────────────────────────────────
                    # These fields' real Apex logic depends on Custom Labels, Custom Metadata,
                    # and/or multi-hop product-hierarchy chains (e.g. SBQQ__RequiredBy__r.
                    # SBQQ__RequiredBy__r...) too fragile to hard-code as pass/fail without a
                    # real risk of confidently-wrong verdicts. Shown for manual review only —
                    # no Expected/Actual comparison is asserted.
                    _REFERENCE_ONLY_FIELDS = [
                        ("Buyer_Part_Number__c", "Buyer Part Number"),
                        ("EDI_Line_Number__c", "EDI Line Number"),
                        ("Opportunity_Product__c", "Opportunity Product"),
                        ("TPH_Quantity__c", "TPH Quantity"),
                        ("Previous_Contract_Line_Items__c", "Previous Contract Line Items"),
                        ("Licence_Type__c", "Licence Type"),
                        ("Cluster_Order_Type__c", "Cluster Order Type"),
                        ("Program__c", "Program"),
                        ("Additional_Term__c", "Additional Term"),
                        ("Surviving_Amount__c", "Surviving Amount"),
                        ("SBQQ__RequiredBy__c", "Required By"),
                        ("Has_PSTask__c", "Has PS Task"),
                        ("Task_Created__c", "Task Created"),
                        ("Global_Commit_ID__c", "Global Commit ID (OrderItem-level)"),
                        ("Global_Commit_Split_ID__c", "Global Commit Split ID"),
                        ("SBQQ__Contracted__c", "Contracted (OrderItem-level)"),
                        ("Trade_Up_SerialNumber__c", "Trade-Up Serial Number"),
                    ]
                    for item in items_result.get("records", []):
                        p2 = item.get("Product2") or {}
                        p2_name = p2.get("Name") or "(unknown product)"
                        for _fld, _label in _REFERENCE_ONLY_FIELDS:
                            _val = item.get(_fld)
                            _val_str = str(_val) if _val not in (None, "") else "(blank)"
                            orderitem_results.append({
                                "#": "—",
                                "Validation": f"{_label} (Reference Only) — {p2_name}",
                                "Details": f"{_fld}: {_val_str} — complex Apex logic, not independently validated here",
                                "Expected": "—", "Actual": _val_str,
                                "Status": f"ℹ️ {_val_str}",
                            })

                    # Validation 15 — Quote Net vs Orders Sum (per line item)
                    # Real Apex check compares QuoteLine.SBQQ__NetPrice__c to
                    # OrderItem.Sales_Price__c per line, not an order-level
                    # aggregate of Quote.SBQQ__NetAmount__c vs SUM(Order.TotalAmount).
                    for item in items_result.get("records", []):
                        _qn_p2      = item.get("Product2") or {}
                        _qn_p2_name = _qn_p2.get("Name") or "(unknown product)"
                        _qn_order   = item.get("Sales_Price__c")
                        _qn_ql_r    = item.get("SBQQ__QuoteLine__r") or {}
                        _qn_quote   = _qn_ql_r.get("SBQQ__NetPrice__c")
                        if _qn_order is None or _qn_quote is None:
                            _qn_status = "ℹ️ N/A (Sales_Price__c or QuoteLine.SBQQ__NetPrice__c is blank)"
                            _qn_matched = None
                        else:
                            _qn_matched = round(float(_qn_order), 2) == round(float(_qn_quote), 2)
                            _qn_status = "✅ PASS — Net Price matched" if _qn_matched else "❌ FAIL — Net Price not matched"
                        orderitem_results.append({"#": "—", "Validation": f"Quote Net vs Orders Sum — {_qn_p2_name}",
                                                   "Details": f"OrderItem.Sales_Price__c: {fmt_amount(_qn_order) if _qn_order is not None else '(blank)'} | "
                                                              f"QuoteLine.SBQQ__NetPrice__c: {fmt_amount(_qn_quote) if _qn_quote is not None else '(blank)'}",
                                                   "Expected": fmt_amount(_qn_quote) if _qn_quote is not None else "(blank)",
                                                   "Actual": fmt_amount(_qn_order) if _qn_order is not None else "(blank)",
                                                   "Status": _qn_status})

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
                    # Applies to all order sub-types including GC Offer.
                    _ent_rows    = []
                    _ent_records = _ent_prefetched.get("records", [])

                    from collections import Counter
                    _mfg_osi_counts = Counter(
                        (e.get("Order_Service_Item__c") or "")
                        for e in _ent_records
                        if (e.get("Type") or "").strip() == "Manufacturing Entitlement"
                    )

                    # Serialized hardware line items create one Phone Support Entitlement
                    # per unit (each Quantity__c = 1) — Order_Quantity__c reflects the
                    # whole line, so Quantity must be validated as the SUM of all
                    # entitlements sharing the same Order_Service_Item__c, not per-record.
                    _phone_osi_qty_sum = {}
                    for _e in _ent_records:
                        if (_e.get("Type") or "").strip() != "Phone Support":
                            continue
                        _osi_id = _e.get("Order_Service_Item__c") or ""
                        try:
                            _q = float(_e.get("Quantity__c") or 0)
                        except (TypeError, ValueError):
                            _q = 0
                        _phone_osi_qty_sum[_osi_id] = _phone_osi_qty_sum.get(_osi_id, 0) + _q

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
                        # ASPEN orders prefer Support_Term__c over SBQQ__SubscriptionTerm__c,
                        # but fall back to SBQQ__SubscriptionTerm__c when Support_Term__c isn't
                        # set — same fallback pattern used for OrderItem Support End Date.
                        if (order_process_type or "").strip().upper() == "ASPEN" and _osi_r.get("Support_Term__c") is not None:
                            _osi_sub_term_field = "Support_Term__c"
                            _osi_sub_term        = _term_str_ent(_osi_r.get("Support_Term__c"))
                        else:
                            _osi_sub_term_field = "SBQQ__SubscriptionTerm__c"
                            _osi_sub_term        = _term_str_ent(_osi_r.get("SBQQ__SubscriptionTerm__c"))
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
                            if order_sub_type != "GC Offer":
                                _ent_rows.append({
                                    "#": "—", "Validation": f"Subscription Term — {_ent_name}",
                                    "Details":  (f"Entitlement.Subscription_Term__c: {_ent_sub_term or '(blank)'} | Order_Service_Item__r.{_osi_sub_term_field}: {_osi_sub_term or '(blank)'}"),
                                    "Expected": _osi_sub_term or "(blank)", "Actual": _ent_sub_term or "(blank)",
                                    "Status":   "✅ PASS — Subscription Term matched" if _ent_sub_term == _osi_sub_term else "❌ FAIL — Subscription Term not matched",
                                })
                            _ent_osi_id    = _ent.get("Order_Service_Item__c") or ""
                            _osi_qty_total = _term_str_ent(_phone_osi_qty_sum.get(_ent_osi_id))
                            _ent_rows.append({
                                "#": "—", "Validation": f"Quantity — {_ent_name}",
                                "Details":  (f"Entitlement.Quantity__c: {_ent_qty or '(blank)'} "
                                             f"(SUM across all Entitlements on this line: {_osi_qty_total or '(blank)'}) | "
                                             f"Entitlement.Order_Quantity__c: {_ord_qty or '(blank)'}"),
                                "Expected": _ord_qty or "(blank)", "Actual": _osi_qty_total or "(blank)",
                                "Status":   "✅ PASS — Quantity matched" if _osi_qty_total == _ord_qty else "❌ FAIL — Quantity not matched",
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

                            # Validation 3: Quantity__c must be > 0
                            _mfg_qty_val  = bk_safe_float(_ent.get("Quantity__c"))
                            _mfg_qty_pass = _mfg_qty_val is not None and _mfg_qty_val > 0
                            _ent_rows.append({
                                "#":          "—",
                                "Validation": f"MFG Ent Quantity — {_ent_name}",
                                "Details":    f"Entitlement.Quantity__c: {_ent_qty or '(blank)'} | Expected: > 0",
                                "Expected":   "> 0",
                                "Actual":     _ent_qty or "(blank)",
                                "Status":     "✅ PASS — MFG Ent Quantity > 0" if _mfg_qty_pass else "❌ FAIL — MFG Ent Quantity is blank or not greater than 0",
                            })

                            # Validation 4: AccountId must match the Order's AccountId
                            _ent_acct_id   = (_ent.get("AccountId") or "").strip()
                            _mfg_acct_pass = _ent_acct_id == order_account_id
                            _ent_rows.append({
                                "#":          "—",
                                "Validation": f"MFG Ent Account Match — {_ent_name}",
                                "Details":    f"Entitlement.AccountId: {_ent_acct_id or '(blank)'} | Order.AccountId: {order_account_id or '(blank)'}",
                                "Expected":   order_account_id or "(blank)",
                                "Actual":     _ent_acct_id or "(blank)",
                                "Status":     "✅ PASS — Account matched" if _mfg_acct_pass else "❌ FAIL — Account does not match Order",
                            })

                            # Validation 5: Manufacturing_Integration_Partner__c must match the Order's
                            _ent_mfg_partner   = (_ent.get("Manufacturing_Integration_Partner__c") or "").strip()
                            _mfg_partner_pass  = _ent_mfg_partner == order_mfg_partner
                            _ent_rows.append({
                                "#":          "—",
                                "Validation": f"MFG Ent Partner Match — {_ent_name}",
                                "Details":    (f"Entitlement.Manufacturing_Integration_Partner__c: {_ent_mfg_partner or '(blank)'} | "
                                               f"Order.Manufacturing_Integration_Partner__c: {order_mfg_partner or '(blank)'}"),
                                "Expected":   order_mfg_partner or "(blank)",
                                "Actual":     _ent_mfg_partner or "(blank)",
                                "Status":     "✅ PASS — Manufacturing Integration Partner matched" if _mfg_partner_pass else "❌ FAIL — Manufacturing Integration Partner does not match Order",
                            })

                            # Validation 6: StartDate/EndDate must be populated once the Order has shipped
                            _ent_start      = _ent.get("StartDate")
                            _ent_end        = _ent.get("EndDate")
                            _mfg_dates_pass = order_status != "Shipped" or (bool(_ent_start) and bool(_ent_end))
                            _ent_rows.append({
                                "#":          "—",
                                "Validation": f"MFG Ent Start/End Date — {_ent_name}",
                                "Details":    (f"Order.Order_Status__c: {order_status or '(blank)'} | "
                                               f"StartDate: {_ent_start or '(blank)'} | EndDate: {_ent_end or '(blank)'}"),
                                "Expected":   "Populated once Shipped",
                                "Actual":     f"{_ent_start or '(blank)'} / {_ent_end or '(blank)'}",
                                "Status":     "✅ PASS — Dates OK for current ship status" if _mfg_dates_pass else "❌ FAIL — Order Shipped but StartDate/EndDate still blank",
                            })

                            # Validation 7: at most one Manufacturing Entitlement per Order_Service_Item__c
                            _ent_osi        = _ent.get("Order_Service_Item__c") or ""
                            _mfg_dupe_count = _mfg_osi_counts.get(_ent_osi, 0)
                            _mfg_unique_pass = _mfg_dupe_count <= 1
                            _ent_rows.append({
                                "#":          "—",
                                "Validation": f"MFG Ent Unique Per Order Line — {_ent_name}",
                                "Details":    f"Order_Service_Item__c: {_ent_osi or '(blank)'} | Manufacturing Entitlements on this line: {_mfg_dupe_count}",
                                "Expected":   "1",
                                "Actual":     str(_mfg_dupe_count),
                                "Status":     "✅ PASS — Unique per order line" if _mfg_unique_pass else "❌ FAIL — Duplicate Manufacturing Entitlements on the same order line",
                            })

                    # ── Scale_Entitlement__c (LinkedAssets) query & field-consistency rows ──
                    _KNOWN_ENT_TYPES  = ("Phone Support", "Manufacturing Entitlement")
                    _KNOWN_SCALE_TYPES = ("Non-Scale", "Scale")
                    _KNOWN_SUB_TYPES   = ("", "Third Party")
                    _KNOWN_RENEWAL_CATEGORIES = ("Renewed", "Refreshed", "Converted", "Churn", "Replaced", "Upgraded")
                    _KNOWN_STATUS_VALUES = ("Valid", "Invalid")

                    _scale_rows    = []
                    _scale_records = _scale_ent_prefetched.get("records", [])

                    for _sc in _scale_records:
                        _sc_name       = _sc.get("Name") or "(unknown)"
                        _sc_type       = (_sc.get("Type__c") or "").strip()
                        _sc_sub_type   = (_sc.get("Sub_Type__c") or "").strip()
                        _sc_asset      = (_sc.get("Asset__c") or "").strip()
                        _sc_asset_r    = _sc.get("Asset__r") or {}
                        _sc_req_by_li  = (_sc_asset_r.get("SBQQSC__RequiredByLineItem__c") or "").strip()
                        _sc_ent        = (_sc.get("Entitlement__c") or "").strip()
                        _sc_ent_r      = _sc.get("Entitlement__r") or {}
                        _sc_ent_type   = (_sc_ent_r.get("Type") or "").strip()
                        _sc_ent_cli    = (_sc_ent_r.get("ContractLineItemId") or "").strip()
                        _sc_cli        = (_sc.get("Contract_Line_Item__c") or "").strip()
                        _sc_renewal_cat = (_sc.get("Renewal_Category__c") or "").strip()
                        _sc_order_product = (_sc.get("Order_Product__c") or "").strip()
                        _sc_status     = (_sc.get("Status__c") or "").strip()

                        # 1. Asset Presence — Asset__c must be populated
                        _scale_rows.append({
                            "#": "—", "Validation": f"Asset Presence — {_sc_name}",
                            "Details":  f"Scale_Entitlement__c: {_sc_name} | Asset__c: {_sc_asset or '(blank)'}",
                            "Expected": "(populated)", "Actual": _sc_asset or "(blank)",
                            "Status":   "✅ PASS — Asset is linked" if _sc_asset else "❌ FAIL — Asset__c is blank",
                        })

                        # 1b. Order Product Presence — Order_Product__c must be populated
                        _scale_rows.append({
                            "#": "—", "Validation": f"Order Product Presence — {_sc_name}",
                            "Details":  f"Scale_Entitlement__c: {_sc_name} | Order_Product__c: {_sc_order_product or '(blank)'}",
                            "Expected": "(populated)", "Actual": _sc_order_product or "(blank)",
                            "Status":   "✅ PASS — Order Product is linked" if _sc_order_product else "❌ FAIL — Order_Product__c is blank",
                        })

                        # 2. Entitlement Type — must be a recognized Entitlement.Type
                        if not _sc_ent:
                            _ent_type_status = "❌ FAIL — Entitlement__c is blank"
                        elif _sc_ent_type in _KNOWN_ENT_TYPES:
                            _ent_type_status = "✅ PASS — Entitlement Type recognized"
                        else:
                            _ent_type_status = "ℹ️ INFO — Unrecognized Entitlement Type, confirm manually"
                        _scale_rows.append({
                            "#": "—", "Validation": f"Entitlement Type — {_sc_name}",
                            "Details":  f"Entitlement__c: {_sc_ent or '(blank)'} | Entitlement__r.Type: {_sc_ent_type or '(blank)'}",
                            "Expected": " / ".join(_KNOWN_ENT_TYPES), "Actual": _sc_ent_type or "(blank)",
                            "Status":   _ent_type_status,
                        })

                        # 3. Contract Line Item Match — Contract_Line_Item__c vs Entitlement__r.ContractLineItemId
                        if not _sc_cli and not _sc_ent_cli:
                            _cli_status = "ℹ️ INFO — Both Contract Line Item references are blank"
                        elif _sc_cli == _sc_ent_cli:
                            _cli_status = "✅ PASS — Contract Line Item matched"
                        else:
                            _cli_status = "❌ FAIL — Contract Line Item mismatch"
                        _scale_rows.append({
                            "#": "—", "Validation": f"Contract Line Item Match — {_sc_name}",
                            "Details":  f"Contract_Line_Item__c: {_sc_cli or '(blank)'} | Entitlement__r.ContractLineItemId: {_sc_ent_cli or '(blank)'}",
                            "Expected": _sc_ent_cli or "(blank)", "Actual": _sc_cli or "(blank)",
                            "Status":   _cli_status,
                        })

                        # 4. Type / Sub-Type — enum validity (FAIL takes priority over INFO over PASS)
                        if not _sc_type:
                            _combined_type_status = "❌ FAIL — Type__c is blank"
                        elif _sc_type not in _KNOWN_SCALE_TYPES:
                            _combined_type_status = "ℹ️ INFO — Unrecognized Type__c, confirm manually"
                        elif _sc_sub_type not in _KNOWN_SUB_TYPES:
                            _combined_type_status = "ℹ️ INFO — Unrecognized Sub_Type__c, confirm manually"
                        else:
                            _combined_type_status = "✅ PASS — Type / Sub-Type recognized"
                        _scale_rows.append({
                            "#": "—", "Validation": f"Type Sub-Type — {_sc_name}",
                            "Details":  f"Type__c: {_sc_type or '(blank)'} | Sub_Type__c: {_sc_sub_type or '(blank)'}",
                            "Expected": f"{' / '.join(_KNOWN_SCALE_TYPES)} | (blank) / Third Party", "Actual": f"{_sc_type or '(blank)'} | {_sc_sub_type or '(blank)'}",
                            "Status":   _combined_type_status,
                        })

                        # 5. RequiredByLineItem Sync — only asserted when the Apex trigger condition is met
                        if _sc_type == "Non-Scale" and not _sc_sub_type and _sc_cli and _sc_asset:
                            _sync_status = "✅ PASS — RequiredByLineItem synced" if _sc_req_by_li == _sc_cli else "❌ FAIL — RequiredByLineItem not synced"
                            _scale_rows.append({
                                "#": "—", "Validation": f"RequiredByLineItem Sync — {_sc_name}",
                                "Details":  f"Asset__r.SBQQSC__RequiredByLineItem__c: {_sc_req_by_li or '(blank)'} | Contract_Line_Item__c: {_sc_cli or '(blank)'}",
                                "Expected": _sc_cli or "(blank)", "Actual": _sc_req_by_li or "(blank)",
                                "Status":   _sync_status,
                            })

                        # 6. Renewal Category — optional field; only validate enum when populated
                        if not _sc_renewal_cat:
                            _renewal_cat_status = "✅ PASS — Renewal Category not set (no renewal/refresh/replace activity)"
                        elif _sc_renewal_cat in _KNOWN_RENEWAL_CATEGORIES:
                            _renewal_cat_status = "✅ PASS — Renewal Category recognized"
                        else:
                            _renewal_cat_status = "ℹ️ INFO — Unrecognized Renewal Category, confirm manually"
                        _scale_rows.append({
                            "#": "—", "Validation": f"Renewal Category — {_sc_name}",
                            "Details":  f"Renewal_Category__c: {_sc_renewal_cat or '(blank)'}",
                            "Expected": " / ".join(_KNOWN_RENEWAL_CATEGORIES) + " / (blank)", "Actual": _sc_renewal_cat or "(blank)",
                            "Status":   _renewal_cat_status,
                        })

                        # 7. Status — optional field; only validate enum when populated
                        if not _sc_status:
                            _status_status = "✅ PASS — Status not set"
                        elif _sc_status in _KNOWN_STATUS_VALUES:
                            _status_status = "✅ PASS — Status recognized"
                        else:
                            _status_status = "ℹ️ INFO — Unrecognized Status__c, confirm manually"
                        _scale_rows.append({
                            "#": "—", "Validation": f"Status — {_sc_name}",
                            "Details":  f"Status__c: {_sc_status or '(blank)'}",
                            "Expected": " / ".join(_KNOWN_STATUS_VALUES) + " / (blank)", "Actual": _sc_status or "(blank)",
                            "Status":   _status_status,
                        })

                    # ── ContractLineItem field-consistency rows ──
                    _cli_rows    = []
                    _cli_records = _cli_prefetched.get("records", [])

                    # Pre-pass: compute ORG-WIDE Max Commit per Global_Commit_ID__c, mirroring
                    # ContractLineItemTriggerHelper.updateCLIFieldforGCOfferLines (CSU-486), which
                    # queries ALL ContractLineItems WHERE Global_Commit_ID__c IN :gcIds with no
                    # order/contract scoping — sibling lines on other orders/contracts sharing the
                    # same Global Commit ID are included.
                    _gc_max_commit = {}
                    _gc_ids_in_scope = sorted({
                        (_c.get("Global_Commit_ID__c") or "").strip()
                        for _c in _cli_records
                        if (_c.get("Global_Commit_ID__c") or "").strip()
                    })
                    if _gc_ids_in_scope:
                        _gc_org_wide_clis = bk_soql_in(
                            ["Global_Commit_ID__c", "SBQQSC__SegmentQuantity__c",
                             "Product2.Product_Subtype__c", "Product2.License_Category__c"],
                            "ContractLineItem", "Global_Commit_ID__c", _gc_ids_in_scope, alias
                        )
                        for _gc_cli in _gc_org_wide_clis:
                            _gc_id = (_gc_cli.get("Global_Commit_ID__c") or "").strip()
                            if not _gc_id:
                                continue
                            _gc_prod = _gc_cli.get("Product2") or {}
                            if _gc_prod.get("Product_Subtype__c") == "Scale MSP" and _gc_prod.get("License_Category__c") == "SaaS":
                                _seg_qty = _gc_cli.get("SBQQSC__SegmentQuantity__c")
                                if _seg_qty is not None:
                                    _gc_max_commit[_gc_id] = max(_gc_max_commit.get(_gc_id, _seg_qty), _seg_qty)

                    for _cli in _cli_records:
                        _cli_id       = _cli.get("Id") or "(unknown)"
                        _cli_label    = f"CLI-{_cli_id[-6:]}" if _cli_id != "(unknown)" else _cli_id
                        _cli_op       = (_cli.get("SBQQSC__OrderProduct__c") or "").strip()
                        _cli_sc       = (_cli.get("ServiceContractId") or "").strip()
                        _cli_qty      = _cli.get("Quantity")
                        _cli_prod     = (_cli.get("Product2Id") or "").strip()
                        _cli_start    = _cli.get("StartDate")
                        _cli_end      = _cli.get("EndDate")
                        _cli_op_r     = _cli.get("SBQQSC__OrderProduct__r") or {}
                        _op_qty       = _cli_op_r.get("Quantity")
                        _op_prod      = (_cli_op_r.get("Product2Id") or "").strip()
                        _op_start     = _cli_op_r.get("ServiceDate")
                        _op_end       = _cli_op_r.get("EndDate")

                        # 1. Order Product Link — SBQQSC__OrderProduct__c must be populated
                        _cli_rows.append({
                            "#": "—", "Validation": f"Order Product Link — {_cli_label}",
                            "Details":  f"ContractLineItem: {_cli_label} | SBQQSC__OrderProduct__c: {_cli_op or '(blank)'}",
                            "Expected": "(populated)", "Actual": _cli_op or "(blank)",
                            "Status":   "✅ PASS — Order Product is linked" if _cli_op else "❌ FAIL — SBQQSC__OrderProduct__c is blank",
                        })

                        # 2. Service Contract Link — ServiceContractId must be populated
                        _cli_rows.append({
                            "#": "—", "Validation": f"Service Contract Link — {_cli_label}",
                            "Details":  f"ServiceContractId: {_cli_sc or '(blank)'}",
                            "Expected": "(populated)", "Actual": _cli_sc or "(blank)",
                            "Status":   "✅ PASS — Service Contract is linked" if _cli_sc else "❌ FAIL — ServiceContractId is blank",
                        })

                        # 3. Quantity Match — CLI Quantity vs SBQQSC__OrderProduct__r.Quantity
                        if _cli_qty in (None, "") and _op_qty in (None, ""):
                            _qty_status = "ℹ️ INFO — Both Quantity values are blank"
                        elif _cli_qty == _op_qty:
                            _qty_status = "✅ PASS — Quantity matched"
                        else:
                            _qty_status = "❌ FAIL — Quantity mismatch"
                        _cli_rows.append({
                            "#": "—", "Validation": f"Quantity Match — {_cli_label}",
                            "Details":  f"CLI Quantity: {_cli_qty if _cli_qty not in (None, '') else '(blank)'} | OrderItem Quantity: {_op_qty if _op_qty not in (None, '') else '(blank)'}",
                            "Expected": _op_qty if _op_qty not in (None, "") else "(blank)", "Actual": _cli_qty if _cli_qty not in (None, "") else "(blank)",
                            "Status":   _qty_status,
                        })

                        # 4. Product Match — CLI Product2Id vs SBQQSC__OrderProduct__r.Product2Id
                        if not _cli_prod and not _op_prod:
                            _prod_status = "ℹ️ INFO — Both Product references are blank"
                        elif _cli_prod == _op_prod:
                            _prod_status = "✅ PASS — Product matched"
                        else:
                            _prod_status = "❌ FAIL — Product mismatch"
                        _cli_rows.append({
                            "#": "—", "Validation": f"Product Match — {_cli_label}",
                            "Details":  f"CLI Product2Id: {_cli_prod or '(blank)'} | OrderItem Product2Id: {_op_prod or '(blank)'}",
                            "Expected": _op_prod or "(blank)", "Actual": _cli_prod or "(blank)",
                            "Status":   _prod_status,
                        })

                        # 5. Start Date Match — CLI StartDate vs SBQQSC__OrderProduct__r.ServiceDate
                        if not _cli_start and not _op_start:
                            _start_status = "ℹ️ INFO — Both Start Date values are blank"
                        elif _cli_start == _op_start:
                            _start_status = "✅ PASS — Start Date matched"
                        else:
                            _start_status = "❌ FAIL — Start Date mismatch"
                        _cli_rows.append({
                            "#": "—", "Validation": f"Start Date Match — {_cli_label}",
                            "Details":  f"CLI StartDate: {_cli_start or '(blank)'} | OrderItem ServiceDate: {_op_start or '(blank)'}",
                            "Expected": _op_start or "(blank)", "Actual": _cli_start or "(blank)",
                            "Status":   _start_status,
                        })

                        # 6. End Date Match — CLI EndDate vs SBQQSC__OrderProduct__r.EndDate
                        if not _cli_end and not _op_end:
                            _end_status = "ℹ️ INFO — Both End Date values are blank"
                        elif _cli_end == _op_end:
                            _end_status = "✅ PASS — End Date matched"
                        else:
                            _end_status = "❌ FAIL — End Date mismatch"
                        _cli_rows.append({
                            "#": "—", "Validation": f"End Date Match — {_cli_label}",
                            "Details":  f"CLI EndDate: {_cli_end or '(blank)'} | OrderItem EndDate: {_op_end or '(blank)'}",
                            "Expected": _op_end or "(blank)", "Actual": _cli_end or "(blank)",
                            "Status":   _end_status,
                        })

                        # 6b. Contract End Date Consistency — Contract_End_Date__c vs CLI EndDate
                        _cli_ced = _cli.get("Contract_End_Date__c")
                        if not _cli_ced and not _cli_end:
                            _ced_status = "ℹ️ INFO — Both Contract End Date and EndDate are blank"
                        elif _cli_ced == _cli_end:
                            _ced_status = "✅ PASS — Contract_End_Date__c matches EndDate"
                        else:
                            _ced_status = "❌ FAIL — Contract_End_Date__c does not match EndDate"
                        _cli_rows.append({
                            "#": "—", "Validation": f"Contract End Date Consistency — {_cli_label}",
                            "Details":  f"Contract_End_Date__c: {_cli_ced or '(blank)'} | EndDate: {_cli_end or '(blank)'}",
                            "Expected": _cli_end or "(blank)", "Actual": _cli_ced or "(blank)",
                            "Status":   _ced_status,
                        })

                        # 6c. Subscription Term Match — CLI Subscription_Term__c vs OrderItem SBQQ__SubscriptionTerm__c
                        _cli_term = _cli.get("Subscription_Term__c")
                        _op_term  = _cli_op_r.get("SBQQ__SubscriptionTerm__c")
                        if _cli_term in (None, "") and _op_term in (None, ""):
                            _term_status = "ℹ️ INFO — Both Subscription Term values are blank"
                        elif _cli_term == _op_term:
                            _term_status = "✅ PASS — Subscription Term matched"
                        else:
                            _term_status = "❌ FAIL — Subscription Term mismatch"
                        _cli_rows.append({
                            "#": "—", "Validation": f"Subscription Term Match — {_cli_label}",
                            "Details":  f"CLI Subscription_Term__c: {_cli_term if _cli_term not in (None, '') else '(blank)'} | OrderItem SBQQ__SubscriptionTerm__c: {_op_term if _op_term not in (None, '') else '(blank)'}",
                            "Expected": _op_term if _op_term not in (None, "") else "(blank)", "Actual": _cli_term if _cli_term not in (None, "") else "(blank)",
                            "Status":   _term_status,
                        })

                        # ── Trigger-derived field checks (ContractLineItemTriggerHelper) ──
                        _cli_prod2   = _cli.get("Product2") or {}
                        _cli_ql      = _cli.get("SBQQSC__QuoteLine__c")
                        _cli_ql_r    = _cli.get("SBQQSC__QuoteLine__r") or {}

                        # 7. TPH Fields Sync (RWD-1181) — only for 3rd-party hardware, Product_Level__c blank
                        _fam = _cli_prod2.get("Family")
                        if _fam in ("Dell", "HPE", "UCS") and not _cli_prod2.get("Product_Level__c"):
                            _tph_expected = (
                                _fam,
                                _cli_prod2.get("TPH_Models_Gen__c"),
                                _cli_prod2.get("Third_party_SKU_DRIVE_Size__c"),
                                str(_cli_qty) if _cli_qty not in (None, "") else None,
                            )
                            _tph_actual = (
                                _cli.get("TPH_OEM__c"),
                                _cli.get("TPH_Models_Gen__c"),
                                _cli.get("TPH_Drive_Size__c"),
                                _cli.get("TPH_Quantity__c"),
                            )
                            _tph_status = "✅ PASS — TPH fields synced from Product/Quantity" if _tph_expected == _tph_actual else "❌ FAIL — TPH fields do not match Product/Quantity"
                            _cli_rows.append({
                                "#": "—", "Validation": f"TPH Fields Sync — {_cli_label}",
                                "Details":  f"Family: {_fam} | Expected (OEM/Models/Drive/Qty): {_tph_expected} | Actual: {_tph_actual}",
                                "Expected": str(_tph_expected), "Actual": str(_tph_actual),
                                "Status":   _tph_status,
                            })

                        # 8/9. POT Parent Source/List Price Match (CPQ22-1159) — always copied from QuoteLine
                        _pot_src_cli = _cli.get("POT_Parent_Source__c")
                        _pot_src_ql  = _cli_ql_r.get("POT_Parent_Source__c")
                        _pot_price_cli = _cli.get("POT_Parent_List_Price__c")
                        _pot_price_ql  = _cli_ql_r.get("POT_Parent_List_Price__c")
                        if not _cli_ql:
                            _pot_src_status   = "ℹ️ INFO — No linked SBQQSC__QuoteLine__c to compare against"
                            _pot_price_status = "ℹ️ INFO — No linked SBQQSC__QuoteLine__c to compare against"
                        else:
                            _pot_src_status   = "✅ PASS — POT_Parent_Source__c matches QuoteLine" if _pot_src_cli == _pot_src_ql else "❌ FAIL — POT_Parent_Source__c mismatch"
                            _pot_price_status = "✅ PASS — POT_Parent_List_Price__c matches QuoteLine" if _pot_price_cli == _pot_price_ql else "❌ FAIL — POT_Parent_List_Price__c mismatch"
                        _cli_rows.append({
                            "#": "—", "Validation": f"POT Parent Source Match — {_cli_label}",
                            "Details":  f"CLI POT_Parent_Source__c: {_pot_src_cli or '(blank)'} | QuoteLine POT_Parent_Source__c: {_pot_src_ql or '(blank)'}",
                            "Expected": _pot_src_ql or "(blank)", "Actual": _pot_src_cli or "(blank)",
                            "Status":   _pot_src_status,
                        })
                        _cli_rows.append({
                            "#": "—", "Validation": f"POT Parent List Price Match — {_cli_label}",
                            "Details":  f"CLI POT_Parent_List_Price__c: {_pot_price_cli if _pot_price_cli not in (None, '') else '(blank)'} | QuoteLine POT_Parent_List_Price__c: {_pot_price_ql if _pot_price_ql not in (None, '') else '(blank)'}",
                            "Expected": _pot_price_ql if _pot_price_ql not in (None, "") else "(blank)", "Actual": _pot_price_cli if _pot_price_cli not in (None, "") else "(blank)",
                            "Status":   _pot_price_status,
                        })

                        # 10. AMER FED Exception Match (CPQ22-4065) — only for RSC-eligible software products
                        _ql_level    = _cli_ql_r.get("Product_Level__c")
                        _ql_type     = _cli_ql_r.get("Product_Type__c")
                        _ql_subtype  = _cli_ql_r.get("Product_Subtype__c")
                        _ql_optional = _cli_ql_r.get("SBQQ__Optional__c")
                        _ql_renewed  = _cli_ql_r.get("SBQQSC__RenewedContractLine__c")
                        _ql_renewed_r = _cli_ql_r.get("SBQQSC__RenewedContractLine__r") or {}
                        _ql_deal_ops_exc = _cli_ql_r.get("RWD_Deal_Ops_Exception__c") or ""
                        _rsc_eligible = (
                            _cli_ql
                            and _ql_level in ("Hybrid Software", "SaaS Software Addon", "Standalone Software Addon")
                            and _ql_type != "RZTDP"
                            and _ql_optional is False
                            and _ql_subtype not in ("Ondemand Sub Reserve", "Ondemand Above Reserve", "Scale MSP", "On Demand", "FEDRAMP", "E1000")
                            and _ql_type != "NAS"
                        )
                        if _rsc_eligible:
                            _amer_fed_cli = _cli.get("AMER_FED_Exception__c")
                            if _ql_renewed:
                                _amer_fed_expected = _ql_renewed_r.get("AMER_FED_Exception__c")
                                _amer_fed_status = "✅ PASS — AMER_FED_Exception__c inherited from renewed contract line" if _amer_fed_cli == _amer_fed_expected else "❌ FAIL — AMER_FED_Exception__c does not match renewed contract line"
                                _cli_rows.append({
                                    "#": "—", "Validation": f"AMER FED Exception Match — {_cli_label}",
                                    "Details":  f"SBQQSC__RenewedContractLine__c populated | Expected (from renewed line): {_amer_fed_expected} | Actual: {_amer_fed_cli}",
                                    "Expected": _amer_fed_expected, "Actual": _amer_fed_cli,
                                    "Status":   _amer_fed_status,
                                })
                            elif "AMER-FED Account quoting RSC" in _ql_deal_ops_exc:
                                _amer_fed_expected = True
                                _amer_fed_status = "✅ PASS — AMER_FED_Exception__c set for RSC deal-ops exception" if _amer_fed_cli == _amer_fed_expected else "❌ FAIL — AMER_FED_Exception__c should be true for RSC deal-ops exception"
                                _cli_rows.append({
                                    "#": "—", "Validation": f"AMER FED Exception Match — {_cli_label}",
                                    "Details":  f"RWD_Deal_Ops_Exception__c contains 'AMER-FED Account quoting RSC' | Expected: True | Actual: {_amer_fed_cli}",
                                    "Expected": True, "Actual": _amer_fed_cli,
                                    "Status":   _amer_fed_status,
                                })
                            # else: trigger does not touch AMER_FED_Exception__c in this branch — no assertion

                        # 11. Max Commit Consistency (CSU-486) — On-Demand lines vs same-order Scale MSP/SaaS max
                        _gc_id = (_cli.get("Global_Commit_ID__c") or "").strip()
                        _scale_util_id = _cli_ql_r.get("Scale_Utility_Product_Identifier__c")
                        if _gc_id and _scale_util_id in ("OND SR", "OND AR"):
                            _max_commit_cli = _cli.get("Max_Commit__c")
                            _max_commit_expected = _gc_max_commit.get(_gc_id)
                            _scope_note = "Computed org-wide from all Contract Line Items sharing this Global Commit ID (no order/contract scoping), mirroring ContractLineItemTriggerHelper.updateCLIFieldforGCOfferLines."
                            if _max_commit_expected is None:
                                _mc_status = "ℹ️ INFO — No org-wide Scale MSP/SaaS sibling to compute Max Commit from"
                            elif _max_commit_cli == _max_commit_expected:
                                _mc_status = "✅ PASS — Max_Commit__c matches org-wide Scale MSP/SaaS sibling max"
                            else:
                                _mc_status = "❌ FAIL — Max_Commit__c does not match org-wide Scale MSP/SaaS sibling max"
                            _cli_rows.append({
                                "#": "—", "Validation": f"Max Commit Consistency — {_cli_label}",
                                "Details":  f"Global_Commit_ID__c: {_gc_id} | {_scope_note} | Max_Commit__c: {_max_commit_cli if _max_commit_cli not in (None, '') else '(blank)'}",
                                "Expected": _max_commit_expected if _max_commit_expected is not None else "(blank)", "Actual": _max_commit_cli if _max_commit_cli not in (None, "") else "(blank)",
                                "Status":   _mc_status,
                            })

                        # 12. Resync Flag (REEN-63) — informational only, cannot be verified from a single snapshot
                        _resync_val = _cli.get("Resync_Line__c")
                        _renewal_qty = _cli.get("SBQQSC__RenewalQuantity__c")
                        if _resync_val:
                            _resync_detail = f"Resync_Line__c: {_resync_val} — verify manually if a recent RenewalQuantity change was expected to trigger this. SBQQSC__RenewalQuantity__c: {_renewal_qty if _renewal_qty not in (None, '') else '(blank)'}"
                        else:
                            _resync_detail = f"Resync_Line__c: (blank) | SBQQSC__RenewalQuantity__c: {_renewal_qty if _renewal_qty not in (None, '') else '(blank)'}"
                        _cli_rows.append({
                            "#": "—", "Validation": f"Resync Flag — {_cli_label}",
                            "Details":  _resync_detail,
                            "Expected": "(informational — not asserted)", "Actual": _resync_val or "(blank)",
                            "Status":   "ℹ️ INFO — " + (f"Resync_Line__c is set to '{_resync_val}'" if _resync_val else "Resync_Line__c is blank"),
                        })

                    # ── Display results ────────────────────────────────────────────────
                    # Order Success Metrics rows get their own tab — split them out of the
                    # Order Header results before computing that tab's pass/fail/info lists.
                    _is_metrics_row = lambda r: r["Validation"].startswith("Metrics —")
                    _metrics_results = [r for r in results if _is_metrics_row(r)]
                    _header_results  = [r for r in results if not _is_metrics_row(r)]

                    info_rows = [r for r in _header_results if r["Status"].startswith("ℹ️")]
                    pass_rows = [r for r in _header_results if r["Status"].startswith("✅")]
                    fail_rows = [r for r in _header_results if r["Status"].startswith("❌")]

                    def renumber(rows):
                        for i, r in enumerate(rows, start=1):
                            r["#"] = str(i)
                        return rows

                    pass_rows = renumber(pass_rows)
                    fail_rows = renumber(fail_rows)

                    # Feature #8 — Skip specific checks
                    if _skipped_check_nums:
                        fail_rows = [r for r in fail_rows if r["#"] not in _skipped_check_nums]

                    # Pin Order Type Classification → Process Type to top of Order Details
                    _pinned   = ("Order Type Classification", "Process Type")
                    info_rows = (
                        [r for r in info_rows if r["Validation"] == "Order Type Classification"] +
                        [r for r in info_rows if r["Validation"] == "Process Type"] +
                        [r for r in info_rows if r["Validation"] not in _pinned]
                    )
                    info_rows = renumber(info_rows)

                    metrics_info_rows = renumber([r for r in _metrics_results if r["Status"].startswith("ℹ️") or r["Status"].startswith("⏳")])
                    metrics_pass_rows = renumber([r for r in _metrics_results if r["Status"].startswith("✅")])
                    metrics_fail_rows = renumber([r for r in _metrics_results if r["Status"].startswith("❌")])

                    # ── Validation tabs ───────────────────────────────────────────────────
                    _tab_specs = []
                    if scope_quote_header:          _tab_specs.append(("quote_header",          "📝 Quote Header"))
                    if scope_quote_lines:           _tab_specs.append(("quote_lines",           "📝 QuoteLines"))
                    if scope_opportunity_header:    _tab_specs.append(("opportunity_header",    "🎯 Opportunity Header"))
                    if scope_opportunity_lineitems: _tab_specs.append(("opportunity_lineitems", "🎯 Opportunity Lineitems"))
                    if scope_header:    _tab_specs.append(("header",      "🔵 Order Header"))
                    if scope_items:     _tab_specs.append(("items",       "📦 OrderItem"))
                    if scope_header:    _tab_specs.append(("metrics",     "📊 Order Success Metrics"))
                    if scope_booking_header:     _tab_specs.append(("booking_header",     "🧾 Booking Header"))
                    if scope_booking_lineitems:  _tab_specs.append(("booking_lineitems",  "🧾 Booking Lineitems"))
                    if scope_contract_lineitems: _tab_specs.append(("contract_lineitems", "📄 Contract Lineitems"))
                    if scope_ent:       _tab_specs.append(("ent",         "📋 Entitlement"))
                    if scope_linked_assets:      _tab_specs.append(("linked_assets",      "🔗 LinkedAssets"))
                    if line_types:
                        _tab_specs.append(("replacement", "🔄 Replacement Order"))
                    _val_tabs = st.tabs([lbl for _, lbl in _tab_specs]) if _tab_specs else []
                    _tab_map  = {k: t for (k, _), t in zip(_tab_specs, _val_tabs)}

                    if scope_quote_header:
                        with _tab_map["quote_header"]:
                            if not quote_record:
                                st.info("No Quote linked to this Order (SBQQ__Quote__c is blank).")
                            else:
                                qh_info_rows = renumber([r for r in quote_header_results if r["Status"].startswith("ℹ️")])
                                qh_pass_rows = renumber([r for r in quote_header_results if r["Status"].startswith("✅")])
                                qh_fail_rows = renumber([r for r in quote_header_results if r["Status"].startswith("❌")])

                                st.caption(f"Quote: {quote_name}")

                                st.markdown(f"""
                                <div style="display:flex; gap:1rem; margin-bottom:1.2rem;">
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0f3460;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Total Checks</div>
                                        <div style="font-size:2rem; font-weight:700; color:#1a1a2e;">{len(qh_pass_rows) + len(qh_fail_rows)}</div>
                                    </div>
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #00b894;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Passed ✅</div>
                                        <div style="font-size:2rem; font-weight:700; color:#00b894;">{len(qh_pass_rows)}</div>
                                    </div>
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #d63031;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Failed ❌</div>
                                        <div style="font-size:2rem; font-weight:700; color:#d63031;">{len(qh_fail_rows)}</div>
                                    </div>
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0984e3;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Info ℹ️</div>
                                        <div style="font-size:2rem; font-weight:700; color:#0984e3;">{len(qh_info_rows)}</div>
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)

                                if qh_info_rows:
                                    _qh_det_col1, _qh_det_col2 = st.columns([3, 1])
                                    with _qh_det_col1:
                                        st.markdown("#### 🔵 Quote Header Details (Reference Only)")
                                    with _qh_det_col2:
                                        _show_qh_details = st.toggle(
                                            "Show Details",
                                            value=True,
                                            key=f"qh_details_toggle_{order_num}_{alias}",
                                        )
                                    if _show_qh_details:
                                        render_table(pd.DataFrame(qh_info_rows))

                                with st.expander(f"✅ Passed — {len(qh_pass_rows)} validation(s)", expanded=True):
                                    if qh_pass_rows:
                                        render_table(pd.DataFrame(qh_pass_rows))
                                    else:
                                        st.caption("No Quote Header validations passed.")

                                with st.expander(f"❌ Failed — {len(qh_fail_rows)} validation(s)", expanded=True):
                                    if qh_fail_rows:
                                        render_table(pd.DataFrame(qh_fail_rows))
                                        _copy_buttons_html(qh_fail_rows)
                                    else:
                                        st.success("All Quote Header validations passed — no failures.")

                    if scope_quote_lines:
                        with _tab_map["quote_lines"]:
                            if not quote_record:
                                st.info("No Quote linked to this Order (SBQQ__Quote__c is blank).")
                            elif not _ql_records:
                                st.info(f"No Quote Lines found for Quote {quote_name}.")
                            else:
                                ql_info_rows = renumber([r for r in quote_line_results if r["Status"].startswith("ℹ️")])
                                ql_pass_rows = renumber([r for r in quote_line_results if r["Status"].startswith("✅")])
                                ql_fail_rows = renumber([r for r in quote_line_results if r["Status"].startswith("❌")])

                                st.caption(f"Quote: {quote_name} — {len(_ql_records)} Quote Line(s)")

                                st.markdown(f"""
                                <div style="display:flex; gap:1rem; margin-bottom:1.2rem;">
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0f3460;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Total Checks</div>
                                        <div style="font-size:2rem; font-weight:700; color:#1a1a2e;">{len(ql_pass_rows) + len(ql_fail_rows)}</div>
                                    </div>
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #00b894;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Passed ✅</div>
                                        <div style="font-size:2rem; font-weight:700; color:#00b894;">{len(ql_pass_rows)}</div>
                                    </div>
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #d63031;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Failed ❌</div>
                                        <div style="font-size:2rem; font-weight:700; color:#d63031;">{len(ql_fail_rows)}</div>
                                    </div>
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0984e3;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Info ℹ️</div>
                                        <div style="font-size:2rem; font-weight:700; color:#0984e3;">{len(ql_info_rows)}</div>
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)

                                with st.expander(f"✅ Passed — {len(ql_pass_rows)} validation(s)", expanded=True):
                                    if ql_pass_rows:
                                        render_quote_line_rows(ql_pass_rows)
                                    else:
                                        st.caption("No Quote Line validations passed.")

                                with st.expander(f"❌ Failed — {len(ql_fail_rows)} validation(s)", expanded=True):
                                    if ql_fail_rows:
                                        render_quote_line_rows(ql_fail_rows)
                                        _copy_buttons_html(ql_fail_rows)
                                    else:
                                        st.success("All Quote Line validations passed — no failures.")

                                if ql_info_rows:
                                    with st.expander(f"ℹ️ Reference Only — {len(ql_info_rows)} field(s)", expanded=False):
                                        render_quote_line_rows(ql_info_rows)
                                        _ql_info_other = [r for r in ql_info_rows if not r["Validation"].startswith((
                                            "Term-Price Consistency", "Additional Discount Formula",
                                            "Net vs Regular Price Sanity", "Discount % Consistency",
                                        ))]
                                        if _ql_info_other:
                                            render_table(pd.DataFrame(_ql_info_other))

                                with st.expander(f"🔍 Raw QuoteLine Data — {len(_ql_records)} record(s) returned", expanded=False):
                                    _raw_ql_rows = []
                                    for _r in _ql_records:
                                        _r_prod = _r.get("SBQQ__Product__r") or {}
                                        _raw_ql_rows.append({
                                            "Name":                   _r.get("Name") or "(blank)",
                                            "Product":                _r_prod.get("Name") or "(blank)",
                                            "ProductCode":            _r.get("SBQQ__ProductCode__c") or "(blank)",
                                            "Quantity":               str(_r.get("SBQQ__Quantity__c") if _r.get("SBQQ__Quantity__c") is not None else "(blank)"),
                                            "ListPrice":              fmt_amount(_r.get("SBQQ__ListPrice__c")),
                                            "RegularPrice":           fmt_amount(_r.get("SBQQ__RegularPrice__c")),
                                            "CustomerPrice":          fmt_amount(_r.get("SBQQ__CustomerPrice__c")),
                                            "NetPrice":               fmt_amount(_r.get("SBQQ__NetPrice__c")),
                                            "SubscriptionTerm":       str(_r.get("SBQQ__SubscriptionTerm__c") if _r.get("SBQQ__SubscriptionTerm__c") is not None else "(blank)"),
                                            "SubscriptionPricing":    _r_prod.get("SBQQ__SubscriptionPricing__c") or "(blank)",
                                        })
                                    if _raw_ql_rows:
                                        render_table(pd.DataFrame(_raw_ql_rows))
                                    else:
                                        st.caption("No raw QuoteLine records returned.")

                    if scope_opportunity_header:
                        with _tab_map["opportunity_header"]:
                            st.info("🚧 Opportunity Header validations — logic coming soon.")

                    if scope_opportunity_lineitems:
                        with _tab_map["opportunity_lineitems"]:
                            st.info("🚧 Opportunity Lineitems validations — logic coming soon.")

                    if scope_header:
                        with _tab_map["header"]:
                            with st.expander(f"{len(info_rows)} row(s)", expanded=True):
                                if info_rows:
                                    render_table(pd.DataFrame(info_rows))
                                else:
                                    st.caption("No info rows.")

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
                                else:
                                    st.success("All validations passed — no failures.")

                    oi_fail_rows = []; oi_pass_rows = []; oi_info_rows = []

                    if scope_items:
                        with _tab_map["items"]:
                            oi_info_rows = renumber([r for r in orderitem_results if r["Status"].startswith("ℹ️")])
                            oi_pass_rows = renumber([r for r in orderitem_results if r["Status"].startswith("✅")])
                            oi_fail_rows = renumber([r for r in orderitem_results if r["Status"].startswith("❌")])

                            if _skipped_check_nums:
                                oi_fail_rows = [r for r in oi_fail_rows if r["#"] not in _skipped_check_nums]

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
                                _oi_det_col1, _oi_det_col2 = st.columns([3, 1])
                                with _oi_det_col1:
                                    st.markdown("#### 🔵 OrderItem Details")
                                with _oi_det_col2:
                                    _show_oi_details = st.toggle(
                                        "Show Details",
                                        value=True,
                                        key=f"oi_details_toggle_{order_num}_{alias}",
                                    )
                                if _show_oi_details:
                                    render_oi_rows(oi_info_rows)

                            with st.expander(f"✅ Passed — {len(oi_pass_rows)} validation(s)", expanded=True):
                                if oi_pass_rows:
                                    render_oi_rows(oi_pass_rows)
                                else:
                                    st.caption("No OrderItem validations passed.")

                            with st.expander(f"❌ Failed — {len(oi_fail_rows)} validation(s)", expanded=True):
                                if oi_fail_rows:
                                    render_oi_rows(oi_fail_rows)
                                    _copy_buttons_html(oi_fail_rows)
                                else:
                                    st.success("All OrderItem validations passed — no failures.")

                    if scope_header:
                        with _tab_map["metrics"]:
                            st.markdown(f"""
                            <div style="display:flex; gap:1rem; margin-bottom:1.2rem;">
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0f3460;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Total Checks</div>
                                    <div style="font-size:2rem; font-weight:700; color:#1a1a2e;">{len(metrics_pass_rows) + len(metrics_fail_rows)}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #00b894;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Passed ✅</div>
                                    <div style="font-size:2rem; font-weight:700; color:#00b894;">{len(metrics_pass_rows)}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #d63031;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Failed ❌</div>
                                    <div style="font-size:2rem; font-weight:700; color:#d63031;">{len(metrics_fail_rows)}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0984e3;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Info ℹ️</div>
                                    <div style="font-size:2rem; font-weight:700; color:#0984e3;">{len(metrics_info_rows)}</div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)

                            with st.expander(f"✅ Passed — {len(metrics_pass_rows)} validation(s)", expanded=True):
                                if metrics_pass_rows:
                                    render_table(pd.DataFrame(metrics_pass_rows))
                                else:
                                    st.caption("No metrics validations passed.")

                            with st.expander(f"❌ Failed — {len(metrics_fail_rows)} validation(s)", expanded=True):
                                if metrics_fail_rows:
                                    render_table(pd.DataFrame(metrics_fail_rows))
                                    _copy_buttons_html(metrics_fail_rows)
                                else:
                                    st.success("All metrics validations passed — no failures.")

                            with st.expander(f"ℹ️ Info — {len(metrics_info_rows)} item(s)", expanded=True):
                                if metrics_info_rows:
                                    render_table(pd.DataFrame(metrics_info_rows))
                                else:
                                    st.caption("No info rows.")

                    if is_rma_order or is_poc_order:
                        _bk_data      = None
                        _bk_fetch_err = None
                    else:
                        try:
                            with st.spinner("Fetching Booking data…"):
                                _bk_data = bk_fetch_booking_data(record.get("Id"), alias)
                            _bk_fetch_err = None
                        except Exception as _bk_exc:
                            _bk_data = None
                            _bk_fetch_err = str(_bk_exc)

                    # Reset per-order so a prior order's rows never leak into this one's totals
                    # when Booking Header/Lineitems are skipped (RMA/POC/no data/fetch error).
                    _bkh_rows      = []
                    _bkli_all_rows = []

                    if scope_booking_header:
                      with _tab_map["booking_header"]:
                        if is_rma_order:
                            st.info(RMA_SKIP_MSG)
                        elif is_poc_order:
                            st.info(POC_SKIP_MSG)
                        elif _bk_fetch_err:
                            st.error(f"Failed to fetch Booking data: {_bk_fetch_err}")
                        elif _bk_data is None:
                            st.info("No Booking__c record found for this Order — Booking Header validations skipped.")
                        else:
                            _bkh_rows_raw = bk_compare_booking_header(_bk_data["booking"], _bk_data["blis"])
                            _bkh_rows     = bk_rows_to_app_rows(_bkh_rows_raw)
                            _bkh_pass = renumber([r for r in _bkh_rows if r["Status"].startswith("✅")])
                            _bkh_fail = renumber([r for r in _bkh_rows if r["Status"].startswith("❌")])
                            _bkh_info = renumber([r for r in _bkh_rows if r["Status"].startswith("ℹ️")])

                            st.markdown(f"""
                            <div style="display:flex; gap:1rem; margin-bottom:1.2rem;">
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0f3460;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Total Checks</div>
                                    <div style="font-size:2rem; font-weight:700; color:#1a1a2e;">{len(_bkh_pass) + len(_bkh_fail)}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #00b894;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Passed ✅</div>
                                    <div style="font-size:2rem; font-weight:700; color:#00b894;">{len(_bkh_pass)}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #d63031;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Failed ❌</div>
                                    <div style="font-size:2rem; font-weight:700; color:#d63031;">{len(_bkh_fail)}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0984e3;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Info/NA ℹ️</div>
                                    <div style="font-size:2rem; font-weight:700; color:#0984e3;">{len(_bkh_info)}</div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)

                            with st.expander(f"✅ Passed — {len(_bkh_pass)} validation(s)", expanded=True):
                                if _bkh_pass:
                                    render_table(pd.DataFrame(_bkh_pass))
                                else:
                                    st.caption("No validations passed.")

                            with st.expander(f"❌ Failed — {len(_bkh_fail)} validation(s)", expanded=True):
                                if _bkh_fail:
                                    render_table(pd.DataFrame(_bkh_fail))
                                    _copy_buttons_html(_bkh_fail)
                                else:
                                    st.success("All validations passed — no failures.")

                            if _bkh_info:
                                with st.expander(f"ℹ️ Info / NA — {len(_bkh_info)} item(s)", expanded=False):
                                    render_table(pd.DataFrame(_bkh_info))

                    if scope_booking_lineitems:
                      with _tab_map["booking_lineitems"]:
                        if is_rma_order:
                            st.info(RMA_SKIP_MSG)
                        elif is_poc_order:
                            st.info(POC_SKIP_MSG)
                        elif _bk_fetch_err:
                            st.error(f"Failed to fetch Booking data: {_bk_fetch_err}")
                        elif _bk_data is None:
                            st.info("No Booking__c record found for this Order — Booking Lineitems validations skipped.")
                        elif not _bk_data["blis"]:
                            st.info("No Booking_Line_Item__c records found for this Booking.")
                        else:
                            _bli_sections   = []
                            _bkli_pass_tot  = 0
                            _bkli_fail_tot  = 0
                            _bkli_info_tot  = 0
                            _bkli_all_fails = []
                            for _bli in _bk_data["blis"]:
                                _bli_name  = _bli.get("Name") or _bli.get("Id")
                                _bli_type  = _bli.get("Type__c") or "Unknown"
                                _bli_rows_raw = bk_compare_bli(_bli, _bk_data)
                                _bli_rows     = renumber(bk_rows_to_app_rows(_bli_rows_raw))
                                _bli_pass = [r for r in _bli_rows if r["Status"].startswith("✅")]
                                _bli_fail = [r for r in _bli_rows if r["Status"].startswith("❌")]
                                _bli_info = [r for r in _bli_rows if r["Status"].startswith("ℹ️")]
                                _bkli_pass_tot += len(_bli_pass)
                                _bkli_fail_tot += len(_bli_fail)
                                _bkli_info_tot += len(_bli_info)
                                _bkli_all_fails.extend(_bli_fail)
                                _bli_sections.append((_bli_name, _bli_type, _bli_rows, _bli_pass, _bli_fail))
                                _bkli_all_rows.extend(_bli_rows)

                            st.markdown(f"""
                            <div style="display:flex; gap:1rem; margin-bottom:1.2rem;">
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0f3460;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Total Checks</div>
                                    <div style="font-size:2rem; font-weight:700; color:#1a1a2e;">{_bkli_pass_tot + _bkli_fail_tot}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #00b894;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Passed ✅</div>
                                    <div style="font-size:2rem; font-weight:700; color:#00b894;">{_bkli_pass_tot}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #d63031;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Failed ❌</div>
                                    <div style="font-size:2rem; font-weight:700; color:#d63031;">{_bkli_fail_tot}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0984e3;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Info/NA ℹ️</div>
                                    <div style="font-size:2rem; font-weight:700; color:#0984e3;">{_bkli_info_tot}</div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)

                            for _bli_name, _bli_type, _bli_rows, _bli_pass, _bli_fail in _bli_sections:
                                with st.expander(
                                    f"{_bli_name} ({_bli_type}) — ✅ {len(_bli_pass)} passed · ❌ {len(_bli_fail)} failed",
                                    expanded=(len(_bli_fail) > 0),
                                ):
                                    render_table(pd.DataFrame(_bli_rows))

                            if _bkli_all_fails:
                                st.markdown("#### ❌ All Booking Lineitem Failures")
                                render_table(pd.DataFrame(renumber(_bkli_all_fails)))
                                _copy_buttons_html(renumber(_bkli_all_fails))

                    if scope_contract_lineitems:
                      with _tab_map["contract_lineitems"]:
                        if is_rma_order:
                            st.info(RMA_SKIP_MSG)
                        elif is_poc_order:
                            st.info(POC_SKIP_MSG)
                        else:
                         _cli_rows_disp       = renumber(list(_cli_rows)) if _cli_rows else []
                         _cli_field_pass_rows = [r for r in _cli_rows_disp if r["Status"].startswith("✅")]
                         _cli_field_fail_rows = [r for r in _cli_rows_disp if r["Status"].startswith("❌")]
                         _cli_field_info      = sum(1 for r in _cli_rows_disp if r["Status"].startswith("ℹ️"))
                         _cli_link_pass_rows  = renumber([r for r in _cli_link_rows if r["Status"].startswith("✅")])
                         _cli_link_fail_rows  = renumber([r for r in _cli_link_rows if r["Status"].startswith("❌")])

                         if _cli_link_rows or _cli_rows_disp:
                            _combined_total = len(_cli_link_rows) + len(_cli_field_pass_rows) + len(_cli_field_fail_rows)
                            _combined_pass  = len(_cli_link_pass_rows) + len(_cli_field_pass_rows)
                            _combined_fail  = len(_cli_link_fail_rows) + len(_cli_field_fail_rows)

                            st.markdown("#### 🔗 OrderItem → Contract Line Item Link")
                            st.markdown(f"""
                            <div style="display:flex; gap:1rem; margin-bottom:1.2rem;">
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0f3460;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Total Checks</div>
                                    <div style="font-size:2rem; font-weight:700; color:#1a1a2e;">{_combined_total}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #00b894;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Passed ✅</div>
                                    <div style="font-size:2rem; font-weight:700; color:#00b894;">{_combined_pass}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #d63031;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Failed ❌</div>
                                    <div style="font-size:2rem; font-weight:700; color:#d63031;">{_combined_fail}</div>
                                </div>
                                <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                            box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0984e3;">
                                    <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Info ℹ️</div>
                                    <div style="font-size:2rem; font-weight:700; color:#0984e3;">{_cli_field_info}</div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)

                            with st.expander(f"✅ Passed — {_combined_pass} validation(s)", expanded=True):
                                if _cli_link_pass_rows:
                                    render_table(pd.DataFrame(_cli_link_pass_rows))
                                if _cli_field_pass_rows:
                                    render_contract_lineitem_rows(_cli_field_pass_rows)
                                if not _cli_link_pass_rows and not _cli_field_pass_rows:
                                    st.caption("No Contract Lineitem validations passed.")

                            with st.expander(f"❌ Failed — {_combined_fail} validation(s)", expanded=True):
                                if _cli_link_fail_rows:
                                    render_table(pd.DataFrame(_cli_link_fail_rows))
                                    _copy_buttons_html(_cli_link_fail_rows)
                                if _cli_field_fail_rows:
                                    render_contract_lineitem_rows(_cli_field_fail_rows)
                                    _copy_buttons_html(_cli_field_fail_rows)
                                if not _cli_link_fail_rows and not _cli_field_fail_rows:
                                    st.success("All Contract Lineitem validations passed — no failures.")

                            st.markdown("---")

                         if sc_ent_ready or _cli_records:
                            with st.expander(f"🔍 Raw ContractLineItem Data — {len(_cli_records)} record(s) returned", expanded=False):
                                if _cli_records:
                                    _raw_cli_rows = []
                                    for _r in _cli_records:
                                        _op_r = _r.get("SBQQSC__OrderProduct__r") or {}
                                        _raw_cli_rows.append({
                                            "Id":                              _r.get("Id") or "(blank)",
                                            "Product2.Name":                   (_r.get("Product2") or {}).get("Name") or "(blank)",
                                            "SBQQSC__OrderProduct__c":         _r.get("SBQQSC__OrderProduct__c") or "(blank)",
                                            "ServiceContractId":               _r.get("ServiceContractId") or "(blank)",
                                            "Quantity":                        str(_r.get("Quantity") if _r.get("Quantity") is not None else "(blank)"),
                                            "StartDate":                       _r.get("StartDate") or "(blank)",
                                            "EndDate":                         _r.get("EndDate") or "(blank)",
                                            "Product_Type__c":                 _r.get("Product_Type__c") or "(blank)",
                                            "Product_Subtype__c":              _r.get("Product_Subtype__c") or "(blank)",
                                            "Required_by_Product_Code__c":     _r.get("Required_by_Product_Code__c") or "(blank)",
                                            "OrderProduct.Quantity":           str(_op_r.get("Quantity") if _op_r.get("Quantity") is not None else "(blank)"),
                                            "OrderProduct.ServiceDate":        _op_r.get("ServiceDate") or "(blank)",
                                            "OrderProduct.EndDate":            _op_r.get("EndDate") or "(blank)",
                                            "Product2.Family":                 (_r.get("Product2") or {}).get("Family") or "(blank)",
                                            "TPH_OEM__c":                      _r.get("TPH_OEM__c") or "(blank)",
                                            "POT_Parent_Source__c":            _r.get("POT_Parent_Source__c") or "(blank)",
                                            "AMER_FED_Exception__c":           str(_r.get("AMER_FED_Exception__c") if _r.get("AMER_FED_Exception__c") is not None else "(blank)"),
                                            "Global_Commit_ID__c":             _r.get("Global_Commit_ID__c") or "(blank)",
                                            "Max_Commit__c":                   str(_r.get("Max_Commit__c") if _r.get("Max_Commit__c") is not None else "(blank)"),
                                            "Resync_Line__c":                  _r.get("Resync_Line__c") or "(blank)",
                                        })
                                    st.dataframe(pd.DataFrame(_raw_cli_rows), use_container_width=True)
                                else:
                                    st.info("No ContractLineItem records returned by the query.")

                            if not _cli_rows:
                                if _cli_records:
                                    st.info("ℹ️ No ContractLineItem records linked to this order — Contract Lineitem validations are N/A.")
                                else:
                                    st.info("No ContractLineItem records found for this order.")
                         else:
                            st.warning("Service Contract creation failed or yet to be create.")

                    if scope_ent:
                        with _tab_map["ent"]:
                          if is_rma_order:
                            st.info(RMA_SKIP_MSG)
                          elif is_poc_order:
                            st.info(POC_SKIP_MSG)
                          elif sc_ent_ready:
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

                            if _ent_rows:
                                _ent_rows_disp   = renumber(list(_ent_rows))
                                _ent_fail_actual = [r for r in _ent_rows_disp if r["Status"].startswith("❌")]
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
                                    else:
                                        st.success("All entitlement validations passed — no failures.")
                            elif _ent_records:
                                st.info("ℹ️ No entitlement records linked to this order — entitlement validations are N/A.")
                            else:
                                st.info("No entitlements found for this order.")
                          else:
                            st.warning("Service Contract creation failed or yet to be create.")

                    if scope_linked_assets:
                      with _tab_map["linked_assets"]:
                        if is_rma_order:
                            st.info(RMA_SKIP_MSG)
                        elif is_poc_order:
                            st.info(POC_SKIP_MSG)
                        elif sc_ent_ready:
                            with st.expander(f"🔍 Raw Scale_Entitlement__c Data — {len(_scale_records)} record(s) returned", expanded=False):
                                if _scale_records:
                                    _raw_scale_rows = []
                                    for _r in _scale_records:
                                        _asset_r = _r.get("Asset__r") or {}
                                        _ent_r   = _r.get("Entitlement__r") or {}
                                        _raw_scale_rows.append({
                                            "Name":                                    _r.get("Name") or "(blank)",
                                            "Type__c":                                 _r.get("Type__c") or "(blank)",
                                            "Sub_Type__c":                             _r.get("Sub_Type__c") or "(blank)",
                                            "Renewal_Category__c":                     _r.get("Renewal_Category__c") or "(blank)",
                                            "Status__c":                               _r.get("Status__c") or "(blank)",
                                            "Asset__c":                                _r.get("Asset__c") or "(blank)",
                                            "Asset__r.SBQQSC__RequiredByLineItem__c":  _asset_r.get("SBQQSC__RequiredByLineItem__c") or "(blank)",
                                            "Entitlement__c":                          _r.get("Entitlement__c") or "(blank)",
                                            "Entitlement__r.Name":                     _ent_r.get("Name") or "(blank)",
                                            "Entitlement__r.Type":                     _ent_r.get("Type") or "(blank)",
                                            "Entitlement__r.ContractLineItemId":       _ent_r.get("ContractLineItemId") or "(blank)",
                                            "Contract_Line_Item__c":                   _r.get("Contract_Line_Item__c") or "(blank)",
                                            "Order_Product__c":                        _r.get("Order_Product__c") or "(blank)",
                                        })
                                    st.dataframe(pd.DataFrame(_raw_scale_rows), use_container_width=True)
                                else:
                                    st.info("No Scale_Entitlement__c records returned by the query.")

                            if _scale_rows:
                                _scale_rows_disp   = renumber(list(_scale_rows))
                                _scale_fail_actual = [r for r in _scale_rows_disp if r["Status"].startswith("❌")]
                                _scale_pass  = sum(1 for r in _scale_rows_disp if r["Status"].startswith("✅"))
                                _scale_fail  = len(_scale_fail_actual)
                                _scale_info  = sum(1 for r in _scale_rows_disp if r["Status"].startswith("ℹ️"))
                                _scale_total = _scale_pass + _scale_fail
                                st.markdown(f"""
                                <div style="display:flex; gap:1rem; margin-bottom:1.2rem;">
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0f3460;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Total Checks</div>
                                        <div style="font-size:2rem; font-weight:700; color:#1a1a2e;">{_scale_total}</div>
                                    </div>
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #00b894;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Passed ✅</div>
                                        <div style="font-size:2rem; font-weight:700; color:#00b894;">{_scale_pass}</div>
                                    </div>
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #d63031;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Failed ❌</div>
                                        <div style="font-size:2rem; font-weight:700; color:#d63031;">{_scale_fail}</div>
                                    </div>
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0984e3;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Info ℹ️</div>
                                        <div style="font-size:2rem; font-weight:700; color:#0984e3;">{_scale_info}</div>
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)
                                with st.expander(f"✅ Passed — {_scale_pass} validation(s)", expanded=True):
                                    _scale_pass_rows = [r for r in _scale_rows_disp if r["Status"].startswith("✅")]
                                    if _scale_pass_rows:
                                        render_linked_asset_rows(_scale_pass_rows)
                                    else:
                                        st.caption("No LinkedAssets validations passed.")
                                with st.expander(f"❌ Failed — {_scale_fail} validation(s)", expanded=True):
                                    if _scale_fail_actual:
                                        render_linked_asset_rows(_scale_fail_actual)
                                        _copy_buttons_html(_scale_fail_actual)
                                    else:
                                        st.success("All LinkedAssets validations passed — no failures.")
                            elif _scale_records:
                                st.info("ℹ️ No Scale_Entitlement__c records linked to this order — LinkedAssets validations are N/A.")
                            else:
                                st.info("No Scale_Entitlement__c records found for this order.")
                        else:
                            st.warning("Service Contract creation failed or yet to be create.")

                    if line_types:
                        with _tab_map["replacement"]:
                            st.caption(f"Line Types: `{line_types}`  ·  Gate: `Line_Types__c != null`")
                            if not _repl_rows:
                                st.info("No replacement order data found (Previous_Transaction_Reference__c is blank on all OrderItems).")
                            else:
                                # ── Classification summary cards ───────────────────────────────
                                _full_rows    = [r for r in _repl_rows if r["Replacement Type"] == "Full"]
                                _partial_rows = [r for r in _repl_rows if r["Replacement Type"] == "Partial"]
                                _other_rows   = [r for r in _repl_rows if r["Replacement Type"] not in ("Full", "Partial")]

                                _SCENARIO_ORDER = [
                                    ("PP", "With Credits",    "PP with credit"),
                                    ("PP", "Without Credits", "PP without credit"),
                                    ("PA", "With Credits",    "PA with credit"),
                                    ("PA", "Without Credits", "PA without credit"),
                                ]

                                def _repl_section(section_rows, section_label):
                                    if not section_rows:
                                        return
                                    st.markdown(f"#### {section_label}")
                                    _classify_rows = []
                                    for _pay_p, _cr_lbl, _scen_label in _SCENARIO_ORDER:
                                        _matched = [
                                            r for r in section_rows
                                            if r["Scenario"] == f"{_pay_p} {'with credit' if _cr_lbl == 'With Credits' else 'without credit'}"
                                        ]
                                        _pay_full = "Prepay" if _pay_p == "PP" else "Pay Annual"
                                        if _matched:
                                            for _m in _matched:
                                                _classify_rows.append({
                                                    "Scenario":          _scen_label,
                                                    "Line Types":        line_types,
                                                    "Printable Product": _m["Printable Product"],
                                                    "Product Name":      _m["Product Name"],
                                                    "Payment Option":    _pay_full,
                                                    "Credit Status":     _cr_lbl,
                                                    "Credit Amount":     _m["Credit_Amount__c"],
                                                    "Status":            "✅ Matched",
                                                })
                                        else:
                                            _classify_rows.append({
                                                "Scenario":          _scen_label,
                                                "Line Types":        line_types,
                                                "Printable Product": "—",
                                                "Product Name":      "—",
                                                "Payment Option":    _pay_full,
                                                "Credit Status":     _cr_lbl,
                                                "Credit Amount":     "—",
                                                "Status":            "❌ Not Matched",
                                            })
                                    render_table(pd.DataFrame(_classify_rows))

                                if _full_rows:
                                    _repl_section(_full_rows, "🔵 Full Replacements")
                                if _partial_rows:
                                    _repl_section(_partial_rows, "🟠 Partial Replacements")
                                if _other_rows:
                                    st.markdown("#### ⚪ Other / Unknown Replacement Type")
                                    render_table(pd.DataFrame(_other_rows))

                                # ── Raw detail expander ────────────────────────────────────────
                                _detail_cols = ["#", "Replacement Type", "Scenario", "Credit Status",
                                                "Payment Option", "Prev Order", "Entitlement ID",
                                                "Credit_Amount__c", "Used Qty", "Remaining Qty",
                                                "Is Mismatched"]
                                _detail_df = pd.DataFrame(_repl_rows)[_detail_cols]
                                with st.expander(f"🔍 Raw Replacement Details — {len(_repl_rows)} item(s)", expanded=False):
                                    st.dataframe(_detail_df, use_container_width=True)

                                # ── Fulfillment Scenario Date Matching ────────────────────────────
                                _FULFILLMENT_MATRIX = _load_fulfillment_matrix()

                                # Booking date bucket
                                _booking_bucket = "Unknown"
                                if order_accepted:
                                    try:
                                        _bd_dt    = datetime.strptime(order_accepted[:10], "%Y-%m-%d").date()
                                        _today_dt = datetime.today().date()
                                        if (_bd_dt.year == _today_dt.year and
                                                _bd_dt.month == _today_dt.month):
                                            _booking_bucket = ("1st of the Month" if _bd_dt.day == 1
                                                               else "After 1st of the Month")
                                        else:
                                            _booking_bucket = "Booked in Previous Month"
                                    except (ValueError, TypeError):
                                        pass

                                def _get_scen_key(lt, pay_p, cr_lbl):
                                    lt_l   = (lt or "").lower()
                                    prefix = ("1" if "upgrade"    in lt_l else
                                              "2" if "conversion" in lt_l else None)
                                    if cr_lbl == "With Credits":
                                        suffix = "A"
                                    elif pay_p == "PP":
                                        suffix = "B"
                                    elif pay_p == "PA":
                                        suffix = "D"
                                    else:
                                        suffix = None
                                    return f"{prefix}{suffix}" if prefix and suffix else None

                                st.markdown("---")
                                st.markdown("#### 📅 Fulfillment Scenario Date Matching")
                                st.markdown(
                                    f"**Booking Date:** `{order_accepted or '—'}` &nbsp;|&nbsp; "
                                    f"**Bucket:** `{_booking_bucket}`"
                                )
                                _fs_rows = []
                                for _pay_p, _cr_lbl, _scen_label in _SCENARIO_ORDER:
                                    _has_items = any(
                                        r["Scenario"] == f"{_pay_p} {'with credit' if _cr_lbl == 'With Credits' else 'without credit'}"
                                        for r in _repl_rows
                                    )
                                    if not _has_items:
                                        continue
                                    _key = _get_scen_key(line_types, _pay_p, _cr_lbl)
                                    _mx  = _FULFILLMENT_MATRIX.get((_key, _booking_bucket)) if _key else None
                                    if _mx:
                                        _fs_rows.append({
                                            "Scenario Key":        _key,
                                            "Scenario":            _scen_label,
                                            "Booking Bucket":      _booking_bucket,
                                            "Fulfillment Date":    _mx["Fulfillment Date"],
                                            "Support Start":       _mx["Support Start"],
                                            "Support End":         _mx["Support End"],
                                            "New Ent Start":       _mx["New Ent Start"],
                                            "New Ent End":         _mx["New Ent End"],
                                            "Old Ent Termination": _mx["Old Ent Termination"],
                                        })
                                    else:
                                        _fs_rows.append({
                                            "Scenario Key":        _key or "—",
                                            "Scenario":            _scen_label,
                                            "Booking Bucket":      _booking_bucket,
                                            "Fulfillment Date":    "—",
                                            "Support Start":       "—",
                                            "Support End":         "—",
                                            "New Ent Start":       "—",
                                            "New Ent End":         "—",
                                            "Old Ent Termination": "No match in matrix",
                                        })
                                if _fs_rows:
                                    render_table(pd.DataFrame(_fs_rows))
                                else:
                                    st.info("No fulfillment scenario match — check Line Types and booking date.")

                    # ── Overall summary table (fills placeholder after Raw SF Data) ──────
                    # Rendered here (after every validation section/tab above has run) so the
                    # placeholder — created near the top of the page via st.empty() — reflects
                    # ALL sections' results, not just a subset computed earlier in the script.
                    _all = (results + orderitem_results + quote_header_results + quote_line_results + _ent_rows
                            + _cli_rows + _scale_rows + _bkh_rows + _bkli_all_rows)
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
                        _seq = 1
                        for _row in _all:
                            if _row["Status"].startswith("ℹ️"): continue
                            _all_checks.append({"#": _seq, "Validation": _row["Validation"], "Status": _row["Status"], "Actual": _row.get("Actual", "")})
                            _seq += 1
                        if _all_checks:
                            _pass_count = sum(1 for r in _all_checks if r["Status"].startswith("✅"))
                            _fail_count = sum(1 for r in _all_checks if r["Status"].startswith("❌"))
                            if st.toggle(
                                f"Show All Checks — {len(_all_checks)} total ({_pass_count} passed · {_fail_count} failed)",
                                value=False,
                                key=f"show_all_checks_{order_num}_{alias}",
                            ):
                                st.dataframe(
                                    pd.DataFrame(_all_checks),
                                    use_container_width=True,
                                    hide_index=True,
                                )

                    # ── Cross-order failures + grand totals ───────────────────────────
                    for _r in fail_rows:
                        cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "Order Header"})
                    for _r in oi_fail_rows:
                        cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "OrderItem"})
                    for _r in metrics_fail_rows:
                        cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "Order Success Metrics"})
                    for _r in _ent_rows:
                        if _r["Status"].startswith("❌"):
                            cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "Entitlement"})
                    for _r in _scale_rows:
                        if _r["Status"].startswith("❌"):
                            cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "LinkedAssets"})
                    for _r in _cli_rows:
                        if _r["Status"].startswith("❌"):
                            cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "Contract Lineitems"})
                    _order_pass   = len(pass_rows) + len(oi_pass_rows) + len(metrics_pass_rows)
                    _order_fail   = len(fail_rows) + len(oi_fail_rows) + len(metrics_fail_rows)
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

                    # ── Accumulate download data for this order ────────────────────────
                    prefix = f"{order_num} — "
                    if info_rows:    all_dl_sections[f"{prefix}Details"]   = pd.DataFrame(info_rows)
                    if pass_rows:    all_dl_sections[f"{prefix}Passed"]    = pd.DataFrame(pass_rows)
                    if fail_rows:    all_dl_sections[f"{prefix}Failed"]    = pd.DataFrame(fail_rows)
                    if oi_pass_rows: all_dl_sections[f"{prefix}OI Pass"]   = pd.DataFrame(oi_pass_rows)
                    if oi_fail_rows: all_dl_sections[f"{prefix}OI Fail"]   = pd.DataFrame(oi_fail_rows)
                    if metrics_pass_rows: all_dl_sections[f"{prefix}Metrics Pass"] = pd.DataFrame(metrics_pass_rows)
                    if metrics_fail_rows: all_dl_sections[f"{prefix}Metrics Fail"] = pd.DataFrame(metrics_fail_rows)

    # ── Post-loop: Run history + Cross-order summary ──────────────────────────
    if order_nums:
        _run_record = {
            "timestamp": datetime.now().isoformat(),
            "env":       st.session_state.get("sf_env", "QA"),
            "orders":    order_nums,
            "total":     _grand_total,
            "passed":    _grand_passed,
            "failed":    _grand_failed,
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
