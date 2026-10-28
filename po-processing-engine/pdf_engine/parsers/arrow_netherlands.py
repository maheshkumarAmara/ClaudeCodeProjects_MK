"""Template parser for Arrow ECS BV (Netherlands) purchase orders.

The sample is a landscape, 16-page document: 15 pages of line items (the last
one also carries the totals and payment/delivery terms) followed by a
"Complementary Order Information" page. Each item prints as a main row plus
one or two wrapped continuation lines, so rows are split into columns by
x-position and continuation lines are folded back into their item.

This only loads the template into the editor. There is no layout for Arrow
(Netherlands) yet, so generate/preview are rejected until one is added.
"""

import re
from pathlib import Path

import pdfplumber

# Column boundaries (x0 ranges) measured from the sample's items table.
COL_LINE_NO = (0, 55)
COL_ARROW_ITEM = (55, 146)
COL_VENDOR_ITEM = (146, 271)
COL_DESCRIPTION = (271, 470)
COL_QTY = (470, 530)
COL_RRP = (530, 612)
COL_DISCOUNT = (612, 700)
COL_UNIT_PRICE = (700, 770)
COL_TOTAL = (770, 900)

HEADER_ROW_TOP = 70.0  # items start below the repeated column-header row
FOOTER_TOP = 460.0  # the Arrow ECS address footer begins below this
LINE_TOLERANCE = 2.0
MAIN_ROW_RE = re.compile(r"^\d+$")
TOTALS_START_RE = re.compile(r"^(Total (excl|incl)\.|VAT\b|Terms of payment|Delivery terms)")

HEADER_PATTERNS = {
    "po_number": r"Purchase order (\S+)",
    "po_date": r"PO date: (\S+)",
    "arrow_contact": r"Arrow Contact: (.+?)(?:\n|$)",
    "arrow_email": r"E-mail: (\S+@arrow\.com)",
    "end_user_number": r"End user number : (\S+)",
    "quote_number": r"Quote number : (\S+)",
}

TOTAL_PATTERNS = {
    "payment_terms": r"Terms of payment: (.+)",
    "delivery_terms": r"Delivery terms: (.+)",
}


def _search(patterns: dict[str, str], text: str) -> dict[str, str]:
    values = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        values[key] = match.group(1).strip() if match else ""
    return values


def _in_column(word: dict, column: tuple[float, float]) -> bool:
    return column[0] <= word["x0"] < column[1]


def _column_text(words: list[dict], column: tuple[float, float]) -> str:
    return " ".join(w["text"] for w in sorted(words, key=lambda w: w["x0"]) if _in_column(w, column))


def _cluster_lines(words: list[dict]) -> list[list[dict]]:
    """Groups words onto printed lines, tolerating sub-point top offsets."""
    lines: list[list[dict]] = []
    anchor = None
    for w in sorted(words, key=lambda w: w["top"]):
        if anchor is not None and w["top"] - anchor <= LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
            anchor = w["top"]
    return lines


def _plain_number(text: str) -> str:
    # The sample prints US-style numbers: "1,574.40" -> "1574.40".
    return text.replace(",", "").replace("$", "").strip()


def _parse_items_page(page) -> list[dict]:
    words = [
        w
        for w in page.extract_words(keep_blank_chars=False)
        if HEADER_ROW_TOP < w["top"] < FOOTER_TOP
    ]
    items: list[dict] = []
    current: dict | None = None
    for line in _cluster_lines(words):
        # The last items page continues into the totals and payment/delivery
        # terms; none of that is a wrapped item line.
        if TOTALS_START_RE.match(" ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"]))):
            break
        first = _column_text(line, COL_LINE_NO)
        if MAIN_ROW_RE.match(first) and _column_text(line, COL_QTY):
            current = {
                "line_no": first,
                "arrow_item_no": _column_text(line, COL_ARROW_ITEM),
                "part_number": _column_text(line, COL_VENDOR_ITEM),
                "description": _column_text(line, COL_DESCRIPTION),
                "qty": _plain_number(_column_text(line, COL_QTY)),
                "rrp": _plain_number(_column_text(line, COL_RRP)),
                "pct_disc": _column_text(line, COL_DISCOUNT).replace("%", "").strip(),
                "unit_cost": _plain_number(_column_text(line, COL_UNIT_PRICE)),
                "terms": "",
            }
            items.append(current)
        elif current is not None:
            # Continuation of the previous item: the wrapped part of the
            # Arrow item number (joined with no space, it breaks mid-token)
            # and the rest of the description.
            arrow_cont = _column_text(line, COL_ARROW_ITEM)
            if arrow_cont:
                current["arrow_item_no"] += arrow_cont
            desc_cont = _column_text(line, COL_DESCRIPTION)
            if desc_cont:
                current["description"] = f"{current['description']} {desc_cont}".strip()
    return items


def _parse_complementary_page(page) -> dict[str, str]:
    """Reseller / end-user / shipping blocks on the final page.

    Labels sit at x<100 and values start at x=105, so each value is the text
    to the right of its label on the same printed line.
    """
    left_words = [w for w in page.extract_words() if w["x0"] < 360]
    values: dict[str, str] = {}
    section = "reseller"
    for line in _cluster_lines(left_words):
        label = " ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"]) if w["x0"] < 100)
        value = " ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"]) if w["x0"] >= 100)
        if label.startswith("End User Information"):
            section = "end_user"
            continue
        key = {
            "Company:": "company",
            "Contact name:": "contact",
            "Contact:": "contact",
            "Email:": "email",
            "Phone:": "phone",
        }.get(label)
        if key:
            values[f"{section}_{key}"] = value
    return values


def parse_template(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]
        items: list[dict] = []
        # Every page except the trailing "Complementary Order Information" one
        # is an items page.
        for page in pdf.pages[:-1]:
            items.extend(_parse_items_page(page))
        complementary = _parse_complementary_page(pdf.pages[-1])

    fields = _search(HEADER_PATTERNS, page_texts[0])
    fields.update(_search(TOTAL_PATTERNS, "\n".join(page_texts)))
    fields.update(complementary)
    return {"fields": fields, "line_items": items}
