"""Template parser for Carahsoft Technology Corp purchase orders.

Loads the sample PDF in data/templates/Carahsoft Technology Corp/ into the editable form:
`parse_template(path)` returns {"fields": {...}, "line_items": [...]}.

Layout (Letter, 2 pages; every page repeats the header):
  - Header: PO number (in a box top right and again in the first cell of the info strip),
    date, page number, Ship To block, then an info strip (PO Number, Vendor Number, Terms,
    Ship Via, contact, Reference).
  - A ruled items table: Item Number | Line | Description | Qty | Unit Price | Extended Price.
    A description wraps onto further lines and may carry "Comments: ..." text. The
    subscription term is printed inside the description ("Term: 36 Months").
  - After the last item, the same description column carries a notes block:
        Quote #: Q-191185 / Support Term: 36 / FCA Origin / - / **END USER INFO** /
        name / email / phone / EU PO # ...
    It is read into header fields, not into the last item's description.
  - Page 1 ends with "Continued on next page..."; the last page ends with the total.

Conventions every parser in this engine follows:
  - Coordinates are pdfplumber's top-down points (x0 from the left, top from the top).
  - A line item uses these keys: part_number, description, qty, unit_cost, pct_disc, terms.
    Numbers are returned as plain strings with no thousands separators or currency
    symbols ("1574.40"). `terms` is the subscription term in months, or "".
  - A header field that is not found is returned as "" (never omitted, never None),
    so the form always shows the field.
  - Open the PDF with `open_pdf` (not pdfplumber.open) so that, when an already
    generated PO is uploaded, the parser only sees the text a viewer would see.
"""

import re
from pathlib import Path

from pdf_engine.extractor import open_pdf

# Column boundaries as (start, end) ranges measured from the sample's items table (the
# column rules sit at 143.0, 169.9, 388.6, 454.9 and 512.8). A word belongs to a column when
# its x0 falls in [start, end), or its x1 for the RIGHT_ALIGNED columns.
COL_LINE_NO = (143.0, 170.0)
COL_PART_NUMBER = (30.0, 143.0)
COL_DESCRIPTION = (170.0, 388.6)
COL_TERMS = (-2.0, -1.0)  # no terms column: the term is read from the description
COL_QTY = (388.6, 454.9)
COL_UNIT_PRICE = (454.9, 512.8)
COL_AMOUNT = (512.8, 600.0)

# Line number, qty, unit price and amount all end at the same x whatever their length.
RIGHT_ALIGNED: set[tuple[float, float]] = {COL_LINE_NO, COL_QTY, COL_UNIT_PRICE, COL_AMOUNT}

# Items sit below the rule under the column-header row and above the table's bottom frame.
ITEMS_TOP = 320.5
FOOTER_TOP = 644.0

LINE_TOLERANCE = 2.0  # words whose `top` differs by less than this are on one printed line
MAIN_ROW_RE = re.compile(r"^\d+$")  # what the first column holds on an item's first line

# A line starting like this ends the items table (the totals box sits below FOOTER_TOP, so
# this is only a safeguard).
TOTALS_START_RE = re.compile(r"^Total purchase order\b", re.IGNORECASE)

# The notes block starts with this, in the description column, below the last item.
NOTES_START_RE = re.compile(r"^Quote\s*#:", re.IGNORECASE)
TERM_RE = re.compile(r"Term:\s*(\d+)\s*Months?", re.IGNORECASE)
EMAIL_RE = re.compile(r"\S+@\S+")
PHONE_RE = re.compile(r"^\+?[\d\-\s().]{7,}$")

# Header cells read by position: (x0, x1, top, bottom). The info strip's cells are bounded by
# its vertical rules (143.0, 216.4, 290.2, 361.0, 502.6).
HEADER_CELLS = {
    "po_number": (37.0, 142.5, 268.0, 282.0),
    "vendor_number": (144.0, 215.5, 268.0, 282.0),
    "payment_terms": (217.0, 289.5, 268.0, 282.0),
    "reference": (503.0, 583.0, 268.0, 282.0),
    "po_date": (457.0, 522.5, 63.5, 76.0),
}
SHIP_TO_BOX = (335.0, 158.0, 232.0)  # x0 from, top from, top to


def _search(patterns: dict[str, str], text: str) -> dict[str, str]:
    values = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        values[key] = match.group(1).strip() if match else ""
    return values


def _in_column(word: dict, column: tuple[float, float]) -> bool:
    """A word is in a column when its left edge is. That is wrong for a RIGHT-ALIGNED number
    column: a long value ("$142,145.64") starts further left than a short one ("$40,613.04"),
    so its left edge can land inside the column to its left and be read as part of that one
    (a qty of 7 and an amount of 142,145.64 came back as one qty "7142145.64"). Columns listed
    in RIGHT_ALIGNED are matched on the word's RIGHT edge instead."""
    edge = word["x1"] if column in RIGHT_ALIGNED else word["x0"]
    return column[0] <= edge < column[1]


def _column_text(words: list[dict], column: tuple[float, float]) -> str:
    return " ".join(w["text"] for w in sorted(words, key=lambda w: w["x0"]) if _in_column(w, column))


