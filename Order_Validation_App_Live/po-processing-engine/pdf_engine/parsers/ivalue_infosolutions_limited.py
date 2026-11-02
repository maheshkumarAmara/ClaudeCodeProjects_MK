"""Template parser for iValue InfoSolutions Limited purchase orders.

The sample is a portrait, 2-page printout: a letterhead with the iValue logo, then a
boxed header (Supplier, Purchase Order / PO Date / Shipping Terms / Term of Payment,
Bill To, Ship To), an items table with a ruled header, and on the last page the
Quote No. and an "Additional Information" band (End Customer, Reseller, Freight
Forwarder). The totals box and the Terms and Conditions sit at the foot of page 1.

Each item is one main row (No., OEM Part No., Item Type / HSN Code, Description,
Quantity + unit, Unit Price, Amount). A long part number or description wraps onto
following lines that carry no No. value; those lines are joined onto the row above.
The source system cuts descriptions short, so what is printed is loaded as is.

Items carry the editor's six columns (`part_number`, `description`, `qty`,
`unit_cost`, `pct_disc`, `terms`) plus the printed values so a loaded template keeps
them: `line_no`, `item_type`, `unit` ("NOS"), `currency` ("USD") and `amount` (the
printed Amount). `amount_basis` and `description_basis` follow the Innocom parser, so
a generator can tell whether a row was edited.
"""

import re
from pathlib import Path

from pdf_engine.extractor import open_pdf

LINE_TOLERANCE = 2.0

# Items table columns (x ranges of a word's x0), measured from the sample.
COL_LINE = (25, 42)
COL_PART_NUMBER = (42, 118)
COL_ITEM_TYPE = (118, 215)
COL_DESCRIPTION = (215, 378)
COL_QTY = (378, 418)
COL_UNIT_PRICE = (418, 520)
COL_AMOUNT = (520, 600)

# The header and address columns split at this x (the right-hand column starts near 307).
COLUMN_SPLIT = 305.0

_NUMBER_RE = re.compile(r"^[\d,]+(?:\.\d+)?$")


def _plain_number(text: str) -> str:
    """"80,517.86" -> "80517.86" (the form holds plain numbers)."""
    return text.replace(",", "").strip()


def _text(words: list[dict]) -> str:
    return " ".join(w["text"] for w in sorted(words, key=lambda w: w["x0"])).strip()


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


def _is_main_row(line: list[dict]) -> bool:
    first = _in_x(line, COL_LINE)
    return bool(first) and first[0]["text"].isdigit() and bool(_in_x(line, COL_PART_NUMBER))


def _join_wrapped(first: str, rest: str) -> str:
    """A part number wrapped after a hyphen ("RS-BT-FE-PE-" + "PP") is glued back together."""
    if not rest:
        return first
    if not first:
        return rest
    return first + rest if first.endswith("-") else f"{first} {rest}"


def _parse_items(page, items: list[dict]) -> None:
    """Appends this page's items. A page without the items table header adds nothing."""
    words = page.extract_words()
    header = next((w for w in words if w["text"] == "No." and w["x0"] < 35), None)
    if header is None:
        return
    total_label = next(
        (w for w in words if w["text"] == "Total" and w["x0"] > 400 and w["top"] > header["top"]),
        None,
    )
    end_top = total_label["top"] if total_label else page.height
    body = [w for w in words if header["top"] + 12.0 < w["top"] < end_top - 2.0]

    current: dict | None = None
    for _, line in _cluster_lines(body):
        if _is_main_row(line):
            qty_words = _in_x(line, COL_QTY)
            unit = qty_words[-1]["text"] if len(qty_words) > 1 else ""
            qty = _plain_number(qty_words[0]["text"]) if qty_words else ""
            unit_cost = _plain_number(_text(_in_x(line, COL_UNIT_PRICE)))
            current = {
                "part_number": _text(_in_x(line, COL_PART_NUMBER)),
                "description": _text(_in_x(line, COL_DESCRIPTION)),
                # The description as printed, line by line; the generator redraws these
                # lines as is while "description" is unedited.
                "description_lines": [_text(_in_x(line, COL_DESCRIPTION))],
                "qty": qty,
                "unit_cost": unit_cost,
                "pct_disc": "",
                "terms": "",
                "line_no": _text(_in_x(line, COL_LINE)),
                "item_type": _text(_in_x(line, COL_ITEM_TYPE)),
                "unit": unit,
                "currency": "USD",
                "amount": _plain_number(_text(_in_x(line, COL_AMOUNT))),
            }
            items.append(current)
        elif current is not None:
            part_extra = _text(_in_x(line, COL_PART_NUMBER))
            if part_extra:
                current["part_number"] = _join_wrapped(current["part_number"], part_extra)
            extra = _text(_in_x(line, COL_DESCRIPTION))
            if extra:
                current["description"] = f"{current['description']} {extra}".strip()
                current["description_lines"].append(extra)
    for item in items:
        item["amount_basis"] = f"{item['qty']}|{item['unit_cost']}|{item['terms']}"
        item["description_basis"] = item["description"]


