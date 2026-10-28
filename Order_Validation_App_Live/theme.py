"""Shared dark theme for the Streamlit pages.

All page CSS lives here so it can be maintained in one place. Each page calls
apply_theme("<page>") right after st.set_page_config(); apply_theme must not run
before it, because set_page_config has to be the first Streamlit call.

The CSS for each page is the same as it was when it was inlined in that page:
  - "main"  : the Order Validation page (its own large stylesheet).
  - "po", "soql", "edi" : the embed pages, assembled from the shared fragments
    below plus a few page-specific rules.
css_for(page) returns the stylesheet text without touching Streamlit.

  - "devconsole" : the Developer Console page: the "main" stylesheet plus a few
    rules for main-area secondary/download buttons.
"""

import streamlit as st

# ── Shared fragments (used by the embed pages) ────────────────────────────────

CHROME_HIDE = """
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
[data-testid="stDeployButton"] { display: none; }
"""

SCROLLBAR = """
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: rgba(255,255,255,0.04); border-radius: 4px; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.18); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.32); }
"""

BACKGROUND = """
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewBlockContainer"],
[data-testid="stHeader"],
[data-testid="stToolbar"],
header[data-testid="stHeader"],
.main .block-container {
    background: #0c1929 !important;
}
"""

# Near-full-width layout used by the pages that embed a local web app in an iframe.
PADDED_LAYOUT = """
.block-container,
[data-testid="stAppViewBlockContainer"] {
    padding-top: 1.5rem !important;
    padding-bottom: 0rem !important;
    padding-left: 0.6rem !important;
    padding-right: 0.6rem !important;
    max-width: 100% !important;
}
"""

IFRAME_ELEMENT_CONTAINER = """
[data-testid="stElementContainer"]:has(iframe) { margin-bottom: 0 !important; }
"""

HEADER_TOOLBAR_TEXT = """
[data-testid="stHeader"] * { color: #8ab4cc !important; }
[data-testid="stToolbar"] * { color: #8ab4cc !important; }
"""

MAIN_TEXT = """
.main, .main p, .main span, .main div,
.main label, .main .stMarkdown,
[data-testid="stMarkdownContainer"] { color: #c4daea !important; }
"""

MAIN_LINK = """
.main a { color: #7dd3fc !important; }
"""

def _sidebar_base(shadow: bool = False) -> str:
    # The main and SOQL pages add a box-shadow to the same rule; PO and EDI don't.
    shadow_decl = "\n    box-shadow: 3px 0 24px rgba(0,0,0,0.4);" if shadow else ""
    return f"""
section[data-testid="stSidebar"] {{
    background: #08111e !important;
    border-right: 1px solid rgba(255,255,255,0.07) !important;{shadow_decl}
}}
section[data-testid="stSidebar"] * {{ color: #b8d4e8 !important; }}
"""


SIDEBAR_BASE = _sidebar_base()
SIDEBAR_BASE_SHADOW = _sidebar_base(shadow=True)

ALERT_ERROR = """
[data-testid="stError"] {
    background: rgba(214,48,49,0.09) !important;
    border-radius: 10px; border-left: 3px solid #d63031; padding: 0.7rem 1rem;
}
"""

# ── Order Validation (main page) ──────────────────────────────────────────────

MAIN_CSS = r"""
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

"""

# ── PO Processing Engine page ─────────────────────────────────────────────────

PO_CSS = (
    CHROME_HIDE
    + BACKGROUND
    + PADDED_LAYOUT
    + IFRAME_ELEMENT_CONTAINER
    + """
iframe { border: none !important; background: #0c1929; }
"""
    + HEADER_TOOLBAR_TEXT
    + MAIN_TEXT
    + MAIN_LINK
    + SIDEBAR_BASE
    + """
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] * { color: #9db9cc !important; opacity: 1 !important; }
"""
    + ALERT_ERROR
    + """
[data-testid="stCode"], [data-testid="stCode"] > div, [data-testid="stCode"] pre {
    background: #091d36 !important; color: #a8cce0 !important;
}
"""
)

# ── EDI Validator page (full-bleed iframe) ────────────────────────────────────

EDI_CSS = (
    BACKGROUND
    + SIDEBAR_BASE
    + """
.block-container { padding-top: 0rem; padding-bottom: 0rem; padding-left: 0rem; padding-right: 0rem; max-width: 100% !important; }
iframe { height: 92vh !important; min-height: 700px; border: none !important; outline: none !important; box-shadow: none !important; }
"""
    + CHROME_HIDE
    + HEADER_TOOLBAR_TEXT
    + """
[data-testid="stElementToolbar"] { display: none !important; }
[data-testid="stElementContainer"]:has(iframe) { outline: none !important; box-shadow: none !important; }
[data-testid="stIFrame"] { outline: none !important; box-shadow: none !important; border: none !important; }
"""
)

# ── SOQL Builder page ─────────────────────────────────────────────────────────

SOQL_CSS = (
    """
/* ── Global reset ── */
html, body, [class*="css"] {
    font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
}
"""
    + CHROME_HIDE
    + SCROLLBAR
    + BACKGROUND
    + PADDED_LAYOUT
    + """
[data-testid="stAppViewContainer"],
.main .block-container { min-height: 0 !important; }
"""
    + IFRAME_ELEMENT_CONTAINER
    + """
iframe { border: none !important; }
"""
    + HEADER_TOOLBAR_TEXT
    + MAIN_TEXT
    + MAIN_LINK
    + SIDEBAR_BASE_SHADOW
    + """
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

/* ── Caption / small text ── */
.stCaption, small,
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] *,
[data-testid="stCaptionContainer"] p {
    color: #9db9cc !important;
    opacity: 1 !important;
    font-size: 0.85rem !important;
}

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
"""
    + ALERT_ERROR
    + """
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
"""
)

# ── Developer Console page ────────────────────────────────────────────────────
# The main stylesheet plus styling for the main-area buttons it doesn't cover
# (the Order Validation page only has a primary button there). Matches the
# sidebar buttons: translucent fill, light text, 8px radius.

DEVCONSOLE_EXTRA_CSS = """
/* ── Secondary + download buttons in the main area ── */
.main .stDownloadButton > button,
.main .stButton > button[kind="secondary"] {
    background: rgba(255,255,255,0.07);
    color: #d4e8f4 !important;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px;
    font-size: 0.83rem;
    font-weight: 500;
    transition: all 0.18s;
}
.main .stDownloadButton > button:hover,
.main .stButton > button[kind="secondary"]:hover {
    background: rgba(255,255,255,0.13);
    border-color: rgba(255,255,255,0.22);
}
.main .stDownloadButton > button p,
.main .stButton > button[kind="secondary"] p { color: #d4e8f4 !important; }
"""

DEVCONSOLE_CSS = MAIN_CSS + DEVCONSOLE_EXTRA_CSS

_PAGE_CSS = {
    "main": MAIN_CSS,
    "po": PO_CSS,
    "edi": EDI_CSS,
    "soql": SOQL_CSS,
    "devconsole": DEVCONSOLE_CSS,
}


def css_for(page: str) -> str:
    """The stylesheet for a page, as text (no Streamlit call)."""
    try:
        return _PAGE_CSS[page]
    except KeyError:
        raise ValueError(f"Unknown theme page '{page}'. Valid pages: {', '.join(_PAGE_CSS)}.") from None


def apply_theme(page: str) -> None:
    """Inject a page's stylesheet. Call after st.set_page_config()."""
    st.markdown("<style>" + css_for(page) + "</style>", unsafe_allow_html=True)
