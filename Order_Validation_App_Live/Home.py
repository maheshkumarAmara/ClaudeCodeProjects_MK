"""Home — card-style landing page.

Entry script for the app (launch.sh runs it). Shows one card per tool; each card
opens the matching page in pages/. Purely navigation: no tool logic lives here.
"""

import os
import urllib.request
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from theme import apply_theme

st.set_page_config(page_title="Home · Rubrik", page_icon="🏠", layout="wide")


def _ask_tool_tabs_to_close() -> None:
    # Server to server, so no browser restriction applies. An open tool tab closes itself when
    # it sees the request: the PO Processing Engine tab polls for it, the Jira Dashboard tab is
    # told over its websocket. Errors are ignored: a tool may simply not be running.
    po_port = os.environ.get("PO_ENGINE_PORT", "8012")
    jira_port = os.environ.get("JIRA_DASHBOARD_PORT", "8020")
    for url in (
        f"http://127.0.0.1:{po_port}/api/close-request",
        f"http://127.0.0.1:{jira_port}/api/close-tab",
    ):
        try:
            request = urllib.request.Request(url, data=b"", method="POST")
            urllib.request.urlopen(request, timeout=1).close()
        except Exception:
            pass


_ask_tool_tabs_to_close()

apply_theme("home")

# (icon, title, description, page file)
CARDS = [
    ("📋", "Order Validation",
     "Validate Salesforce orders against business rules, including booking line item checks",
     "pages/Order_Validation.py"),
    ("📄", "PO Processing Engine",
     "Edit a distributor purchase order and regenerate the PDF, optionally pre-filled from a Salesforce Quote",
     "pages/PO_Processing_Engine.py"),
    ("🔍", "SOQL Builder",
     "Build SOQL queries visually and run them against QA or UAT",
     "pages/SOQL_Builder.py"),
    ("📊", "Jira Dashboard",
     "Track boards, sprints, test cases and alerts from Jira in one dashboard",
     "pages/Jira_Dashboard.py"),
    ("🧾", "EDI Validator",
     "Look up order and quote data through the local bridge for EDI order checks",
     "pages/EDI_Validator.py"),
    ("💻", "Developer Console",
     "Run Anonymous Apex and SOQL against QA/UAT, with confirmation for DML and a run history",
     "pages/Developer_Console.py"),
    ("🗂️", "PO Validation",
     "Validate a distributor PO against the Salesforce quote with /pov and get an Excel report",
     "pages/PO_Validation_POV.py"),
    ("📨", "PO_EDI Validation",
     "Validate a distributor PO, and its optional X12 850 .edi file, against the Salesforce quote with /pov_EDI and get an Excel report",
     "pages/PO_Validation_EDI.py"),
    ("📑", "PO_Agent Validation",
     "Validate a distributor PO, and its optional JSON, against the Salesforce quote with /povAgent and get an Excel report",
     "pages/PO_Validation.py"),
    ("✉️", "Marketplace Email",
     "Build the /MarketPlaceAutomation command for AWS, GCP and Azure marketplace notification emails",
     "pages/Marketplace_Email.py"),
    ("🧪", "Test Case Review",
     "Review test cases for a Jira story, find coverage gaps and get a Go / No-Go verdict with /test-case-review",
     "pages/Test_Case_Review.py"),
    ("🎉", "Go-Live Congrats",
     "Write a go-live congratulations message with a QA spotlight and post it to Slack with /go-live-congrats",
     "pages/Go_Live_Congrats.py"),
]
COLUMNS = 3  # the width a card has in a row of three; shorter rows are centred at this width

# Card titles per row, in display order. A row may hold any number of cards.
ROWS = [
    ["Order Validation", "EDI Validator", "Test Case Review"],
    ["Jira Dashboard", "Marketplace Email", "PO Processing Engine"],
    ["PO Validation", "PO_Agent Validation", "PO_EDI Validation"],
    ["SOQL Builder", "Developer Console", "Go-Live Congrats"],
]

st.markdown(
    '<div class="home-hero"><h1>What would you like to do?</h1>'
    "<p>Pick a tool below to get started</p></div>",
    unsafe_allow_html=True,
)

