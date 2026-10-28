"""Template parser for Networld Corporation purchase-order detail sheets.

The sample is a single landscape page: a heading ("Details of PO# <number>",
"Quote #: <quote>"), a ruled items grid (Product Code | Product Description | Qty
| Term | Net Total Price) ending in a Total row, and a block of label / value lines
(Incoterms, Payment Terms, notification and billing emails, End User Name / PO#,
the forwarder's details, the ship-to address and a "mail address").

Words are positioned by x-offset and print with no real spaces between some of
them, so the page is read with a tight x tolerance and re-joined with single
spaces.

The grid has no unit-price column: each row prints a Net Price, the extended
amount. The editor's `unit_cost` is that Net Price divided by `qty` -- the whole-
term price per unit, which is also what a Salesforce quote line carries. `terms`
(the Term column) is a display value that does not enter the arithmetic, so a
row's Net Price is always qty x unit_cost. A loaded row also keeps its printed
`amount`, plus an `amount_basis` (qty|unit_cost|terms as loaded) so the generator
can tell whether the printed figure still applies or the row was edited. Because
`unit_cost` is rounded to 6 decimals, an unedited row reprints its original
amount exactly.

Static labels, the logo and the grid itself stay in the template. Not loaded: the
Total row (recomputed from the rows) and the labels.
"""

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

X_TOLERANCE = 1.5
LINE_TOLERANCE = 2.0

# Items grid columns (x ranges, from the grid's vertical rules).
COL_CODE = (23.5, 178.5)
COL_DESCRIPTION = (178.5, 547.5)
COL_QTY = (547.5, 591.0)
COL_TERM = (591.0, 642.5)
COL_AMOUNT = (642.5, 730.5)
GRID_LEFT, GRID_RIGHT = 23.5, 730.5
HEADER_BOTTOM = 146.0  # bottom of the teal column-header band
VALUE_X = 178.0  # the label / value block's value column

# The label / value lines: label text (as printed, spaces removed) -> field key.
VALUE_LABELS = {
    "Incoterms": "incoterms",
    "PaymentTerms": "payment_terms",
    "Order/shipping/licensenotification": "order_notification_email",
    "Emailforbillinginvoice": "billing_email",
    "EndUserName": "end_user_name",
    "EndUserPO#": "end_user_po",
    "CompanyName": "forwarder_company",
    "Phone#": "forwarder_phone",
    "Fax#": "forwarder_fax",
    "mailaddress": "ship_to_mail",
}

_MONEY_RE = re.compile(r"^\$?-?[\d,]+(?:\.\d+)?$")


def _plain(text: str) -> str:
    """"$120,384.00" -> "120384.00"; "1,120" -> "1120"."""
    return text.replace("$", "").replace(",", "").strip()


def _text(words: list[dict]) -> str:
    return " ".join(w["text"] for w in sorted(words, key=lambda w: w["x0"]))


def _in_x(words: list[dict], x_range: tuple[float, float]) -> list[dict]:
    return [w for w in words if x_range[0] <= w["x0"] < x_range[1]]


def _lines(words: list[dict]) -> list[tuple[float, list[dict]]]:
    clusters: list[list] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if clusters and abs(w["top"] - clusters[-1][0]) <= LINE_TOLERANCE:
            clusters[-1][1].append(w)
        else:
            clusters.append([w["top"], [w]])
    return [(top, sorted(ws, key=lambda w: w["x0"])) for top, ws in clusters]


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _to_decimal(text: str) -> Decimal:
    try:
        return Decimal(_plain(text))
    except InvalidOperation:
        return Decimal("0")


def _parse_heading(words: list[dict]) -> dict[str, str]:
    values = {"po_number": "", "quote_number": ""}
    for top, line in _lines([w for w in words if w["top"] < 110]):
        label = "".join(w["text"] for w in line if w["x0"] < VALUE_X)
        right = [w for w in line if w["x0"] >= VALUE_X]
        if label.startswith("DetailsofPO#"):
            # The PO number prints right-aligned in a green band, far from its label.
            numbers = [w["text"] for w in line if re.fullmatch(r"\d{6,}", w["text"])]
            values["po_number"] = numbers[-1] if numbers else _text(right)
        elif label.startswith("Quote#"):
            values["quote_number"] = _text(right)
    return values


def _parse_items(words: list[dict]) -> tuple[list[dict], float]:
    """Returns (items, top of the Total row's text)."""
    body = [w for w in words if w["top"] > HEADER_BOTTOM]
    items: list[dict] = []
    total_top = 0.0
    for top, line in _lines(body):
        # The Total row prints "Total" in the Term column, with nothing in the code
        # or description columns; everything below it is the label / value block.
        in_term = _text(_in_x(line, (600.0, 645.0)))
        if in_term == "Total" and not _in_x(line, COL_CODE) and not _in_x(line, COL_DESCRIPTION):
            total_top = top
            break
        code = _text(_in_x(line, COL_CODE))
        description = _text(_in_x(line, COL_DESCRIPTION))
        if not code and not description:
            continue
        qty = _plain(_text(_in_x(line, COL_QTY)))
        terms = _plain(_text(_in_x(line, COL_TERM)))
        amount = _plain(_text(_in_x(line, COL_AMOUNT)))
        qty_d = _to_decimal(qty)
        unit_cost = _money(_to_decimal(amount) / qty_d) if qty_d else ""
        if unit_cost and "." in unit_cost:
            unit_cost = f"{_to_decimal(amount) / qty_d:.6f}".rstrip("0").rstrip(".")
        items.append(
            {
                "part_number": code,
                "description": description,
                "qty": qty,
                "unit_cost": unit_cost,
                "pct_disc": "",
                "terms": terms,
                "amount": amount,
                "amount_basis": f"{qty}|{unit_cost}|{terms}",
            }
        )
    return items, total_top


def _parse_value_block(words: list[dict], start_top: float) -> dict[str, str]:
    values = {key: "" for key in VALUE_LABELS.values()}
    values.update(
        {
            "forwarder_contact_1": "",
            "forwarder_contact_2": "",
            "ship_to_block": "",
        }
    )
    lines = _lines([w for w in words if w["top"] > start_top + 4.0])
    in_forwarder = False
    in_ship_to = False
    contacts: list[str] = []
    ship_lines: list[str] = []
    for _, line in lines:
        label = "".join(w["text"] for w in line if w["x0"] < VALUE_X)
        value = _text([w for w in line if w["x0"] >= VALUE_X])
        if label.startswith("NetworldForwarderInformation"):
            in_forwarder, in_ship_to = True, False
            continue
        if label.startswith("SHIPTO"):
            in_forwarder, in_ship_to = False, True
            ship_lines.append(value)
            continue
        key = VALUE_LABELS.get(label)
        if key == "ship_to_mail":
            in_ship_to = False
        if key:
            values[key] = value
            continue
        if in_forwarder and value and not label:
            contacts.append(value)
        elif in_ship_to and value and not label:
            ship_lines.append(value)
    values["forwarder_contact_1"] = contacts[0] if contacts else ""
    values["forwarder_contact_2"] = contacts[1] if len(contacts) > 1 else ""
    values["ship_to_block"] = "\n".join(ship_lines)
    return values


def parse_template(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(x_tolerance=X_TOLERANCE, keep_blank_chars=False)

    fields = _parse_heading(words)
    items, total_top = _parse_items(words)
    fields.update(_parse_value_block(words, total_top))
    return {"fields": fields, "line_items": items}
