"""Jira Dashboard — embedded page.

Runs the Jira dashboard (a FastAPI app in the bundled jira-dashboard/ folder) as
its own local server and embeds it in an iframe, using the same idempotent
auto-start pattern as pages/PO_Processing_Engine.py. The dashboard keeps its own
Python environment (its pinned FastAPI/uvicorn versions differ from this app's),
so it is started with jira-dashboard/venv/bin/python when that exists.
Credentials stay in jira-dashboard/.env; this page only checks that it exists.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from theme import apply_theme  # noqa: E402

st.set_page_config(page_title="Jira Dashboard · Rubrik", page_icon="📊", layout="wide")

JIRA_DIR = Path(__file__).resolve().parent.parent / "jira-dashboard"
PORT = int(os.environ.get("JIRA_DASHBOARD_PORT", "8020"))
LOG_PATH = "/tmp/jira_dashboard_server.log"


def _port_is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _python() -> str:
    venv_python = JIRA_DIR / "venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def _start_server() -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        subprocess.Popen(
            [_python(), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
            cwd=str(JIRA_DIR),
            env={**os.environ, "JIRA_DASHBOARD_NO_BROWSER": "1"},
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def _log_tail(lines: int = 30) -> str:
    try:
        return "\n".join(Path(LOG_PATH).read_text(encoding="utf-8").splitlines()[-lines:])
    except FileNotFoundError:
        return "(no log yet)"


# Same approach as pages/PO_Processing_Engine.py: the tab reference lives on the Streamlit page
# (window.parent) so a rerun focuses the open tab instead of opening another, an attempt in the
# last few seconds is not repeated, and the tab closes with the main page. Browsers may block a
# tab opened without a click; the link is then the fallback.
OPEN_TAB_HTML = """
<style>
  html, body { margin: 0; background: transparent; }
  a { color: #7dd3fc; font-family: "Source Sans Pro", sans-serif; font-size: 1rem; }
</style>
<a id="jira-open" href="__URL__" target="_blank" rel="noopener">Open in a new tab ↗</a>
<script>
  (function () {
    var url = "__URL__";
    var KEY = "jiraDashboardTab";
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
    function openTab() {
      var tab = storedTab();
      if (tab && !tab.closed) { tab.focus(); return true; }
      var opened = window.open(url, "jiraDashboardWin");
      if (opened) { storeTab(opened); return true; }
      return false;
    }

    document.getElementById("jira-open").addEventListener("click", function (event) {
      event.preventDefault();
      openTab();
    });

    var AUTO_KEY = "jiraDashboardAutoOpenAt";
    var lastTry = 0;
    try { lastTry = window.parent[AUTO_KEY] || 0; } catch (e) { lastTry = 0; }
    if (Date.now() - lastTry > 5000) {
      try { window.parent[AUTO_KEY] = Date.now(); } catch (e) { /* may retry on the next rerun */ }
      try { openTab(); } catch (e) { /* blocked: the link is the fallback */ }
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

apply_theme("jira")

st.caption(
    "Runs the Jira Dashboard as a local server bound to 127.0.0.1 only. "
    "Jira credentials are read from jira-dashboard/.env."
)

if not JIRA_DIR.exists():
    st.error(f"jira-dashboard not found at {JIRA_DIR}")
else:
    if not (JIRA_DIR / ".env").exists():
        st.warning("jira-dashboard/.env is missing; the dashboard cannot connect to Jira without it.")

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
        st.error("Jira Dashboard did not start in time. Recent log output:")
        st.code(_log_tail(), language="text")
