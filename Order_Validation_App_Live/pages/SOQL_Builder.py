"""SOQL Builder — new standalone page.

Runs the SOQL Builder dev tool (copied verbatim from rbk-sfdx-release's
scripts/soql-builder/) as its own local Node server and embeds it in an
iframe, mirroring the idempotent auto-start pattern launch.sh already uses
for bridge/sf-bridge-server.js — except done in Python here so launch.sh
itself needs no changes. No logic from that file is reimplemented or
modified. Purely additive: does not touch or import anything from
Order_Validation_App.py or the other pages (it only imports the shared
stylesheet from theme.py).
"""

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# theme.py lives in the project root, one level above pages/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from theme import apply_theme  # noqa: E402

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


apply_theme("soql")

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
