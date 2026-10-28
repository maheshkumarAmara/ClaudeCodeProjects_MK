"""Template parser for NOX Co.,LTD. purchase orders.

The sample is a single portrait "ORDER SHEET": a header block (order number and
date), a label/value block (reference, shipment, payment, end user, quote no),
bill-to / ship-to, an items table, the total, the freight forwarder lines and a
footer with the end-user PO and quote terms. Label/value rows are read by
x-position (labels sit left of x=95, values start at x=99), and the items
table is split into columns the same way.

This only loads the template into the editor. There is no generator for NOX
yet, so generate/preview are rejected until one is added.
"""

import re
from pathlib import Path

import pdfplumber

LINE_TOLERANCE = 2.0

# Label / value rows: label text (left of VALUE_LEFT) -> field key.
VALUE_LEFT = 95.0
LABEL_ROWS = {
    "Reference": "reference",
    "Shipment": "shipment",
    "Insureance": "insurance",  # sic: the sample's own spelling
    "Freight": "freight",
    "Payment": "payment_terms",
    "End User": "end_user",
    "Quote No": "quote_number",
}
LABEL_ROWS_TOP = (135.0, 238.0)  # through the second "Please Send ..." address row

# Items table columns (x0 ranges), measured from the sample.
COL_POS = (10, 28)
COL_PART_NUMBER = (28, 172)
COL_DESCRIPTION = (172, 410)
COL_TERM = (410, 440)
COL_UNIT_PRICE = (440, 500)
COL_QTY = (500, 540)
ITEMS_TOP = (348.0, 459.0)
# A row's TERM value prints about a point above its position number.
ROW_TOP_SLACK = 3.0

HEADER_PATTERNS = {
    "po_number": r"Order No\. (\S+)",
    "po_date": r"Order Date:(\w+ \d+ \d+)",
    "total": r"Total (\$[\d.,]+)",
    "end_user_po": r"End user PO#: (\S+)",
    "quote_date": r"dated (\S+)",
}


def _cluster_lines(words: list[dict]) -> list[list[dict]]:
    """Groups words onto printed lines, tolerating mixed font sizes on one row."""
    lines: list[list[dict]] = []
    anchor = None
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if anchor is not None and w["top"] - anchor <= LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
            anchor = w["top"]
    return lines


def _text(words: list[dict], x_range: tuple[float, float]) -> str:
    return " ".join(
        w["text"] for w in sorted(words, key=lambda w: w["x0"]) if x_range[0] <= w["x0"] < x_range[1]
    )


def _line_text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"]))


def _plain_number(text: str) -> str:
    # The sample prints US-style amounts ("$20,306.52").
    return text.replace("$", "").replace(",", "").strip()


def _parse_header(page) -> dict[str, str]:
    text = page.extract_text() or ""
    values = {}
    for key, pattern in HEADER_PATTERNS.items():
        match = re.search(pattern, text)
        values[key] = match.group(1).strip() if match else ""
    return values


def _parse_label_rows(page) -> dict[str, str]:
    words = [w for w in page.extract_words() if LABEL_ROWS_TOP[0] <= w["top"] < LABEL_ROWS_TOP[1]]
    values = {key: "" for key in LABEL_ROWS.values()}
    values["order_ack_email"] = ""
    values["shipping_notice_email"] = ""
    pending_email_key = None
    for line in _cluster_lines(words):
        label = _text(line, (0, VALUE_LEFT))
        value = _text(line, (VALUE_LEFT, 700))
        full_line = _line_text(line)
        if label in LABEL_ROWS:
            values[LABEL_ROWS[label]] = value
            pending_email_key = None
        # These two labels run past x=95, so match on the whole printed line.
        elif full_line.startswith("Please Send Order Acknowledgement"):
            pending_email_key = "order_ack_email"
        elif full_line.startswith("Please Send Shipping Notification"):
            pending_email_key = "shipping_notice_email"
        elif not label and value and pending_email_key:
            # The address prints on the line below its "Please Send ..." label.
            values[pending_email_key] = value
            pending_email_key = None
    return values


