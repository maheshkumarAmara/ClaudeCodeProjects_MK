"""Template parser for Exclusive Networks (Norway) purchase orders.

The sample is a portrait, 2-page document: a header (PO / SO numbers, dates,
vendor code, ExN contact, a comment line), three address blocks (End User,
Reseller, Shipping Address), shipping details and incoterms, then an items
table that runs across both pages, and a totals footer on the last page.

Each item is a main row (SKU, Quote ID, Qty, U.P, Disc. U.P, Net Amount)
followed by wrapped description lines and a "Terms N months" line. Some items
also carry a block of "Supported S/N:", "Contract Start Date:" and "Contract
End Date:" lines. The sample does not make clear whether such a block belongs to
the row printed above it or below it; it is attached to the row printed
BELOW it, because the block sits a tight 16pt above that row's SKU line (the
gap between an item's own lines is 12-18pt) while it starts a normal 22-24pt
after the previous item's Terms line.

Beyond the editor's six columns each item keeps its other printed values
(`quote_id`, `disc_unit_price`, `amount`, `serial_number`,
`contract_start_date`, `contract_end_date`) so nothing printed is lost; they
are not shown in the form. The static letterhead (company address, VAT / company
registration, the "Phone / Email" footer line) is not loaded.
"""

import re
from pathlib import Path

import pdfplumber

LINE_TOLERANCE = 2.0

# Items table columns (x0 ranges), measured from the sample.
COL_PART_NUMBER = (0, 140)
COL_QUOTE_ID = (140, 225)
COL_QTY = (225, 300)
COL_UNIT_PRICE = (300, 380)
COL_DISC_UNIT_PRICE = (380, 500)
COL_AMOUNT = (500, 700)

# Address blocks (x0 ranges): End User | Reseller | Shipping Address.
BLOCK_END_USER = (0, 205)
BLOCK_RESELLER = (205, 405)
BLOCK_SHIPPING = (405, 700)

# Header values print a little below their labels.
VALUE_BELOW = (8.0, 25.0)

ITEM_BLOCK_LABELS = {
    "Supported S/N:": "serial_number",
    "Contract Start Date:": "contract_start_date",
    "Contract End Date:": "contract_end_date",
}

_QUOTE_ID_RE = re.compile(r"^Q-\d+$")
_AMOUNT = r"([\d,]+\.\d{2})"


def _plain_number(text: str) -> str:
    """"3,000" -> "3000", "23,450.00" -> "23450.00" (the form holds plain numbers)."""
    return text.replace(",", "").strip()


def _text(words: list[dict]) -> str:
    return " ".join(w["text"] for w in sorted(words, key=lambda w: w["x0"]))


def _in_x(words: list[dict], x_range: tuple[float, float]) -> list[dict]:
    return [w for w in words if x_range[0] <= w["x0"] < x_range[1]]


def _cluster_lines(words: list[dict]) -> list[tuple[float, list[dict]]]:
    clusters: list[list] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if clusters and w["top"] - clusters[-1][0] <= LINE_TOLERANCE:
            clusters[-1][1].append(w)
        else:
            clusters.append([w["top"], [w]])
    return [(top, sorted(ws, key=lambda w: w["x0"])) for top, ws in clusters]


def _value_below(words: list[dict], label_top: float | None, x_range: tuple[float, float]) -> str:
    if label_top is None:
        return ""
    lo, hi = label_top + VALUE_BELOW[0], label_top + VALUE_BELOW[1]
    return _text([w for w in _in_x(words, x_range) if lo <= w["top"] < hi])


def _label_top(words: list[dict], text: str, x_range: tuple[float, float], min_top: float = 0.0) -> float | None:
    tops = [w["top"] for w in _in_x(words, x_range) if w["text"] == text and w["top"] > min_top]
    return min(tops) if tops else None


def _parse_header(page) -> dict[str, str]:
    words = page.extract_words()
    po_label = _label_top(words, "PO", (0, 30))
    so_label = _label_top(words, "SO", (0, 30))
    # "Requested Delivery Date" prints on two lines, so anchor its value on the
    # label's second line ("Date"): the value sits on the same row as the SO
    # number's value, not 8-25pt under the SO label.
    requested_label = _label_top(words, "Requested", (110, 205))
    requested_date_label = _label_top(words, "Date", (110, 205), min_top=(requested_label or 0.0))
    comment_label = _label_top(words, "Comment", (0, 30))
    return {
        "po_number": _value_below(words, po_label, (0, 110)),
        "po_date": _value_below(words, po_label, (110, 205)),
        "vendor_code": _value_below(words, po_label, (205, 330)),
        "so_number": _value_below(words, so_label, (0, 110)),
        "requested_delivery_date": _value_below(words, requested_date_label, (110, 205)),
        "exn_contact": _value_below(words, so_label, (205, 330)),
        "comment": _value_below(words, comment_label, (0, 700)),
    }


