"""PO_EDI Validation — runs the /pov_EDI skill (PO, plus an optional X12 850 .edi order file).

A thin page: all the logic is in pov_page.py, shared with the /povAgent and /pov pages. The .edi file is uploaded
here because the Claude Code editor refuses to attach .edi files; this page saves it under a fixed name and starts
Claude Code with its path already in the command.
"""

import sys
from pathlib import Path

import streamlit as st

# theme.py and pov_page.py live in the project root, one level above pages/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pov_page import PovConfig, render_page  # noqa: E402
from theme import apply_theme  # noqa: E402

st.set_page_config(page_title="PO_EDI Validation · Rubrik", page_icon="📨", layout="wide")
apply_theme("povedi")

render_page(st, PovConfig(
    skill="pov_EDI",
    title="PO_EDI Validation",
    accepts_json=False,
    accepts_edi=True,
    description=(
        "Prepare a distributor PO (and an optional X12 850 .edi order file) for validation against its Salesforce "
        "quote with the /pov_EDI skill."
    ),
))
