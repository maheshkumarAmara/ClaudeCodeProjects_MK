"""EDI Order Ops Tool — new standalone page.

Embeds assets/EDI_Order_Ops_Tool.html (a byte-identical copy of
05_08_2026_SFConnector_MK.html) verbatim in an iframe. No logic from that
file is reimplemented or modified. Purely additive: does not touch or
import anything from streamlit_app.py.
"""

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="EDI Order Ops Tool · Rubrik", page_icon="🧾", layout="wide")

# Full-bleed wrapper: no page title/caption, no default Streamlit padding,
# iframe sized to fill the viewport. Presentation only — does not touch
# anything inside the embedded tool itself.
st.markdown(
    """
    <style>
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stAppViewBlockContainer"],
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    header[data-testid="stHeader"],
    .main .block-container {
        background: #0c1929 !important;
    }
    section[data-testid="stSidebar"] {
        background: #08111e !important;
        border-right: 1px solid rgba(255,255,255,0.07) !important;
    }
    section[data-testid="stSidebar"] * { color: #b8d4e8 !important; }
    .block-container { padding-top: 0rem; padding-bottom: 0rem; padding-left: 0rem; padding-right: 0rem; max-width: 100% !important; }
    iframe { height: 92vh !important; min-height: 700px; border: none !important; outline: none !important; box-shadow: none !important; }
    #MainMenu { visibility: hidden; }
    footer    { visibility: hidden; }
    [data-testid="stDeployButton"] { display: none; }
    [data-testid="stHeader"] * { color: #8ab4cc !important; }
    [data-testid="stToolbar"] * { color: #8ab4cc !important; }
    [data-testid="stElementToolbar"] { display: none !important; }
    [data-testid="stElementContainer"]:has(iframe) { outline: none !important; box-shadow: none !important; }
    [data-testid="stIFrame"] { outline: none !important; box-shadow: none !important; border: none !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

html_path = Path(__file__).parent.parent / "assets" / "EDI_Order_Ops_Tool.html"

if html_path.exists():
    html_content = html_path.read_text(encoding="utf-8")
    components.html(html_content, height=900, scrolling=True)
else:
    st.error(f"Tool file not found at {html_path}")
