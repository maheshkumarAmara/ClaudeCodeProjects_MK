"""Small input-cleaning and parsing helpers (no Streamlit)."""

import re

import pandas as pd

_HTML_TAG_RE = re.compile(r'<[^>]+>')


def _clean_sf(s: str) -> str:
    """Strip HTML tags (Salesforce formula/rich-text fields) and normalise whitespace."""
    return _HTML_TAG_RE.sub('', s or '').strip()


def _parse_order_text(raw: str) -> list:
    """Extract order numbers from free-form text.

    Handles all paste formats from Salesforce export:
    - Copy (CSV):   "_","Order_Number__c" / "Order","140703"   (quoted, comma-sep)
    - Copy (Excel): _\tOrder_Number__c / Order\t140703         (tab-sep)
    - Plain list:   140703\n140709  or  140703, 140709
    """
    import re
    # Split on whitespace, commas, semicolons, tabs — any mix
    tokens = re.split(r"[\t ,;\r\n]+", raw.strip())
    result = []
    for tok in tokens:
        # Strip surrounding quotes and whitespace (handles CSV quoting)
        clean = tok.strip().strip('"').strip("'").strip()
        if clean.isdigit() and len(clean) >= 4:   # order numbers are ≥4 digits
            result.append(clean)
    return list(dict.fromkeys(result))  # deduplicate, preserve order


def _parse_csv_upload(file) -> list:
    """Extract order numbers from an uploaded CSV/TXT file."""
    df = pd.read_csv(file, dtype=str)
    # Named column containing 'order' + 'number'?
    candidates = [c for c in df.columns if "order" in c.lower() and "number" in c.lower()]
    if candidates:
        nums = df[candidates[0]].dropna().str.strip().tolist()
    elif df.shape[1] == 1:
        nums = df.iloc[:, 0].dropna().str.strip().tolist()
    else:
        # Find the column where most values are pure digits (order numbers)
        best = None
        for col in df.columns:
            if df[col].dropna().str.strip().str.match(r"^\d{5,}$").mean() > 0.8:
                best = col
                break
        nums = df[best].dropna().str.strip().tolist() if best else df.iloc[:, 0].dropna().str.strip().tolist()
    return [n for n in nums if n.isdigit()]