def _parse_bill_ship(page) -> dict[str, str]:
    """Bill To & Ship To block: company, two address lines, TEL/FAX, mail + contact."""
    words = [w for w in page.extract_words() if 248.0 <= w["top"] < 290.0 and w["x0"] >= VALUE_LEFT]
    lines = [_line_text(line) for line in _cluster_lines(words)]
    values = {
        "bill_to_company": "",
        "bill_to_address": "",
        "bill_to_tel_fax": "",
        "bill_to_mail": "",
        "bill_to_contact": "",
    }
    if lines:
        values["bill_to_company"] = lines[0]
    address_lines = [line for line in lines[1:] if not line.startswith(("TEL:", "Mail:"))]
    values["bill_to_address"] = " ".join(address_lines)
    for line in lines[1:]:
        if line.startswith("TEL:"):
            values["bill_to_tel_fax"] = line
        elif line.startswith("Mail:"):
            mail = re.match(r"Mail:\s*(\S+)\s+Contact:\s*(.+)$", line)
            if mail:
                values["bill_to_mail"], values["bill_to_contact"] = mail.group(1), mail.group(2).strip()
    return values


def _parse_items(page) -> list[dict]:
    """Each row is anchored on its position number (1, 2, 3 ...) rather than
    clustered by `top`: the description prints in a smaller font whose top can
    sit a point or more away from the row's own, and the TERM value sits a
    couple of points above it, so clustering splits one row into several."""
    words = [w for w in page.extract_words() if ITEMS_TOP[0] <= w["top"] < ITEMS_TOP[1]]
    anchors = sorted(
        (w for w in words if COL_POS[0] <= w["x0"] < COL_POS[1] and w["text"].isdigit()),
        key=lambda w: w["top"],
    )
    items: list[dict] = []
    for index, anchor in enumerate(anchors):
        row_top = anchor["top"] - ROW_TOP_SLACK
        next_top = anchors[index + 1]["top"] - ROW_TOP_SLACK if index + 1 < len(anchors) else ITEMS_TOP[1]
        row = [w for w in words if row_top <= w["top"] < next_top]
        part_number = _text(row, COL_PART_NUMBER)
        if not part_number:
            continue
        items.append(
            {
                "part_number": part_number,
                "description": _text(row, COL_DESCRIPTION),
                "qty": _plain_number(_text(row, COL_QTY)),
                "unit_cost": _plain_number(_text(row, COL_UNIT_PRICE)),
                "pct_disc": "",
                "terms": _text(row, COL_TERM),
            }
        )
    return items


def _parse_shipping(page) -> dict[str, str]:
    words = page.extract_words()
    # "Shipping Term:" prints at the left of the Total line, run together with
    # its value ("Term:FCA"), so pdfplumber returns one word that starts inside
    # the label. Read the whole row and strip the label off the front.
    shipping_row = " ".join(
        w["text"]
        for w in sorted(words, key=lambda w: w["x0"])
        if 459.0 <= w["top"] < 466.0 and w["x0"] < 450
    )
    shipping_term = re.sub(r"^Shipping Term:\s*", "", shipping_row)
    forwarder = [
        _line_text(line)
        for line in _cluster_lines([w for w in words if 478.0 <= w["top"] < 495.0])
    ]
    return {
        "shipping_term": shipping_term,
        "forwarder": forwarder[0] if forwarder else "",
        "forwarder_contact": forwarder[1] if len(forwarder) > 1 else "",
    }


def _parse_signature(page) -> dict[str, str]:
    words = [w for w in page.extract_words() if 620.0 <= w["top"] < 645.0]
    lines = [_line_text(line) for line in _cluster_lines(words)]
    return {
        "signatory": lines[0] if lines else "",
        "signatory_title": lines[1] if len(lines) > 1 else "",
    }


def parse_template(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        fields = _parse_header(page)
        fields.update(_parse_label_rows(page))
        fields.update(_parse_bill_ship(page))
        fields.update(_parse_shipping(page))
        fields.update(_parse_signature(page))
        items = _parse_items(page)
    return {"fields": fields, "line_items": items}
