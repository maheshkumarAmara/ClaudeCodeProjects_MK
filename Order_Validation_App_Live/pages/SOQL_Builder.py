"""SOQL Builder — new standalone page.

Runs the SOQL Builder dev tool (copied verbatim from rbk-sfdx-release's
scripts/soql-builder/) as its own local Node server and embeds it in an
iframe, mirroring the idempotent auto-start pattern launch.sh already uses
for bridge/sf-bridge-server.js — except done in Python here so launch.sh
itself needs no changes. No logic from that file is reimplemented or
modified. Purely additive: does not touch or import anything from
streamlit_app.py or the other pages.
"""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="SOQL Builder · Rubrik", page_icon="🔎", layout="wide")

SOQL_BUILDER_DIR = Path(__file__).parent.parent / "soql-builder"
PORT = int(os.environ.get("SOQL_BUILDER_PORT", "4580"))
LOG_PATH = "/tmp/soql_builder_server.log"

NVM_FALLBACK_GLOBS = [
    str(Path.home() / ".nvm" / "versions" / "node" / "*" / "bin" / "node"),
]


def _find_node() -> str | None:
    node = shutil.which("node")
    if node:
        return node
    import glob

    for pattern in NVM_FALLBACK_GLOBS:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]
    return None


def _port_is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _start_server(node_path: str) -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        subprocess.Popen(
            [node_path, "server.mjs"],
            cwd=str(SOQL_BUILDER_DIR),
            env={**os.environ, "SOQL_BUILDER_PORT": str(PORT)},
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def _log_tail(lines: int = 30) -> str:
    try:
        return "\n".join(Path(LOG_PATH).read_text(encoding="utf-8").splitlines()[-lines:])
    except FileNotFoundError:
        return "(no log yet)"


st.markdown(
    """
    <style>
    /* ── Global reset ── */
    html, body, [class*="css"] {
        font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
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
    .block-container,
    [data-testid="stAppViewBlockContainer"] {
        padding-top: 1.5rem !important;
        padding-bottom: 0rem !important;
        padding-left: 0.6rem !important;
        padding-right: 0.6rem !important;
        max-width: 100% !important;
    }
    [data-testid="stAppViewContainer"],
    .main .block-container { min-height: 0 !important; }
    [data-testid="stElementContainer"]:has(iframe) { margin-bottom: 0 !important; }
    iframe { border: none !important; }

    /* Top toolbar */
    [data-testid="stHeader"] * { color: #8ab4cc !important; }
    [data-testid="stToolbar"] * { color: #8ab4cc !important; }

    /* Main content text */
    .main, .main p, .main span, .main div,
    .main label, .main .stMarkdown,
    [data-testid="stMarkdownContainer"] { color: #c4daea !important; }
    .main a { color: #7dd3fc !important; }

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
    [data-testid="stError"] {
        background: rgba(214,48,49,0.09) !important;
        border-radius: 10px; border-left: 3px solid #d63031; padding: 0.7rem 1rem;
    }

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
    </style>
    """,
    unsafe_allow_html=True,
)

st.caption(
    "Runs a local Node server that shells out to the already-authenticated `sf` CLI — "
    "same trust model as the EDI Order Ops Tool's bridge server. Bound to 127.0.0.1 only."
)

if not SOQL_BUILDER_DIR.exists():
    st.error(f"soql-builder tool not found at {SOQL_BUILDER_DIR}")
else:
    server_url = f"http://127.0.0.1:{PORT}/"

    if not _port_is_listening(PORT):
        node_path = _find_node()
        if not node_path:
            st.error("Could not locate a `node` executable on this machine — SOQL Builder needs Node to run its local server.")
        else:
            _start_server(node_path)
            for _ in range(20):
                time.sleep(0.25)
                if _port_is_listening(PORT):
                    break

    if _port_is_listening(PORT):
        st.markdown(f"[Open in a new tab ↗]({server_url})")
        components.iframe(server_url, height=1000, scrolling=True)
    else:
        st.error("SOQL Builder server did not start in time. Recent log output:")
        st.code(_log_tail(), language="text")
