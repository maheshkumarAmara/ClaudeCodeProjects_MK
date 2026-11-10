"""PO_Agent Validation — runs the /povAgent skill (PO, plus an optional JSON order file).

A thin page: all the logic is in pov_page.py, shared with the /pov page (PO_Validation_POV.py).
"""

import sys
from pathlib import Path

import streamlit as st

# theme.py and pov_page.py live in the project root, one level above pages/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pov_page import PovConfig, render_page  # noqa: E402
from theme import apply_theme  # noqa: E402

st.set_page_config(page_title="PO_Agent Validation · Rubrik", page_icon="📑", layout="wide")
apply_theme("povalidation")

render_page(st, PovConfig(
    skill="povAgent",
    title="PO_Agent Validation",
    accepts_json=True,
    description=(
        "Prepare a distributor PO (and an optional JSON order file) for validation against its Salesforce quote "
        "with the /povAgent skill."
    ),
))
