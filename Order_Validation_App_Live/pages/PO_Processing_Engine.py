"""PO Processing Engine — new standalone page.

Runs the PO Processing Engine (a FastAPI app, copied verbatim into
po-processing-engine/) as its own local server and embeds it in an iframe,
using the same idempotent auto-start pattern as pages/SOQL_Builder.py. No logic
from the engine is reimplemented or modified. Purely additive: does not touch
or import anything from Order_Validation_App.py or the other pages.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="PO Processing Engine · Rubrik", page_icon="📄", layout="wide")

PO_ENGINE_DIR = Path(__file__).parent.parent / "po-processing-engine"
# 8010 is where the engine runs when launched standalone, so the embedded copy
# uses its own port and the two never collide.
PORT = int(os.environ.get("PO_ENGINE_PORT", "8011"))
LOG_PATH = "/tmp/po_processing_engine_server.log"


def _port_is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _start_server() -> None:
    # sys.executable is the interpreter running Streamlit, so the engine uses the
    # same packages launch.sh installed from requirements.txt.
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
            cwd=str(PO_ENGINE_DIR),
            env={**os.environ, "PORT": str(PORT)},
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
    #MainMenu { visibility: hidden; }
    footer    { visibility: hidden; }
    [data-testid="stDeployButton"] { display: none; }

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
    [data-testid="stElementContainer"]:has(iframe) { margin-bottom: 0 !important; }
    iframe { border: none !important; background: #ffffff; }

    [data-testid="stHeader"] * { color: #8ab4cc !important; }
    [data-testid="stToolbar"] * { color: #8ab4cc !important; }
    .main, .main p, .main span, .main div,
    .main label, .main .stMarkdown,
    [data-testid="stMarkdownContainer"] { color: #c4daea !important; }
    .main a { color: #7dd3fc !important; }

    section[data-testid="stSidebar"] {
        background: #08111e !important;
        border-right: 1px solid rgba(255,255,255,0.07) !important;
    }
    section[data-testid="stSidebar"] * { color: #b8d4e8 !important; }

    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] * { color: #9db9cc !important; opacity: 1 !important; }
    [data-testid="stError"] {
        background: rgba(214,48,49,0.09) !important;
        border-radius: 10px; border-left: 3px solid #d63031; padding: 0.7rem 1rem;
    }
    [data-testid="stCode"], [data-testid="stCode"] > div, [data-testid="stCode"] pre {
        background: #091d36 !important; color: #a8cce0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.caption(
    "Runs the PO Processing Engine as a local server bound to 127.0.0.1 only. "
    "Salesforce pulls use the already-authenticated `sf` CLI; nothing is written back to Salesforce."
)

if not PO_ENGINE_DIR.exists():
    st.error(f"po-processing-engine not found at {PO_ENGINE_DIR}")
else:
    server_url = f"http://127.0.0.1:{PORT}/"

    if not _port_is_listening(PORT):
        _start_server()
        for _ in range(40):
            time.sleep(0.25)
            if _port_is_listening(PORT):
                break

    if _port_is_listening(PORT):
        st.markdown(f"[Open in a new tab ↗]({server_url})")
        components.iframe(server_url, height=1100, scrolling=True)
    else:
        st.error("PO Processing Engine did not start in time. Recent log output:")
        st.code(_log_tail(), language="text")
