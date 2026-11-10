"""PO Validation — runs the /pov skill (PO only, no JSON order file).

A thin page: all the logic is in pov_page.py, shared with the /povAgent page (PO_Validation.py).
"""

import sys
from pathlib import Path

import streamlit as st

# theme.py and pov_page.py live in the project root, one level above pages/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pov_page import PovConfig, render_page  # noqa: E402
from theme import apply_theme  # noqa: E402

st.set_page_config(page_title="PO Validation · Rubrik", page_icon="🗂️", layout="wide")
apply_theme("pov")

render_page(st, PovConfig(
    skill="pov",
    title="PO Validation",
    accepts_json=False,
    description="Prepare a distributor PO for validation against its Salesforce quote with the /pov skill.",
    note="This checks the PO against the quote only. To also compare a JSON order file, use PO_Agent Validation.",
))