def _cluster_lines(words: list[dict]) -> list[list[dict]]:
    """Groups words onto printed lines, tolerating sub-point `top` offsets."""
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
    """"$1,574.40" -> "1574.40". For a European sample ("1.574,40") replace this with a
    version that drops the dots and turns the comma into a decimal point."""
    return re.sub(r"[^\d.\-]", "", text.replace(",", ""))


def _line_text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"]))


def _parse_items_page(page, carry: dict | None, notes: list[str]) -> tuple[list[dict], bool]:
    """Line items on one page, and whether the totals block was reached (so no later page
    holds items). `carry` is the previous page's last item, for a row that wraps across pages.
    Lines of the notes block are appended to `notes` instead of to an item."""
    words = [w for w in page.extract_words(keep_blank_chars=False) if ITEMS_TOP < w["top"] < FOOTER_TOP]
    items: list[dict] = []
    current = carry
    in_notes = False
    for line in _cluster_lines(words):
        line_text = _line_text(line)
        if TOTALS_START_RE.match(line_text):
            return items, True
        if in_notes:
            notes.append(line_text)
            continue
        first = _column_text(line, COL_LINE_NO)
        if MAIN_ROW_RE.match(first) and _column_text(line, COL_QTY):
            current = {
                "part_number": _column_text(line, COL_PART_NUMBER),
                "description": _column_text(line, COL_DESCRIPTION),
                "qty": _plain_number(_column_text(line, COL_QTY)),
                "unit_cost": _plain_number(_column_text(line, COL_UNIT_PRICE)),
                "pct_disc": "",
                "terms": "",
            }
            items.append(current)
        elif NOTES_START_RE.match(_column_text(line, COL_DESCRIPTION)):
            in_notes = True
            notes.append(line_text)
        elif current is not None:
            # A wrapped continuation of the previous item's part number / description.
            part_cont = _column_text(line, COL_PART_NUMBER)
            if part_cont:
                current["part_number"] += part_cont  # a code wrapped mid-token has no space
            desc_cont = _column_text(line, COL_DESCRIPTION)
            if desc_cont:
                current["description"] = f"{current['description']} {desc_cont}".strip()
    return items, False


def _cell_text(page, box: tuple[float, float, float, float]) -> str:
    x0, x1, top, bottom = box
    words = [w for w in page.extract_words() if w["x0"] >= x0 and w["x1"] <= x1 and top <= w["top"] <= bottom]
    return " ".join(w["text"] for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])))


def _ship_to_block(page) -> str:
    x_from, top_from, top_to = SHIP_TO_BOX
    words = [w for w in page.extract_words() if w["x0"] >= x_from and top_from <= w["top"] <= top_to]
    return "\n".join(_line_text(line) for line in _cluster_lines(words))


def _notes_fields(notes: list[str]) -> dict[str, str]:
    """Quote number, support term, shipping terms and the END USER INFO block."""
    fields = {
        "quote_number": "", "support_term": "", "shipping_terms": "",
        "end_user_name": "", "end_user_email": "", "end_user_phone": "", "end_user_po": "",
    }
    lines = [n.strip() for n in notes if n.strip()]
    for i, text in enumerate(lines):
        match = re.match(r"Quote\s*#:\s*(\S+)", text, re.IGNORECASE)
        if match:
            fields["quote_number"] = match.group(1)
        match = re.match(r"Support Term:\s*(\S+)", text, re.IGNORECASE)
        if match:
            fields["support_term"] = match.group(1)
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt != "-" and not nxt.startswith("**"):
                fields["shipping_terms"] = nxt
    for i, text in enumerate(lines):
        if text.startswith("**END USER"):
            for later in lines[i + 1:]:
                po = re.match(r"EU PO\s*#\s*(\S+)", later, re.IGNORECASE)
                if po:
                    fields["end_user_po"] = po.group(1)
                elif EMAIL_RE.search(later):
                    fields["end_user_email"] = EMAIL_RE.search(later).group(0)
                elif PHONE_RE.match(later):
                    fields["end_user_phone"] = later
                elif not fields["end_user_name"]:
                    fields["end_user_name"] = later
            break
    return fields


def parse_template(path: Path) -> dict:
    with open_pdf(path) as pdf:
        items: list[dict] = []
        notes: list[str] = []
        for page in pdf.pages:
            page_items, done = _parse_items_page(page, items[-1] if items else None, notes)
            items.extend(page_items)
            if done:
                break

        first = pdf.pages[0]
        fields = {key: _cell_text(first, box) for key, box in HEADER_CELLS.items()}
        fields["ship_to_block"] = _ship_to_block(first)

    fields.update(_notes_fields(notes))

    for item in items:
        match = TERM_RE.search(item["description"])
        item["terms"] = match.group(1) if match else ""

    ordered = (
        "po_number", "po_date", "vendor_number", "payment_terms", "reference", "ship_to_block",
        "quote_number", "support_term", "shipping_terms",
        "end_user_name", "end_user_email", "end_user_phone", "end_user_po",
    )
    return {"fields": {key: fields.get(key, "") for key in ordered}, "line_items": items}
