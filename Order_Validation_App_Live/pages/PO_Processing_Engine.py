"""PO Processing Engine — new standalone page.

Runs the PO Processing Engine (a FastAPI app, copied verbatim into
po-processing-engine/) as its own local server and embeds it in an iframe,
using the same idempotent auto-start pattern as pages/SOQL_Builder.py. No logic
from the engine is reimplemented or modified. Purely additive: does not touch
or import anything from Order_Validation_App.py or the other pages (it only
imports the shared stylesheet from theme.py).
"""

import os
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

st.set_page_config(page_title="PO Processing Engine · Rubrik", page_icon="📄", layout="wide")

PO_ENGINE_DIR = Path(__file__).parent.parent / "po-processing-engine"
# 8010 is where the engine runs when launched standalone, and 8011 can be held by
# another checkout's embedded engine, so this copy uses its own port and never
# reuses an engine serving different code.
PORT = int(os.environ.get("PO_ENGINE_PORT", "8012"))
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


# Renders the "Open in a new tab" link. The tab reference is kept on the Streamlit
# page (window.parent), which the iframe can reach because Streamlit sandboxes
# components with allow-same-origin. That keeps the reference across reruns, so a
# second click focuses the open tab instead of opening another one. A pagehide
# listener on the main page closes the tab when the main page closes.
OPEN_TAB_HTML = """
<style>
  html, body { margin: 0; background: transparent; }
  a { color: #7dd3fc; font-family: "Source Sans Pro", sans-serif; font-size: 1rem; }
</style>
<a id="po-open" href="__URL__" target="_blank" rel="noopener">Open in a new tab ↗</a>
<script>
  (function () {
    var url = "__URL__";
    var KEY = "poEngineTab";
    var localTab = null;

    function storedTab() {
      try { return window.parent[KEY] || null; } catch (e) { return localTab; }
    }

    function storeTab(tab) {
      localTab = tab;
      try { window.parent[KEY] = tab; } catch (e) { /* fall back to localTab */ }
    }

    function closeTabWithPage() {
      var tab = storedTab();
      if (tab && !tab.closed) { tab.close(); }
    }

    // Opens the engine in a new tab, or focuses the one that is already open. Returns true when a
    // tab is open afterwards, false when the browser blocked the new one.
    function openEngineTab() {
      var tab = storedTab();
      if (tab && !tab.closed) { tab.focus(); return true; }
      var opened = window.open(url, "poEngineWin");
      if (opened) { storeTab(opened); return true; }
      return false;
    }

    document.getElementById("po-open").addEventListener("click", function (event) {
      event.preventDefault();
      openEngineTab();
    });

    // Opens the tab by itself when the page is shown. Streamlit re-creates this component on every
    // rerun of the page, so two things stop that from opening more tabs: an engine tab that is
    // already open is only focused (see openEngineTab), and an attempt made in the last few seconds
    // is not repeated. Browsers often block a tab opened without a click: then nothing opens and
    // the link above still works with one click.
    var AUTO_KEY = "poEngineAutoOpenAt";
    var RETRY_AFTER_MS = 5000;
    var lastTry = 0;
    try { lastTry = window.parent[AUTO_KEY] || 0; } catch (e) { lastTry = 0; }
    if (Date.now() - lastTry > RETRY_AFTER_MS) {
      try { window.parent[AUTO_KEY] = Date.now(); } catch (e) { /* no stamp: may retry on the next rerun */ }
      try { openEngineTab(); } catch (e) { /* blocked: the link is the fallback */ }
    }

    try {
      var previous = window.parent[KEY + "Hook"];
      if (previous) { window.parent.removeEventListener("pagehide", previous); }
      window.parent[KEY + "Hook"] = closeTabWithPage;
      window.parent.addEventListener("pagehide", closeTabWithPage);
    } catch (e) {
      window.addEventListener("pagehide", closeTabWithPage);
    }
  })();
</script>
"""


apply_theme("po")

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
        components.html(OPEN_TAB_HTML.replace("__URL__", server_url), height=32)
        components.iframe(server_url, height=1100, scrolling=True)
    else:
        st.error("PO Processing Engine did not start in time. Recent log output:")
        st.code(_log_tail(), language="text")
