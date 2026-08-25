import streamlit as st
import subprocess
import json
import io
import re
import calendar
import concurrent.futures
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

_HTML_TAG_RE = re.compile(r'<[^>]+>')

def _clean_sf(s: str) -> str:
    """Strip HTML tags (Salesforce formula/rich-text fields) and normalise whitespace."""
    return _HTML_TAG_RE.sub('', s or '').strip()

# ── Persistent data directory ─────────────────────────────────────────────────
DATA_DIR          = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE      = DATA_DIR / "history.json"
MATRIX_FILE       = DATA_DIR / "fulfillment_matrix.json"

def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except (json.JSONDecodeError, OSError):
        return default

_DEFAULT_MATRIX_ROWS = [
    {"Scenario Key": "1A", "Booking Bucket": "1st of the Month",         "Fulfillment Date": "1st of the same month",            "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "Order Fulfillment Date"},
    {"Scenario Key": "1A", "Booking Bucket": "After 1st of the Month",   "Fulfillment Date": "After 1st of the same Month",      "Support Start": "1st of the Following Month", "Support End": "End of term", "New Ent Start": "1st of the Following Month", "New Ent End": "End of term", "Old Ent Termination": "New Ent start date - 1"},
    {"Scenario Key": "1A", "Booking Bucket": "Booked in Previous Month", "Fulfillment Date": "FF on any date in following Month", "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "Order Fulfillment Date - 1"},
    {"Scenario Key": "1B", "Booking Bucket": "1st of the Month",         "Fulfillment Date": "1st of the same month",            "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of term"},
    {"Scenario Key": "1B", "Booking Bucket": "After 1st of the Month",   "Fulfillment Date": "After 1st of the same Month",      "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of term"},
    {"Scenario Key": "1B", "Booking Bucket": "Booked in Previous Month", "Fulfillment Date": "FF on any date in following Month", "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of term"},
    {"Scenario Key": "1D", "Booking Bucket": "1st of the Month",         "Fulfillment Date": "1st of the same month",            "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of Paid Term"},
    {"Scenario Key": "1D", "Booking Bucket": "After 1st of the Month",   "Fulfillment Date": "After 1st of the same Month",      "Support Start": "1st of the Following Month", "Support End": "End of term", "New Ent Start": "1st of the Following Month", "New Ent End": "End of term", "Old Ent Termination": "New Ent start date - 1"},
    {"Scenario Key": "1D", "Booking Bucket": "Booked in Previous Month", "Fulfillment Date": "FF on any date in following Month", "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of Paid Term"},
    {"Scenario Key": "2A", "Booking Bucket": "1st of the Month",         "Fulfillment Date": "1st of the same month",            "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "Order Fulfillment Date"},
    {"Scenario Key": "2A", "Booking Bucket": "After 1st of the Month",   "Fulfillment Date": "After 1st of the same Month",      "Support Start": "1st of the Following Month", "Support End": "End of term", "New Ent Start": "1st of the Following Month", "New Ent End": "End of term", "Old Ent Termination": "New Ent start date - 1"},
    {"Scenario Key": "2A", "Booking Bucket": "Booked in Previous Month", "Fulfillment Date": "FF on any date in following Month", "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "Order Fulfillment Date - 1"},
    {"Scenario Key": "2B", "Booking Bucket": "1st of the Month",         "Fulfillment Date": "1st of the same month",            "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of term"},
    {"Scenario Key": "2B", "Booking Bucket": "After 1st of the Month",   "Fulfillment Date": "After 1st of the same Month",      "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of term"},
    {"Scenario Key": "2B", "Booking Bucket": "Booked in Previous Month", "Fulfillment Date": "FF on any date in following Month", "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of term"},
    {"Scenario Key": "2D", "Booking Bucket": "1st of the Month",         "Fulfillment Date": "1st of the same month",            "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of Paid Term"},
    {"Scenario Key": "2D", "Booking Bucket": "After 1st of the Month",   "Fulfillment Date": "After 1st of the same Month",      "Support Start": "1st of the Following Month", "Support End": "End of term", "New Ent Start": "1st of the Following Month", "New Ent End": "End of term", "Old Ent Termination": "New Ent start date - 1"},
    {"Scenario Key": "2D", "Booking Bucket": "Booked in Previous Month", "Fulfillment Date": "FF on any date in following Month", "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of Paid Term"},
]

def _load_fulfillment_matrix() -> dict:
    rows = _read_json(MATRIX_FILE, _DEFAULT_MATRIX_ROWS)
    return {
        (r["Scenario Key"], r["Booking Bucket"]): {
            k: v for k, v in r.items() if k not in ("Scenario Key", "Booking Bucket")
        }
        for r in rows
    }

def _write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2))

def load_history() -> list:
    return _read_json(HISTORY_FILE, [])

def append_history(run: dict):
    history = load_history()
    history.append(run)
    _write_json(HISTORY_FILE, history[-50:])

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

st.set_page_config(page_title="Order Validation · Rubrik", page_icon="📋", layout="wide")

# ── CSS styles ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Global reset ── */
html, body, [class*="css"] {
    font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
    font-size: 14px;
    -webkit-font-smoothing: antialiased;
}
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
[data-testid="stDeployButton"] { display: none; }

/* Custom scrollbar */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: rgba(255,255,255,0.04); border-radius: 4px; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.18); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.32); }

/* ── Background ── */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewBlockContainer"],
[data-testid="stHeader"],
[data-testid="stToolbar"],
header[data-testid="stHeader"],
.main .block-container {
    background: #0c1929 !important;
}
.main .block-container { padding-top: 1.2rem !important; max-width: 1440px; }