def _after(text: str, label: str) -> str:
    # [ \t]* not \s*: an empty value must not run on into the next line.
    match = re.search(rf"^{re.escape(label)}[ \t]*(.*)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _block(text: str, start: str, end: str) -> str:
    """The lines between `start` and `end` (both labels excluded), joined with newlines."""
    match = re.search(rf"{re.escape(start)}\s*\n(.*?)\n{re.escape(end)}", text, re.DOTALL)
    if not match:
        return ""
    return "\n".join(ln.strip() for ln in match.group(1).splitlines() if ln.strip())


def _column_text(page, left: bool) -> str:
    x0, x1 = (0.0, COLUMN_SPLIT) if left else (COLUMN_SPLIT, page.width)
    return page.crop((x0, 0, x1, page.height)).extract_text() or ""


def _block_below(page, label: str, x0: float, x1: float) -> str:
    """Text under the "Additional Information" column heading `label`, down to the
    signature line, within the column x0..x1."""
    words = page.extract_words()
    heading = next((w for w in words if w["text"] == label), None)
    signature = next((w for w in words if w["text"] == "Authorized"), None)
    if heading is None:
        return ""
    bottom = signature["top"] if signature else page.height
    crop = page.crop((x0, heading["top"] + 12.0, x1, bottom - 2.0))
    return "\n".join(ln.strip() for ln in (crop.extract_text() or "").splitlines() if ln.strip())


def parse_template(path: Path) -> dict:
    with open_pdf(path) as pdf:
        first = pdf.pages[0]
        last = pdf.pages[-1]
        first_full = first.extract_text() or ""
        last_full = last.extract_text() or ""
        left_first = _column_text(first, left=True)
        right_first = _column_text(first, left=False)
        items: list[dict] = []
        for page in pdf.pages:
            _parse_items(page, items)
        end_customer = _block_below(last, "End", 0.0, 210.0)
        reseller = _block_below(last, "Reseller", 210.0, 398.0)
        freight = _block_below(last, "Freight", 398.0, last.width)

    fields: dict[str, str] = {}
    fields["supplier"] = _block(left_first, "Supplier :", "Bill To :")
    fields["po_number"] = _after(right_first, "Purchase Order :")
    fields["po_date"] = _after(right_first, "PO Date :")
    fields["delivery_date"] = _after(right_first, "Delivery Date :")
    fields["shipping_terms"] = _after(right_first, "Shipping Terms :")
    fields["port_of_destination"] = _after(right_first, "Port of Destination:")
    fields["payment_terms"] = _after(right_first, "Term of Payment :")
    fields["bill_to"] = _block(left_first, "Bill To :", "GST No :")
    fields["ship_to"] = _block(right_first, "Ship To :", "Contact Person:")
    fields["contact_name"] = _after(right_first, "Contact Person:")
    fields["contact_phone"] = _after(right_first, "Contact No:")
    fields["contact_email"] = _after(right_first, "Email id:")
    fields["gst_number"] = _after(left_first, "GST No :")
    term = re.search(r"Term \(Mos\):\s*(\d+)", first_full)
    fields["term_months"] = term.group(1) if term else ""
    fields["customer_po"] = _after(first_full, "Customer PO no:")
    quote = re.search(r"Quote No\.:\s*(\S+)", last_full)
    fields["quote_number"] = quote.group(1) if quote else ""
    fields["end_customer"] = end_customer
    fields["reseller"] = reseller
    fields["freight_forwarder"] = freight

    total = re.search(r"^Total\s+([\d,]+\.\d{2})\s*$", first_full, re.MULTILINE)
    fields["subtotal"] = _plain_number(total.group(1)) if total else ""
    discount = re.search(r"^Discount\s+([\d,.]+)", first_full, re.MULTILINE)
    fields["discount"] = _plain_number(discount.group(1)) if discount else ""
    for key, label in (("cgst", "CGST"), ("sgst", "SGST"), ("igst", "IGST")):
        tax = re.search(rf"^{label} @[\d.]+%\s+([\d,.]+)", first_full, re.MULTILINE)
        fields[key] = _plain_number(tax.group(1)) if tax else ""
    grand = re.search(r"Grand Total\s+([A-Z]{3})\s+([\d,]+\.\d{2})", first_full)
    fields["currency"] = grand.group(1) if grand else "USD"
    fields["total"] = _plain_number(grand.group(2)) if grand else ""
    return {"fields": fields, "line_items": items}
