"""EDI Order Ops Tool — new standalone page.

Embeds assets/EDI_Order_Ops_Tool.html (a byte-identical copy of
05_08_2026_SFConnector_MK.html) verbatim in an iframe. No logic from that
file is reimplemented or modified. Purely additive: does not touch or
import anything from Order_Validation_App.py or the other pages (it only
imports the shared stylesheet from theme.py).
"""

import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# theme.py lives in the project root, one level above pages/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from theme import apply_theme  # noqa: E402

st.set_page_config(page_title="EDI Order Ops Tool · Rubrik", page_icon="🧾", layout="wide")

# Full-bleed wrapper: no page title/caption, no default Streamlit padding,
# iframe sized to fill the viewport. Presentation only — does not touch
# anything inside the embedded tool itself.
apply_theme("edi")

html_path = Path(__file__).parent.parent / "assets" / "EDI_Order_Ops_Tool.html"

if html_path.exists():
    html_content = html_path.read_text(encoding="utf-8")
    components.html(html_content, height=900, scrolling=True)
else:
    st.error(f"Tool file not found at {html_path}")