/* Top toolbar */
[data-testid="stHeader"] * { color: #8ab4cc !important; }
[data-testid="stToolbar"] * { color: #8ab4cc !important; }

/* Main content text */
.main, .main p, .main span, .main div,
.main label, .main .stMarkdown,
[data-testid="stMarkdownContainer"] { color: #c4daea !important; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: #08111e !important;
    border-right: 1px solid rgba(255,255,255,0.07) !important;
    box-shadow: 3px 0 24px rgba(0,0,0,0.4);
}
section[data-testid="stSidebar"] * { color: #b8d4e8 !important; }
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: #eaf3fb !important;
    letter-spacing: 0.2px;
    font-size: 0.95rem !important;
}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] small,
section[data-testid="stSidebar"] .stCaption { color: #6a8fa8 !important; font-size: 0.79rem; }
section[data-testid="stSidebar"] [data-baseweb="select"] { border-radius: 8px !important; }
section[data-testid="stSidebar"] [data-baseweb="select"] * { color: #1a1a2e !important; }
section[data-testid="stSidebar"] code {
    color: #7dd3fc !important;
    background: rgba(125,211,252,0.1) !important;
    border-radius: 4px; padding: 2px 6px; font-size: 0.78rem;
}
section[data-testid="stSidebar"] .stButton > button {
    background: rgba(255,255,255,0.07);
    color: #d4e8f4 !important;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px;
    font-size: 0.83rem;
    font-weight: 500;
    transition: all 0.18s;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,0.13);
    border-color: rgba(255,255,255,0.22);
}
section[data-testid="stSidebar"] [data-testid="stSuccess"] {
    background: rgba(0,184,148,0.10) !important;
    border: 1px solid rgba(0,184,148,0.3) !important;
    border-radius: 8px; padding: 0.5rem 0.75rem;
}
section[data-testid="stSidebar"] [data-testid="stWarning"] {
    background: rgba(253,203,110,0.10) !important;
    border: 1px solid rgba(253,203,110,0.3) !important;
    border-radius: 8px; padding: 0.5rem 0.75rem;
}
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label {
    color: #b8d4e8 !important; font-size: 0.84rem;
}
/* sidebar brand strip */
.sidebar-brand {
    background: linear-gradient(135deg, #0d2240 0%, #0f3460 100%);
    margin: -1rem -1rem 1rem -1rem;
    padding: 1rem 1.2rem 0.9rem;
    border-bottom: 1px solid rgba(255,255,255,0.08);
}
.sidebar-brand-title {
    font-size: 0.95rem; font-weight: 700; color: #ffffff !important;
    letter-spacing: 0.4px; margin: 0;
}
.sidebar-brand-sub {
    font-size: 0.72rem; color: #5b87a8 !important; margin: 0.15rem 0 0;
}
/* sidebar section label */
.sidebar-section-label {
    font-size: 0.7rem; font-weight: 600; letter-spacing: 0.8px;
    text-transform: uppercase; color: #3d6680 !important;
    margin: 0.8rem 0 0.35rem;
}

/* ── App header ── */
.app-header {
    background: linear-gradient(135deg, #091d36 0%, #0d2a50 55%, #0e3868 100%);
    padding: 1.25rem 1.8rem;
    border-radius: 14px;
    margin-bottom: 1.4rem;
    box-shadow: 0 6px 28px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.07);
    display: flex; align-items: center; gap: 1.2rem;
}
.app-header-icon {
    width: 48px; height: 48px; flex-shrink: 0;
    background: linear-gradient(135deg, #0d5fa3 0%, #0984e3 100%);
    border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.5rem;
    box-shadow: 0 4px 16px rgba(9,132,227,0.35);
}
.app-header-text { flex: 1; min-width: 0; }
.app-header-text h1 {
    color: #f0f8ff !important; margin: 0;
    font-size: 1.35rem; font-weight: 700; letter-spacing: 0.2px; line-height: 1.2;
}
.app-header-text p {
    color: #6a9abb !important; margin: 0.25rem 0 0;
    font-size: 0.8rem; font-weight: 400;
}
.app-header-tags { display: flex; gap: 0.5rem; flex-wrap: wrap; flex-shrink: 0; }
.app-tag {
    background: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 20px; padding: 0.2rem 0.75rem;
    font-size: 0.72rem; color: #88b8d4 !important; font-weight: 500; letter-spacing: 0.3px;
    white-space: nowrap;
}

/* ── Section headings ── */
h2 { color: #dceef8 !important; font-size: 1.1rem !important; font-weight: 600 !important; }
h3 {
    color: #dceef8 !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
    padding-bottom: 0.35rem;
    border-bottom: 1px solid rgba(255,255,255,0.09);
    margin-bottom: 0.75rem;
}
h4 { color: #6fa8c8 !important; font-size: 0.9rem !important; font-weight: 600 !important; }

/* ── Caption / small text ── */
.stCaption, small,
[data-testid="stCaptionContainer"] p { color: #4d7a96 !important; font-size: 0.78rem; }

/* ── Input fields ── */
[data-testid="stTextInput"] input,
[data-testid="stDateInput"] input {
    background: #12263e !important;
    border: 1px solid rgba(255,255,255,0.13) !important;
    color: #dceef8 !important;
    border-radius: 9px;
    font-size: 0.88rem;
    transition: border-color 0.18s, box-shadow 0.18s;
}
[data-testid="stTextArea"] textarea {
    background: #12263e !important;
    border: 1px solid rgba(255,255,255,0.13) !important;
    color: #dceef8 !important;
    border-radius: 10px;
    font-size: 0.88rem;
    line-height: 1.55;
    transition: border-color 0.18s, box-shadow 0.18s;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
    border-color: rgba(9,132,227,0.7) !important;
    box-shadow: 0 0 0 3px rgba(9,132,227,0.12) !important;
    outline: none;
}
[data-testid="stTextInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder { color: #2e5470 !important; font-size: 0.83rem; }
[data-testid="stTextInput"] label,
[data-testid="stDateInput"] label,
[data-testid="stSelectbox"] label,
[data-testid="stTextArea"] label {
    color: #6a9abb !important; font-weight: 600; font-size: 0.8rem;
    text-transform: uppercase; letter-spacing: 0.5px;
}
[data-baseweb="select"] { background: #12263e !important; border-radius: 9px; }
[data-baseweb="select"] * { color: #dceef8 !important; }
[data-baseweb="select"] [class*="placeholder"] { color: #2e5470 !important; }

/* ── Primary button ── */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #0c55a0 0%, #0984e3 100%);
    color: #ffffff !important;
    border: none;
    border-radius: 10px;
    padding: 0.6rem 2.5rem;
    font-weight: 600; font-size: 0.92rem; letter-spacing: 0.3px;
    box-shadow: 0 4px 18px rgba(9,132,227,0.38);
    transition: all 0.2s ease;
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #1065b4 0%, #1a95f5 100%);
    transform: translateY(-2px);
    box-shadow: 0 8px 26px rgba(9,132,227,0.48);
}
.stButton > button[kind="primary"]:active { transform: translateY(0); }
.stButton > button[kind="primary"]:disabled {
    background: #182c3e; color: #2e5470 !important;
    box-shadow: none; transform: none; cursor: not-allowed;
}

/* ── Dividers ── */
hr { border: none; border-top: 1px solid rgba(255,255,255,0.07); margin: 1.2rem 0; }

/* ── Alert boxes ── */
[data-testid="stInfo"] {
    background: rgba(9,132,227,0.09) !important;
    border-radius: 10px; border-left: 3px solid #0984e3; padding: 0.7rem 1rem;
}
[data-testid="stSuccess"] {
    background: rgba(0,184,148,0.09) !important;
    border-radius: 10px; border-left: 3px solid #00b894; padding: 0.7rem 1rem;
}
[data-testid="stWarning"] {
    background: rgba(253,203,110,0.09) !important;
    border-radius: 10px; border-left: 3px solid #fdcb6e; padding: 0.7rem 1rem;
}
[data-testid="stError"] {
    background: rgba(214,48,49,0.09) !important;
    border-radius: 10px; border-left: 3px solid #d63031; padding: 0.7rem 1rem;
}

/* ── Expander ── */
details {
    background: rgba(255,255,255,0.025) !important;
    border-radius: 11px !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    margin-bottom: 0.55rem;
    transition: border-color 0.18s;
}
details:hover { border-color: rgba(255,255,255,0.14) !important; }
details[open] { border-color: rgba(9,132,227,0.22) !important; }
details > div, details > div > div,
[data-testid="stExpander"] > div { background: transparent !important; }
summary {
    font-weight: 600; color: #c4daea !important;
    padding: 0.72rem 1rem; font-size: 0.88rem;
    cursor: pointer; letter-spacing: 0.15px; user-select: none;
}
summary:hover { color: #f0f8ff !important; }

/* ── Toggle ── */
[data-testid="stToggle"] label { color: #b0cfe4 !important; font-weight: 500; font-size: 0.87rem; }

/* ── Checkbox ── */
[data-testid="stCheckbox"] label { color: #b0cfe4 !important; font-size: 0.86rem; }

/* ── Tabs (order tabs for multi-order) ── */
[data-testid="stTabs"] [data-baseweb="tab-list"] { background: transparent !important; gap: 0.2rem; }
[data-testid="stTabs"] [data-baseweb="tab"] {
    color: #527a96 !important;
    background: transparent !important;
    border-radius: 8px 8px 0 0;
    font-size: 0.84rem; font-weight: 500;
    padding: 0.5rem 1rem;
    transition: all 0.16s;
}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {
    color: #c4daea !important;
    background: rgba(255,255,255,0.04) !important;
}
[data-testid="stTabs"] [aria-selected="true"] {
    color: #f0f8ff !important;
    background: rgba(9,132,227,0.10) !important;
    border-bottom: 2px solid #0984e3 !important;
    font-weight: 600;
}
[data-testid="stTabs"] [data-baseweb="tab-panel"] { padding-top: 0.8rem; }

/* ── Code blocks ── */
[data-testid="stCode"],
[data-testid="stCode"] > div {
    background: #091d36 !important;
    border-radius: 10px !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
}
[data-testid="stCode"] pre {
    background: #091d36 !important; color: #a8cce0 !important;
    font-family: 'Fira Code','Cascadia Code',Consolas,monospace !important;
    font-size: 0.82rem !important; line-height: 1.65 !important;
}
code {
    background: rgba(9,132,227,0.12) !important;
    color: #7dd3fc !important;
    border-radius: 4px !important; padding: 2px 6px !important; font-size: 0.83em !important;
}

/* ── Spinner ── */
[data-testid="stSpinner"] { color: #0984e3 !important; }

/* ── File uploader ── */
[data-testid="stFileUploader"] {
    background: rgba(255,255,255,0.025) !important;
    border-radius: 10px !important;
    border: 1px dashed rgba(255,255,255,0.15) !important;
    padding: 0.4rem;
}
[data-testid="stFileUploader"]:hover { border-color: rgba(9,132,227,0.4) !important; }

/* ── Dataframe ── */
[data-testid="stDataFrame"] {
    border-radius: 10px !important;
    overflow: hidden !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    box-shadow: 0 2px 12px rgba(0,0,0,0.25);
}

/* ── Dropdown ── */
[data-baseweb="popover"] {
    background: #12263e !important;
    border-radius: 10px !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    box-shadow: 0 8px 28px rgba(0,0,0,0.5) !important;
}
[data-baseweb="list-item"]:hover { background: rgba(9,132,227,0.15) !important; }

</style>
""", unsafe_allow_html=True)

# ── App header ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="app-header">
    <div class="app-header-icon">📋</div>
    <div class="app-header-text">
        <h1>Order Validation</h1>
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
    """Pre-fetch all SF data for one order — 5 concurrent SOQL queries (down from 3+2 sequential)."""

    # ── Q1: Order header + all line items in one round-trip (child subquery) ──
    soql_combined = f"""
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
        FROM Order WHERE OrderNumber = '{order_num}' LIMIT 1
    """

    # ── Q2: Order Success Metrics ─────────────────────────────────────────────
    soql_metrics = f"""
        SELECT Order_Creation_Metrics__c, Order_Booking_Metrics__c,
               Order_Provisioning_Metrics__c, Booking_Creation_Metrics__c,
               SC_creation_Metrics__c, Stage_PO_Submission_Metrics__c,
               CLI_creation_Metrics__c, Entitlement_Creation_Metrics__c, Comment__c
        FROM Order_Success_Metrics__c
        WHERE Order__r.Order_Number__c = '{order_num}' LIMIT 1
    """

    # ── Q3: Entitlements — pre-fetched in parallel to avoid a sequential round-trip ──
    soql_ent = f"""
        SELECT Name, Type, SubType__c,
               Order_Service_Item__r.Printable_Product__c,
               Product__r.Name,
               Order_Service_Item__r.Product2.Name,
               Subscription_Term__c,
               Order_Service_Item__r.SBQQ__SubscriptionTerm__c,
               Quantity__c, Order_Quantity__c
        FROM Entitlement
        WHERE Order_Service_Item__r.Order.Order_Number__c = '{order_num}'
    """

    # ── Q4: Scale_Entitlement__c — linked-asset field-consistency validation ──
    soql_scale_ent = f"""
        SELECT Name, Type__c, Sub_Type__c, Renewal_Category__c,
               Asset__c, Asset__r.SBQQSC__RequiredByLineItem__c,
               Entitlement__c, Entitlement__r.Name, Entitlement__r.Type,
               Entitlement__r.ContractLineItemId,
               Contract_Line_Item__c, Order_Product__c
        FROM Scale_Entitlement__c
        WHERE Order_Product__r.Order.Order_Number__c = '{order_num}'
    """

    # ── Q5: ContractLineItem — field-consistency validation against source OrderItem ──
    soql_cli = f"""
        SELECT Id, SBQQSC__OrderProduct__c, ServiceContractId,
               Product2Id, Product2.Name,
               Quantity, StartDate, EndDate,
               Product_Type__c, Product_Subtype__c,
               Required_by_Product_Code__c,
               SBQQSC__OrderProduct__r.Quantity,
               SBQQSC__OrderProduct__r.ServiceDate,
               SBQQSC__OrderProduct__r.EndDate,
               SBQQSC__OrderProduct__r.Product2Id,
               SBQQSC__Product__c,
               Product2.Family, Product2.Product_Level__c, Product2.TPH_Models_Gen__c, Product2.Third_party_SKU_DRIVE_Size__c,
               Product2.Product_Subtype__c, Product2.License_Category__c,
               TPH_OEM__c, TPH_Models_Gen__c, TPH_Drive_Size__c, TPH_Quantity__c,
               SBQQSC__QuoteLine__c,
               SBQQSC__QuoteLine__r.POT_Parent_Source__c, SBQQSC__QuoteLine__r.POT_Parent_List_Price__c,
               SBQQSC__QuoteLine__r.Product_Level__c, SBQQSC__QuoteLine__r.Product_Type__c, SBQQSC__QuoteLine__r.Product_Subtype__c,
               SBQQSC__QuoteLine__r.SBQQ__Optional__c,
               SBQQSC__QuoteLine__r.SBQQSC__RenewedContractLine__c, SBQQSC__QuoteLine__r.SBQQSC__RenewedContractLine__r.AMER_FED_Exception__c,
               SBQQSC__QuoteLine__r.RWD_Deal_Ops_Exception__c,
               SBQQSC__QuoteLine__r.Scale_Utility_Product_Identifier__c,
               POT_Parent_Source__c, POT_Parent_List_Price__c, AMER_FED_Exception__c,
               Global_Commit_ID__c, Max_Commit__c, SBQQSC__TerminatedDate__c, SBQQSC__SegmentQuantity__c,
               SBQQSC__RenewalQuantity__c, Resync_Line__c
        FROM ContractLineItem
        WHERE SBQQSC__OrderProduct__r.Order.Order_Number__c = '{order_num}'
    """

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as _pool:
        _fc = _pool.submit(run_sf_query, alias, soql_combined)
        _fm = _pool.submit(run_sf_query, alias, soql_metrics)
        _fe = _pool.submit(run_sf_query, alias, soql_ent)
        _fse = _pool.submit(run_sf_query, alias, soql_scale_ent)
        _fcli = _pool.submit(run_sf_query, alias, soql_cli)
        _combined = _fc.result()
        _metrics  = _fm.result()
        _ent      = _fe.result()
        _scale_ent = _fse.result()
        _cli      = _fcli.result()

    # Flatten OrderItems subquery into the same dict structure the caller expects
    _order_rec = (_combined.get("records") or [{}])[0]
    _items_sub = _order_rec.get("OrderItems") or {}
    _items = {
        "records":   _items_sub.get("records")   or [],
        "totalSize": _items_sub.get("totalSize") or 0,
        "done":      _items_sub.get("done", True),
    }

    return {
        "result":          _combined,
        "items_result":    _items,
        "metrics_result":  _metrics,
        "ent_result":      _ent,
        "scale_ent_result": _scale_ent,
        "cli_result":      _cli,
    }

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
    _collapsible = ("Product Name Match", "Payment Options Match", "Subscription Term Match", "Support Start Date", "Support End Date", "UnitPrice × Quantity", "SerialNumber vs Quantity", "Segment Label", "Quarter", "Upgraded From")
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
        ("Entitlement Type",           "Entitlement Type"),
        ("Contract Line Item Match",   "Contract Line Item Match"),
        ("Type Sub-Type",              "Type Sub-Type"),
        ("RequiredByLineItem Sync",    "RequiredByLineItem Sync"),
        ("Renewal Category",           "Renewal Category"),
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
BK_NUMERIC_TOL = 0.10

BK_BOOKING_FIELDS = [
    "Id", "Name", "Order__c", "Opportunity__c", "Status__c",
    "Order_Type__c", "Opportunity_Type__c",
    "Gross_Bookings_Total__c", "Gross_ACV_Total__c",
    "New_Expansion_TCV__c", "Gross_New_Expansion_ACV__c",
    "Subsumed_Renewal_TCV__c", "Gross_Subsumed_Renewal_ACV__c",
    "Net_Bookings_Total__c", "Net_ACV_Total__c",
    "Net_New_Expansion_TCV__c", "Net_New_Expansion_ACV__c",
    "Net_Subsumed_Renewal_TCV__c", "Net_Subsumed_Renewal_ACV__c",
]

BK_BOOKING_HEADER_CHECKS = [
    ("Gross TCV Total",            "Gross_Bookings_Total__c",       "Total_Price__c"),
    ("Gross New/Expansion TCV",    "New_Expansion_TCV__c",          "New_Expansion_TCV__c"),
    ("Gross Subsumed Renewal TCV", "Subsumed_Renewal_TCV__c",       "Subsumed_Renewal_TCV__c"),
    ("Net TCV Total",              "Net_Bookings_Total__c",         "Net_TCV_Amount__c"),
    ("Net New/Expansion TCV",      "Net_New_Expansion_TCV__c",      "Net_New_Expansion_TCV__c"),
    ("Net Renewal Subsumed TCV",   "Net_Subsumed_Renewal_TCV__c",   "Net_Subsumed_Renewal_TCV__c"),
    ("Gross ACV Total",            "Gross_ACV_Total__c",            "Gross_ACV_Amount__c"),
    ("Gross New/Expansion ACV",    "Gross_New_Expansion_ACV__c",    "Gross_New_Expansion_ACV__c"),
    ("Gross Subsumed Renewal ACV", "Gross_Subsumed_Renewal_ACV__c", "Gross_Subsumed_Renewal_ACV__c"),
    ("Net ACV Total",              "Net_ACV_Total__c",              "Net_ACV_Amount__c"),
    ("Net New/Expansion ACV",      "Net_New_Expansion_ACV__c",      "Net_New_Expansion_ACV__c"),
    ("Net Renewal Subsumed ACV",   "Net_Subsumed_Renewal_ACV__c",   "Net_Subsumed_Renewal_ACV__c"),
]

BK_BLI_FIELDS = [
    "Id", "Name", "Booking__c", "OrderProduct__c", "CCR__c", "Type__c", "Rebate__c",
    "Total_Price__c", "New_Expansion_TCV__c", "Subsumed_Renewal_TCV__c",
    "Net_TCV_Amount__c", "Net_New_Expansion_TCV__c", "Net_Subsumed_Renewal_TCV__c",
    "Gross_ACV_Amount__c", "Gross_New_Expansion_ACV__c", "Gross_Subsumed_Renewal_ACV__c",
    "Net_ACV_Amount__c", "Net_New_Expansion_ACV__c", "Net_Subsumed_Renewal_ACV__c",
    "PromoDiscTCV__c", "Oppty_Trade_Up_Discount__c", "Prepayment_Credit__c",
    "Partner_Referral_Fee__c", "Product_Name__c", "Product_Code__c",
    "Commission_Impact__c", "Impacts_Gross_Bookings__c", "Impacts_Net_Bookings__c",
]

BK_ORDER_ITEM_FIELDS = [
    "Id", "OrderId", "Quantity", "TotalPrice", "UnitPrice", "oliID__c",
    "SBQQ__QuoteLine__c", "PromoDiscTCV__c", "Oppty_Trade_Up_Discount__c",
    "Prepaid_Credit__c", "SBQQ__ProrateMultiplier__c", "Product2Id",
    "ProductID__c", "Product_Name__c",
]

BK_OLI_FIELDS = [
    "Id", "TotalPrice", "Quantity", "ACV_Amount__c", "New_Expansion_TCV__c",
    "Subsumed_Renewal_TCV__c", "New_Expansion_ACV__c", "Subsumed_Renewal_Amount__c",
    "PromoDiscTCV__c", "Oppty_Trade_Up_Discount__c", "Prepayment_Credit__c",
    "OpportunityId", "Product2Id", "SBQQ__QuoteLine__c",
]

BK_OPP_FIELDS = [
    "Id", "Name", "Amount", "ACV_Amount__c", "New_Expansion_ACV__c",
    "New_Expansion_TCV__c", "Renewal_Subsumed_TCV__c", "Renewal_ACV__c",
    "Referral_Fee_Amount__c", "CCR_Type__c",
]


def bk_safe_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def bk_safe_div(a, b):
    if b is None or b == 0 or a is None:
        return None
    return a / b


def bk_soql_in(fields, sobject, in_field, ids, alias):
    """Batch an IN(...) query at 200 ids/batch using the app's own run_sf_query."""
    out = []
    field_list = ", ".join(fields)
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        quoted = ", ".join(f"'{_id}'" for _id in batch)
        soql = f"SELECT {field_list} FROM {sobject} WHERE {in_field} IN ({quoted})"
        try:
            result = run_sf_query(alias, soql)
        except Exception:
            continue
        out.extend(result.get("records", []))
    return out


def bk_fetch_booking_data(order_id, alias):
    """Fetch Booking__c → Booking_Line_Item__c → OrderItem → OpportunityLineItem/Opportunity
    chain for a given Order Id, using entirely independent queries (no reliance on any
    data already prefetched elsewhere in the app)."""
    bk_fields = ", ".join(BK_BOOKING_FIELDS)
    bookings = run_sf_query(
        alias, f"SELECT {bk_fields} FROM Booking__c WHERE Order__c = '{order_id}'"
    ).get("records", [])
    if not bookings:
        return None

    booking = bookings[0]
    bli_fields = ", ".join(BK_BLI_FIELDS)
    blis = run_sf_query(
        alias, f"SELECT {bli_fields} FROM Booking_Line_Item__c WHERE Booking__c = '{booking['Id']}'"
    ).get("records", [])

    op_ids = [b["OrderProduct__c"] for b in blis if b.get("OrderProduct__c")]
    oi_map = {}
    if op_ids:
        ois = bk_soql_in(BK_ORDER_ITEM_FIELDS, "OrderItem", "Id", op_ids, alias)
        oi_map = {oi["Id"]: oi for oi in ois}

    oli_ids = [oi["oliID__c"] for oi in oi_map.values() if oi.get("oliID__c")]
    oli_map = {}
    ql_to_oli_map = {}
    if oli_ids:
        olis = bk_soql_in(BK_OLI_FIELDS, "OpportunityLineItem", "Id", oli_ids, alias)
        oli_map = {oli["Id"]: oli for oli in olis}

    ql_ids = [oi["SBQQ__QuoteLine__c"] for oi in oi_map.values()
              if not oi.get("oliID__c") and oi.get("SBQQ__QuoteLine__c")]
    if ql_ids:
        olis_fb = bk_soql_in(BK_OLI_FIELDS, "OpportunityLineItem", "SBQQ__QuoteLine__c", ql_ids, alias)
        for oli in olis_fb:
            ql = oli.get("SBQQ__QuoteLine__c")
            if ql:
                ql_to_oli_map[ql] = oli
            oli_map[oli["Id"]] = oli

    opp_map = {}
    opp_id = booking.get("Opportunity__c")
    if opp_id:
        opps = bk_soql_in(BK_OPP_FIELDS, "Opportunity", "Id", [opp_id], alias)
        opp_map = {o["Id"]: o for o in opps}

    return {
        "booking": booking, "blis": blis, "oi_map": oi_map,
        "oli_map": oli_map, "ql_to_oli_map": ql_to_oli_map, "opp_map": opp_map,
    }


def bk_compare_vals(sf_val, expected, label=""):
    if expected is None:
        return "ERROR", f"Cannot calculate expected value{(' for ' + label) if label else ''}"
    sf_n = bk_safe_float(sf_val)
    ex_n = bk_safe_float(expected)
    if ex_n is not None:
        sf_num = sf_n if sf_n is not None else 0.0
        diff = abs(sf_num - ex_n)
        if diff <= BK_NUMERIC_TOL:
            note = "" if sf_n is not None else "(SF null treated as 0)"
            return "PASS", note
        sf_label = f"{sf_n:.4f}" if sf_n is not None else "null"
        return "FAIL", f"SF={sf_label}  Expected={ex_n:.4f}  Δ={diff:.4f}"
    sf_s = str(sf_val) if sf_val is not None else ""
    ex_s = str(expected)
    return ("PASS", "") if sf_s == ex_s else ("FAIL", f"SF='{sf_s}'  Expected='{ex_s}'")


def bk_row(fname, api, vtype, formula, sf_val, expected, status, note):
    return dict(field_name=fname, api_name=api, validation_type=vtype, formula=formula,
                sf_value=sf_val, expected_value=expected, status=status, note=note)


def bk_compare_revenue_bli(bli, oi, oli, dist_rebate=0.0):
    # Revenue BLIs inherit the rebate from the sibling Distributor Fee BLI (their own Rebate__c is null)
    rebate = bk_safe_float(bli.get("Rebate__c")) or dist_rebate
    net_factor = (100 - rebate) * 0.01
    results = []

    def src(fname, api, oli_api):
        sf_val = bli.get(api)
        if oli is None:
            status, note = "ERROR", "OLI not found"
            expected = None
        else:
            oli_val = bk_safe_float(oli.get(oli_api))
            expected = oli_val if oli_val is not None else 0.0
            status, note = bk_compare_vals(sf_val, expected, fname)
            if oli_val is None and status == "PASS":
                note = "(OLI field null, treated as 0)"
        results.append(bk_row(fname, api, "Source", f"OLI.{oli_api}", sf_val, expected, status, note))

    def fml(fname, api, base_api):
        sf_val = bli.get(api)
        base = bk_safe_float(bli.get(base_api))
        expected = base * net_factor if base is not None else None
        status, note = bk_compare_vals(sf_val, expected, fname)
        results.append(bk_row(fname, api, "Formula", f"{base_api} * ((100 - Rebate__c) * 0.01)",
                               sf_val, expected, status, note))

    src("Gross TCV Amount",            "Total_Price__c",              "TotalPrice")
    src("Gross New/Expansion TCV",     "New_Expansion_TCV__c",        "New_Expansion_TCV__c")
    src("Gross Subsumed Renewal TCV",  "Subsumed_Renewal_TCV__c",     "Subsumed_Renewal_TCV__c")
    fml("Net TCV Amount",              "Net_TCV_Amount__c",           "Total_Price__c")
    fml("Net New/Expansion TCV",       "Net_New_Expansion_TCV__c",    "New_Expansion_TCV__c")
    fml("Net Subsumed Renewal TCV",    "Net_Subsumed_Renewal_TCV__c", "Subsumed_Renewal_TCV__c")

    src("Gross ACV Amount",            "Gross_ACV_Amount__c",            "ACV_Amount__c")
    src("Gross New/Expansion ACV",     "Gross_New_Expansion_ACV__c",     "New_Expansion_ACV__c")
    src("Gross Subsumed Renewal ACV",  "Gross_Subsumed_Renewal_ACV__c",  "Subsumed_Renewal_Amount__c")
    fml("Net ACV Amount",              "Net_ACV_Amount__c",              "Gross_ACV_Amount__c")
    fml("Net New/Expansion ACV",       "Net_New_Expansion_ACV__c",       "Gross_New_Expansion_ACV__c")
    fml("Net Subsumed Renewal ACV",    "Net_Subsumed_Renewal_ACV__c",    "Gross_Subsumed_Renewal_ACV__c")

    def prorated(fname, api, oli_api):
        sf_val = bli.get(api)
        if oli is None or oi is None:
            status, note = "ERROR", "OLI/OI not linked"
            expected = None
        else:
            oli_val = bk_safe_float(oli.get(oli_api))
            oli_num = oli_val if oli_val is not None else 0.0
            oi_qty = bk_safe_float(oi.get("Quantity"))
            oli_qty = bk_safe_float(oli.get("Quantity"))
            ratio = bk_safe_div(oi_qty, oli_qty)
            expected = oli_num * ratio if ratio is not None else 0.0
            status, note = bk_compare_vals(sf_val, expected, fname)
        results.append(bk_row(fname, api, "Formula",
                               f"OLI.{oli_api} * (OrderItem.Quantity / OLI.Quantity)",
                               sf_val, expected, status, note))

    prorated("Promo Discount TCV",     "PromoDiscTCV__c",             "PromoDiscTCV__c")
    prorated("Trade-up Credit TCV",    "Oppty_Trade_Up_Discount__c",  "Oppty_Trade_Up_Discount__c")
    prorated("Prepayment Credit TCV",  "Prepayment_Credit__c",        "Prepayment_Credit__c")

    return results


def bk_compare_prf_bli(bli, all_rev_blis):
    def rev_sum(api):
        return sum(bk_safe_float(b.get(api)) or 0.0 for b in all_rev_blis)

    results = []
    gross_tcv_total = rev_sum("Total_Price__c")

    sf_val = bli.get("Total_Price__c")
    results.append(bk_row("Gross TCV Amount", "Total_Price__c", "Source",
                           "Referral_Fee_Amount__c from Opportunity (CCR Type=PRF)",
                           sf_val, "—", "NA", "Manual verification required"))

    prf_total = bk_safe_float(bli.get("Total_Price__c"))

    def ratio_fml(fname, api, rev_api):
        sf_val = bli.get(api)
        ratio = bk_safe_div(rev_sum(rev_api), gross_tcv_total)
        expected = prf_total * ratio if (prf_total is not None and ratio is not None) else None
        status, note = bk_compare_vals(sf_val, expected, fname)
        results.append(bk_row(fname, api, "Formula",
                               f"Total_Price__c * (SUM Revenue BLI {rev_api} / SUM Revenue BLI Gross TCV)",
                               sf_val, expected, status, note))

    ratio_fml("Gross New/Expansion TCV",    "New_Expansion_TCV__c",       "New_Expansion_TCV__c")
    ratio_fml("Gross Subsumed Renewal TCV", "Subsumed_Renewal_TCV__c",    "Subsumed_Renewal_TCV__c")

    gross_map = {
        "Net TCV Amount":            ("Net_TCV_Amount__c",             "Total_Price__c"),
        "Net New/Expansion TCV":     ("Net_New_Expansion_TCV__c",      "New_Expansion_TCV__c"),
        "Net Subsumed Renewal TCV":  ("Net_Subsumed_Renewal_TCV__c",   "Subsumed_Renewal_TCV__c"),
        "Net ACV Amount":            ("Net_ACV_Amount__c",             "Gross_ACV_Amount__c"),
        "Net New/Expansion ACV":     ("Net_New_Expansion_ACV__c",      "Gross_New_Expansion_ACV__c"),
        "Net Subsumed Renewal ACV":  ("Net_Subsumed_Renewal_ACV__c",   "Gross_Subsumed_Renewal_ACV__c"),
    }

    def gross_eq_net(fname, api, gross_api):
        sf_val = bli.get(api)
        expected = bk_safe_float(bli.get(gross_api))
        status, note = bk_compare_vals(sf_val, expected, fname)
        results.append(bk_row(fname, api, "Source", gross_api, sf_val, expected, status, note))

    gross_eq_net("Net TCV Amount",           *gross_map["Net TCV Amount"])
    gross_eq_net("Net New/Expansion TCV",    *gross_map["Net New/Expansion TCV"])
    gross_eq_net("Net Subsumed Renewal TCV", *gross_map["Net Subsumed Renewal TCV"])

    oli_tcv = None
    ratio_acv = bk_safe_div(rev_sum("Gross_ACV_Amount__c"), oli_tcv)
    sf_val = bli.get("Gross_ACV_Amount__c")
    results.append(bk_row("Gross ACV Amount", "Gross_ACV_Amount__c", "Formula",
                           "Total_Price__c * (SUM Revenue BLI Gross ACV / OLI TCV Amount)",
                           sf_val, "—", "NA", "Requires OLI TCV Amount — manual verification"))

    gross_eq_net("Net ACV Amount",           *gross_map["Net ACV Amount"])
    gross_eq_net("Net New/Expansion ACV",    *gross_map["Net New/Expansion ACV"])
    gross_eq_net("Net Subsumed Renewal ACV", *gross_map["Net Subsumed Renewal ACV"])

    return results


def bk_compare_distributor_fee_bli(bli, all_rev_blis):
    rebate = bk_safe_float(bli.get("Rebate__c")) or 0.0
    factor = rebate * -0.01
    results = []

    def rev_sum(api):
        return sum(bk_safe_float(b.get(api)) or 0.0 for b in all_rev_blis)

    def gross_fml(fname, api, rev_api):
        sf_val = bli.get(api)
        base = rev_sum(rev_api)
        expected = base * factor
        status, note = bk_compare_vals(sf_val, expected, fname)
        results.append(bk_row(fname, api, "Formula", f"SUM(Revenue BLI {rev_api}) * (Rebate__c * -0.01)",
                               sf_val, expected, status, note))

    gross_fml("Gross TCV Amount",            "Total_Price__c",              "Total_Price__c")
    gross_fml("Gross New/Expansion TCV",     "New_Expansion_TCV__c",        "New_Expansion_TCV__c")
    gross_fml("Gross Subsumed Renewal TCV",  "Subsumed_Renewal_TCV__c",     "Subsumed_Renewal_TCV__c")
    gross_fml("Gross ACV Amount",            "Gross_ACV_Amount__c",         "Gross_ACV_Amount__c")
    gross_fml("Gross New/Expansion ACV",     "Gross_New_Expansion_ACV__c",  "Gross_New_Expansion_ACV__c")
    gross_fml("Gross Subsumed Renewal ACV",  "Gross_Subsumed_Renewal_ACV__c", "Gross_Subsumed_Renewal_ACV__c")

    for fname, api in [
        ("Net TCV Amount", "Net_TCV_Amount__c"),
        ("Net New/Expansion TCV", "Net_New_Expansion_TCV__c"),
        ("Net Subsumed Renewal TCV", "Net_Subsumed_Renewal_TCV__c"),
        ("Net ACV Amount", "Net_ACV_Amount__c"),
        ("Net New/Expansion ACV", "Net_New_Expansion_ACV__c"),
        ("Net Subsumed Renewal ACV", "Net_Subsumed_Renewal_ACV__c"),
    ]:
        sf_val = bli.get(api)
        results.append(bk_row(fname, api, "NA", "Not applicable for Distributor Fee BLI",
                               sf_val, "—", "NA", "Not applicable for Distributor Fee BLI"))

    return results


def bk_compare_debooking_bli(bli, oi, oli, opp):
    rebate = bk_safe_float(bli.get("Rebate__c")) or 0.0
    net_factor = (100 - rebate) * -0.01
    bli_type = (bli.get("Type__c") or "")
    is_line_based = "line" in bli_type.lower()
    results = []

    def src_or_note(fname, api, oli_api, opp_api):
        sf_val = bli.get(api)
        if is_line_based:
            expected = bk_safe_float(oli.get(oli_api)) if oli else None
            source_label = f"OLI.{oli_api} (Line Based)"
            if oli is None:
                status, note = "ERROR", "Linked OpportunityLineItem not found"
                results.append(bk_row(fname, api, "Source", source_label, sf_val, "—", status, note))
                return
        else:
            expected = bk_safe_float(opp.get(opp_api)) if opp else None
            source_label = f"Debook_Opp.{opp_api} (Amount Based)"
            if opp is None:
                status, note = "ERROR", "Linked Debooking Opportunity not found"
                results.append(bk_row(fname, api, "Source", source_label, sf_val, "—", status, note))
                return
        status, note = bk_compare_vals(sf_val, expected, fname)
        results.append(bk_row(fname, api, "Source", source_label, sf_val, expected, status, note))

    src_or_note("Gross TCV Amount",           "Total_Price__c",             "TotalPrice",               "Amount")
    src_or_note("Gross New/Expansion TCV",    "New_Expansion_TCV__c",       "New_Expansion_TCV__c",     "New_Expansion_TCV__c")
    src_or_note("Gross Subsumed Renewal TCV", "Subsumed_Renewal_TCV__c",    "Subsumed_Renewal_TCV__c",  "Renewal_Subsumed_TCV__c")

    def fml(fname, api, base_api):
        sf_val = bli.get(api)
        base = bk_safe_float(bli.get(base_api))
        expected = base * net_factor if base is not None else None
        status, note = bk_compare_vals(sf_val, expected, fname)
        results.append(bk_row(fname, api, "Formula", f"{base_api} * ((100 - Rebate__c) * -0.01)",
                               sf_val, expected, status, note))

    fml("Net TCV Amount",              "Net_TCV_Amount__c",           "Total_Price__c")
    fml("Net New/Expansion TCV",       "Net_New_Expansion_TCV__c",    "New_Expansion_TCV__c")
    fml("Net Subsumed Renewal TCV",    "Net_Subsumed_Renewal_TCV__c", "Subsumed_Renewal_TCV__c")

    src_or_note("Gross ACV Amount",           "Gross_ACV_Amount__c",           "ACV_Amount__c",              "ACV_Amount__c")
    src_or_note("Gross New/Expansion ACV",    "Gross_New_Expansion_ACV__c",    "New_Expansion_ACV__c",       "New_Expansion_ACV__c")
    src_or_note("Gross Subsumed Renewal ACV", "Gross_Subsumed_Renewal_ACV__c", "Subsumed_Renewal_Amount__c", "Renewal_Subsumed_ACV__c")

    fml("Net ACV Amount",              "Net_ACV_Amount__c",              "Gross_ACV_Amount__c")
    fml("Net New/Expansion ACV",       "Net_New_Expansion_ACV__c",       "Gross_New_Expansion_ACV__c")
    fml("Net Subsumed Renewal ACV",    "Net_Subsumed_Renewal_ACV__c",    "Gross_Subsumed_Renewal_ACV__c")

    return results


def bk_compare_booking_header(booking, blis):
    eligible = [b for b in blis if (b.get("Type__c") or "").strip() in ("Revenue", "PRF")]
    results = []
    for fname, booking_api, bli_api in BK_BOOKING_HEADER_CHECKS:
        sf_val = booking.get(booking_api)
        expected = sum(bk_safe_float(b.get(bli_api)) or 0.0 for b in eligible)
        formula = f"SUM(BLI.{bli_api} WHERE Type IN (Revenue, PRF))"
        status, note = bk_compare_vals(sf_val, expected)
        results.append(bk_row(fname, booking_api, "Formula", formula, sf_val, expected, status, note))
    return results


def bk_compare_bli(bli, data):
    bli_type = (bli.get("Type__c") or "").strip()
    oi_id = bli.get("OrderProduct__c")
    oi = data["oi_map"].get(oi_id) if oi_id else None
    oli_id = oi.get("oliID__c") if oi else None
    if oli_id:
        oli = data["oli_map"].get(oli_id)
    else:
        ql_id = oi.get("SBQQ__QuoteLine__c") if oi else None
        oli = data["ql_to_oli_map"].get(ql_id) if ql_id else None
    opp = next(iter(data["opp_map"].values()), None)
    rev_blis = [b for b in data["blis"] if (b.get("Type__c") or "").strip() == "Revenue"]
    dist_fee_blis = [b for b in data["blis"] if "distributor" in (b.get("Type__c") or "").lower()]
    dist_rebate = bk_safe_float(dist_fee_blis[0].get("Rebate__c") if dist_fee_blis else None) or 0.0

    t = bli_type.lower()
    if t == "revenue":
        return bk_compare_revenue_bli(bli, oi, oli, dist_rebate)
    elif t == "prf":
        return bk_compare_prf_bli(bli, rev_blis)
    elif "distributor" in t or "dist" in t:
        return bk_compare_distributor_fee_bli(bli, rev_blis)
    elif "debook" in t or "return" in t or "refund" in t or "amount based" in t or "line based" in t:
        return bk_compare_debooking_bli(bli, oi, oli, opp)
    else:
        return [bk_row("(All fields)", "—", "UNKNOWN", f"Unknown BLI Type: {bli_type}",
                        "—", None, "ERROR", f"No comparator implemented for type '{bli_type}'")]


def bk_status_to_row_status(status):
    """Map skill status (PASS/FAIL/NA/ERROR) → app row Status string."""
    if status == "PASS":
        return "✅ PASS"
    elif status == "FAIL":
        return "❌ FAIL"
    elif status == "NA":
        return "ℹ️ NA"
    else:
        return "ℹ️ ERROR"


def bk_rows_to_app_rows(bk_rows_list, prefix=""):
    """Convert a list of bk_row(...) dicts into the app's row schema."""
    out = []
    for r in bk_rows_list:
        expected = r["expected_value"]
        expected_str = "—" if expected is None else (
            f"{expected:.4f}" if isinstance(expected, float) else str(expected)
        )
        status_str = bk_status_to_row_status(r["status"])
        note = r.get("note") or ""
        out.append({
            "#": "—",
            "Validation": f"{prefix}{r['field_name']}",
            "Details": f"{r['validation_type']}: {r['formula']}" + (f" | {note}" if note else ""),
            "Expected": expected_str,
            "Actual": "—" if r["sf_value"] is None else r["sf_value"],
            "Status": status_str,
        })
    return out

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
                    sc_ent_ready            = bool(order_contracted) and sc_or_ent_stage == "SC Creation Successful"
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
                    primary_contact_screen_status = record.get("Primary_Contact_Screen_Status__c") or ""
                    shipping_carrier              = record.get("Shipping_Carrier__c") or ""
                    scac                          = record.get("SCAC__c") or ""
                    smart_hands_provider          = record.get("Smart_Hands_Provider__c") or ""

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
               Quantity__c, Order_Quantity__c
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

                    if sf_order_type.lower() == "poc":
                        st.info("🚧 **POC Orders logic Yet to Start**")
                        continue

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
                    # Applies to all order sub-types including GC Offer.
                    _ent_rows    = []
                    _ent_records = _ent_prefetched.get("records", [])

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
                            if order_sub_type != "GC Offer":
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

                    # ── Scale_Entitlement__c (LinkedAssets) query & field-consistency rows ──
                    _KNOWN_ENT_TYPES  = ("Phone Support", "Manufacturing Entitlement")
                    _KNOWN_SCALE_TYPES = ("Non-Scale", "Scale")
                    _KNOWN_SUB_TYPES   = ("", "Third Party")
                    _KNOWN_RENEWAL_CATEGORIES = ("Renewed", "Refreshed", "Converted", "Churn", "Replaced", "Upgraded")

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

                        # 1. Asset Presence — Asset__c must be populated
                        _scale_rows.append({
                            "#": "—", "Validation": f"Asset Presence — {_sc_name}",
                            "Details":  f"Scale_Entitlement__c: {_sc_name} | Asset__c: {_sc_asset or '(blank)'}",
                            "Expected": "(populated)", "Actual": _sc_asset or "(blank)",
                            "Status":   "✅ PASS — Asset is linked" if _sc_asset else "❌ FAIL — Asset__c is blank",
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

                    # ── ContractLineItem field-consistency rows ──
                    _cli_rows    = []
                    _cli_records = _cli_prefetched.get("records", [])

                    # Pre-pass: compute same-order Max Commit per Global_Commit_ID__c, mirroring
                    # ContractLineItemTriggerHelper.updateCLIFieldforGCOfferLines (CSU-486). Scoped to
                    # Contract Line Items already fetched for this order — sibling lines on other
                    # orders/contracts sharing the same Global Commit ID are NOT included.
                    _gc_max_commit = {}
                    for _gc_cli in _cli_records:
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
                            _scope_note = "Computed from Contract Line Items on this order only — sibling lines on other orders/contracts sharing this Global Commit ID are not included."
                            if _max_commit_expected is None:
                                _mc_status = "ℹ️ INFO — No in-order Scale MSP/SaaS sibling to compute Max Commit from"
                            elif _max_commit_cli == _max_commit_expected:
                                _mc_status = "✅ PASS — Max_Commit__c matches in-order Scale MSP/SaaS sibling max"
                            else:
                                _mc_status = "❌ FAIL — Max_Commit__c does not match in-order Scale MSP/SaaS sibling max"
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
                        _seq = 1
                        for _row in results:
                            if _row["Status"].startswith("ℹ️"): continue
                            _all_checks.append({"#": _seq, "Validation": _row["Validation"], "Status": _row["Status"], "Actual": _row.get("Actual", "")})
                            _seq += 1
                        for _row in orderitem_results:
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

                    # Pin Order Type Classification → Process Type to top of Order Details
                    _pinned   = ("Order Type Classification", "Process Type")
                    info_rows = (
                        [r for r in info_rows if r["Validation"] == "Order Type Classification"] +
                        [r for r in info_rows if r["Validation"] == "Process Type"] +
                        [r for r in info_rows if r["Validation"] not in _pinned]
                    )
                    info_rows = renumber(info_rows)

                    # ── Validation tabs ───────────────────────────────────────────────────
                    _tab_specs = []
                    if scope_header:    _tab_specs.append(("header",      "🔵 Order Header"))
                    if scope_items:     _tab_specs.append(("items",       "📦 OrderItem"))
                    if scope_booking_header:     _tab_specs.append(("booking_header",     "🧾 Booking Header"))
                    if scope_booking_lineitems:  _tab_specs.append(("booking_lineitems",  "🧾 Booking Lineitems"))
                    if scope_contract_lineitems: _tab_specs.append(("contract_lineitems", "📄 Contract Lineitems"))
                    if scope_ent:       _tab_specs.append(("ent",         "📋 Entitlement"))
                    if scope_linked_assets:      _tab_specs.append(("linked_assets",      "🔗 LinkedAssets"))
                    if line_types:
                        _tab_specs.append(("replacement", "🔄 Replacement Order"))
                    _val_tabs = st.tabs([lbl for _, lbl in _tab_specs]) if _tab_specs else []
                    _tab_map  = {k: t for (k, _), t in zip(_tab_specs, _val_tabs)}

                    if scope_header:
                        with _tab_map["header"]:
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

                    if is_rma_order:
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

                    if scope_booking_header:
                      with _tab_map["booking_header"]:
                        if is_rma_order:
                            st.info(RMA_SKIP_MSG)
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
                        elif sc_ent_ready:
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

                            if _cli_rows:
                                _cli_rows_disp   = renumber(list(_cli_rows))
                                _cli_fail_actual = [r for r in _cli_rows_disp if r["Status"].startswith("❌")]
                                _cli_pass  = sum(1 for r in _cli_rows_disp if r["Status"].startswith("✅"))
                                _cli_fail  = len(_cli_fail_actual)
                                _cli_info  = sum(1 for r in _cli_rows_disp if r["Status"].startswith("ℹ️"))
                                _cli_total = _cli_pass + _cli_fail
                                st.markdown(f"""
                                <div style="display:flex; gap:1rem; margin-bottom:1.2rem;">
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0f3460;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Total Checks</div>
                                        <div style="font-size:2rem; font-weight:700; color:#1a1a2e;">{_cli_total}</div>
                                    </div>
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #00b894;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Passed ✅</div>
                                        <div style="font-size:2rem; font-weight:700; color:#00b894;">{_cli_pass}</div>
                                    </div>
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #d63031;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Failed ❌</div>
                                        <div style="font-size:2rem; font-weight:700; color:#d63031;">{_cli_fail}</div>
                                    </div>
                                    <div style="flex:1; background:#fff; border-radius:10px; padding:1rem 1.2rem;
                                                box-shadow:0 2px 8px rgba(0,0,0,0.07); border-left:4px solid #0984e3;">
                                        <div style="font-size:0.75rem; color:#5a6a7a; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Info ℹ️</div>
                                        <div style="font-size:2rem; font-weight:700; color:#0984e3;">{_cli_info}</div>
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)
                                with st.expander(f"✅ Passed — {_cli_pass} validation(s)", expanded=True):
                                    _cli_pass_rows = [r for r in _cli_rows_disp if r["Status"].startswith("✅")]
                                    if _cli_pass_rows:
                                        render_contract_lineitem_rows(_cli_pass_rows)
                                    else:
                                        st.caption("No Contract Lineitem validations passed.")
                                with st.expander(f"❌ Failed — {_cli_fail} validation(s)", expanded=True):
                                    if _cli_fail_actual:
                                        render_contract_lineitem_rows(_cli_fail_actual)
                                        _copy_buttons_html(_cli_fail_actual)
                                    else:
                                        st.success("All Contract Lineitem validations passed — no failures.")
                            elif _cli_records:
                                st.info("ℹ️ No ContractLineItem records linked to this order — Contract Lineitem validations are N/A.")
                            else:
                                st.info("No ContractLineItem records found for this order.")
                        else:
                            st.warning("Service Contract creation failed or yet to be create.")

                    if scope_ent:
                        with _tab_map["ent"]:
                          if is_rma_order:
                            st.info(RMA_SKIP_MSG)
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


                    # ── Cross-order failures + grand totals ───────────────────────────
                    for _r in fail_rows:
                        cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "Order Header"})
                    for _r in oi_fail_rows:
                        cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "OrderItem"})
                    for _r in _ent_rows:
                        if _r["Status"].startswith("❌"):
                            cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "Entitlement"})
                    for _r in _scale_rows:
                        if _r["Status"].startswith("❌"):
                            cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "LinkedAssets"})
                    for _r in _cli_rows:
                        if _r["Status"].startswith("❌"):
                            cross_order_failures.append({"Order": order_num, "Validation": _r["Validation"], "Section": "Contract Lineitems"})
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

                    # ── Accumulate download data for this order ────────────────────────
                    prefix = f"{order_num} — "
                    if info_rows:    all_dl_sections[f"{prefix}Details"]   = pd.DataFrame(info_rows)
                    if pass_rows:    all_dl_sections[f"{prefix}Passed"]    = pd.DataFrame(pass_rows)
                    if fail_rows:    all_dl_sections[f"{prefix}Failed"]    = pd.DataFrame(fail_rows)
                    if oi_pass_rows: all_dl_sections[f"{prefix}OI Pass"]   = pd.DataFrame(oi_pass_rows)
                    if oi_fail_rows: all_dl_sections[f"{prefix}OI Fail"]   = pd.DataFrame(oi_fail_rows)

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