def _parse_blocks(page) -> dict[str, str]:
    values = {
        "end_user_block": "",
        "reseller_block": "",
        "reseller_po": "",
        "ship_to_block": "",
        "shipping_details": "",
        "incoterms": "",
    }
    words = page.extract_words()
    blocks_label = _label_top(words, "Reseller", (205, 215))
    details_label = _label_top(words, "Shipping", (0, 30))
    if blocks_label is None or details_label is None:
        return values
    region = [w for w in words if blocks_label + 8.0 <= w["top"] < details_label - 2.0]

    def block_lines(x_range: tuple[float, float]) -> list[str]:
        return [_text(ws) for _, ws in _cluster_lines(_in_x(region, x_range))]

    values["end_user_block"] = "\n".join(block_lines(BLOCK_END_USER))
    reseller_lines = []
    for line in block_lines(BLOCK_RESELLER):
        if line.startswith("Reseller PO:"):
            values["reseller_po"] = line[len("Reseller PO:"):].strip()
        else:
            reseller_lines.append(line)
    values["reseller_block"] = "\n".join(reseller_lines)
    values["ship_to_block"] = "\n".join(block_lines(BLOCK_SHIPPING))

    # "Shipping Details  FedEx Priority#..." -- the value sits on the label's own line.
    values["shipping_details"] = _text(
        [w for w in words if w["x0"] >= 95 and abs(w["top"] - details_label) <= LINE_TOLERANCE]
    )
    for _, ws in _cluster_lines([w for w in words if w["top"] > details_label + 2.0 and w["x0"] < 30]):
        if ws[0]["text"] == "Incoterms:":
            values["incoterms"] = _text(
                [w for w in words if abs(w["top"] - ws[0]["top"]) <= LINE_TOLERANCE and w["x0"] > ws[0]["x0"]]
            )
            break
    return values


def _is_item_row(line: list[dict]) -> bool:
    return line[0]["x0"] < COL_PART_NUMBER[1] and any(
        _QUOTE_ID_RE.match(w["text"]) for w in _in_x(line, COL_QUOTE_ID)
    )


def _parse_items_page(page, items: list[dict], pending: dict[str, str]) -> None:
    """Appends this page's items to `items`. `pending` carries a serial / contract
    block across lines (and pages) until the item row it belongs to arrives."""
    words = page.extract_words()
    header = next((w for w in words if w["text"] == "SKU" and w["x0"] < 30), None)
    if header is None:
        return
    ends = [
        w["top"]
        for w in words
        if w["top"] > header["top"] and w["x0"] < 30 and w["text"] in ("Tax", "Phone:")
    ]
    end_top = min(ends) if ends else page.height
    body = [w for w in words if header["top"] + 8.0 < w["top"] < end_top - 1.0]

    awaiting: str | None = None
    for _, line in _cluster_lines(body):
        text = _text(line)
        if awaiting:
            pending[awaiting] = text
            awaiting = None
            continue
        if text in ITEM_BLOCK_LABELS:
            awaiting = ITEM_BLOCK_LABELS[text]
            continue
        if _is_item_row(line):
            item = {
                "part_number": _text(_in_x(line, COL_PART_NUMBER)),
                "description": "",
                "qty": _plain_number(_text(_in_x(line, COL_QTY))),
                "unit_cost": _plain_number(_text(_in_x(line, COL_UNIT_PRICE))),
                "pct_disc": "",
                "terms": "",
                "quote_id": _text(_in_x(line, COL_QUOTE_ID)),
                "disc_unit_price": _plain_number(_text(_in_x(line, COL_DISC_UNIT_PRICE))),
                "amount": _plain_number(_text(_in_x(line, COL_AMOUNT))),
                "serial_number": "",
                "contract_start_date": "",
                "contract_end_date": "",
            }
            item.update(pending)
            pending.clear()
            items.append(item)
        elif items and text.startswith("Terms"):
            items[-1]["terms"] = text[len("Terms"):].strip()
        elif items:
            items[-1]["description"] = f"{items[-1]['description']} {text}".strip()


FOOTER_PATTERNS = {
    "subtotal": rf"Subtotal\s+{_AMOUNT}",
    "tax_total": rf"Tax Total\s+{_AMOUNT}",
    "total": rf"Total \([A-Z]{{3}}\)\s+{_AMOUNT}",
    "currency": r"Total \(([A-Z]{3})\)",
    "payment_terms": r"Payment Terms:\s*(.+)$",
}
_TAX_ROW_RE = re.compile(rf"^(\d+(?:\.\d+)?%)\s+{_AMOUNT}\s+{_AMOUNT}\s+{_AMOUNT}\s*$", re.MULTILINE)


def _parse_footer(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    tax_row = _TAX_ROW_RE.search(text)
    values["tax_rate"] = tax_row.group(1) if tax_row else ""
    values["tax_net_amt"] = tax_row.group(2) if tax_row else ""
    values["tax_amt"] = tax_row.group(3) if tax_row else ""
    values["gross_amt"] = tax_row.group(4) if tax_row else ""
    for key, pattern in FOOTER_PATTERNS.items():
        match = re.search(pattern, text, re.MULTILINE)
        values[key] = match.group(1).strip() if match else ""
    return values


def parse_template(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        fields = _parse_header(pdf.pages[0])
        fields.update(_parse_blocks(pdf.pages[0]))

        items: list[dict] = []
        pending: dict[str, str] = {}
        for page in pdf.pages:
            _parse_items_page(page, items, pending)

        fields.update(_parse_footer(pdf.pages[-1].extract_text() or ""))
    return {"fields": fields, "line_items": items}