_by_title = {card[1]: card for card in CARDS}
assert sorted(t for r in ROWS for t in r) == sorted(_by_title), "ROWS must list every card exactly once"

for titles in ROWS:
    row = [_by_title[t] for t in titles]
    if len(row) < COLUMNS:
        # A short row is centred: equal spacer columns on both sides keep each card
        # the same width as the cards in a row of three.
        pad = (COLUMNS - len(row)) / 2
        cols = st.columns([pad, *[1] * len(row), pad])[1:1 + len(row)]
    else:
        cols = st.columns(len(row))
    for col, (icon, title, description, page) in zip(cols, row):
        with col:
            with st.container(border=True, key=f"home_card_{Path(page).stem}"):
                st.markdown(
                    f'<div class="home-card"><div class="home-card-icon">{icon}</div>'
                    f'<div><div class="home-card-title">{title}</div>'
                    f'<div class="home-card-desc">{description}</div></div></div>',
                    unsafe_allow_html=True,
                )
                # Hidden by CSS; the script below clicks it when the card is clicked.
                st.page_link(page, label=title)

# Forward a click anywhere on a card to that card's page link. The page link does the
# navigation inside the same Streamlit session (so the Salesforce connection is kept).
# The listener lives on the main page (window.parent), so it is replaced, not stacked, on reruns.
components.html(
    """
<script>
  (function () {
    var host;
    try { host = window.parent; host.document; } catch (e) { return; }
    if (host.__homeCardsHook) { host.document.removeEventListener("click", host.__homeCardsHook, true); }
    var hook = function (event) {
      var target = event.target;
      if (!target || !target.closest) { return; }
      var card = target.closest('[class*="st-key-home_card_"]');
      if (!card) { return; }
      var link = card.querySelector('[data-testid="stPageLink"] a');
      if (link && target.closest("a") !== link) { event.preventDefault(); link.click(); }
    };
    host.__homeCardsHook = hook;
    host.document.addEventListener("click", hook, true);
  })();
</script>
""",
    height=0,
)

# Streamlit switches pages without reloading the browser tab, so the tool pages' own
# "close with the page" hooks never fire when the user comes back here. Close the tabs
# those pages opened (their references live on the main page), and clear the auto-open
# stamps so the next visit to a tool page opens its tab again.
components.html(
    """
<script>
  (function () {
    var host;
    try { host = window.parent; host.document; } catch (e) { return; }
    // A tool page leaves an auto-open stamp on the main page. It is still there when the user comes
    // back to Home inside the same session, and gone after a reload of this tab. Only the first case
    // can have left tabs behind that need closing by name (see the safety net below).
    var cameFromToolPage = ["poEngineAutoOpenAt", "jiraDashboardAutoOpenAt", "soqlBuilderAutoOpenAt"]
      .some(function (key) { return !!host[key]; });
    ["poEngineTab", "jiraDashboardTab", "soqlBuilderTab"].forEach(function (key) {
      var had = false;
      try {
        var tab = host[key];
        had = !!tab;
        if (tab && !tab.closed) { tab.close(); }
      } catch (e) { /* already gone */ }
      console.info("Home: " + key + (had ? " had a stored tab, close() called" : " had no stored tab"));
      host[key] = null;
    });
    // Safety net: the tool pages open their tab under a fixed window name, so a tab whose
    // reference was lost (e.g. two reruns racing) can still be found by that name and closed.
    // window.open("", name) focuses a tab with that name, or opens a blank one if there is none, so it
    // is skipped on a plain reload of Home: otherwise the browser jumps to another tab.
    (cameFromToolPage ? ["poEngineWin", "jiraDashboardWin", "soqlBuilderWin"] : []).forEach(function (name) {
      try {
        var named = window.open("", name);
        if (named) { named.close(); }
      } catch (e) { /* blocked */ }
    });
    ["poEngineAutoOpenAt", "jiraDashboardAutoOpenAt", "soqlBuilderAutoOpenAt"].forEach(function (key) {
      host[key] = 0;
    });
  })();
</script>
""",
    height=0,
)
