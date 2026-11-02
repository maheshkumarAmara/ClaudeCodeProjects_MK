"""Template parser for ADN Distribution GmbH purchase orders.

Unlike the coordinate-based layouts in `pdf_engine/layouts/`, ADN prints each
item as a multi-line block: a main row (position, item number, quantity,
prices, total, VAT), then a bracketed SKU line, a description line, and
optionally serial-number and support-period lines. Items run across six pages
with running "Balance c/f" totals, so this parser reads the text of every page
rather than a fixed box per field.

This only loads the template into the editor. There is no layout for ADN yet,
so generate/preview are rejected until one is added.
"""

import re
from decimal import Decimal
from pathlib import Path

import pdfplumber

from pdf_engine.extractor import open_pdf

# The item code (RUB...) is optional: some ADN POs print the main row without it,
# with the SKU only on the bracketed line below.
MAIN_ROW_RE = re.compile(r"^(\d+) (?:(RUB\d+) )?(\d[\d.,]* .+) (\d+) %$")
SKU_RE = re.compile(r"^\[([^\]]+)\]$")
# e.g. "RS-BT-EDG-PE-PP - Per 1 FETB Per Month": SKU followed by the unit of measure.
UNIT_RE = re.compile(r"^\S+ - (Per .+)$")
DESCRIPTION_RE = re.compile(r"^\d+ months? - .+$")
SERIAL_LABEL_RE = re.compile(r"^associated Serial Number: (.+)$")
SERIAL_LIST_RE = re.compile(r"^(?:[A-Z]{2}\d{6,}(?:,\s*)?)+$")
SUPPORT_PERIOD_RE = re.compile(r"^Support Period: .+$")
# Some ADN POs print the term under the description as a bare number ("12", "18") and
# others with its unit ("36 Months").
TERM_NUMBER_RE = re.compile(r"^\d+(?: months?)?$", re.IGNORECASE)

# Read from page 0 only.
HEADER_PATTERNS = {
    "po_number": r"Purchase order (\S+)",
    "po_date": r"Date: (\d{2}\.\d{2}\.\d{4})",
    # "Reference" and "number:" print on different lines; the value sits on the "number:" line.
    "reference_number": r"number: (\S+)$",
    "processed_by": r"Processed by: (.+)$",
    "quote_number": r"Quote: (\S+)$",
    "quote_date": r"DATED (\S+)$",
    "quote_creator": r"Quote Ersteller: ([^,]+),",
    "enduser_po": r"Endkunden PO: ([^,]+),",
    "reseller_po": r"Reseller PO: ([^,]+),",
}

# Read from the full document; these print on the last page.
TOTAL_PATTERNS = {
    "total": r"Sum total ([\d.,]+ [A-Z]{3})",
    "payment_terms": r"(Net payment within \d+ days)",
    # Printed on the same line as "Sum total", so match only the leading words.
    "delivery_terms": r"^(free carrier)\b",
}


# The Licensee address block sits in the right-hand column of the first page,
# below "Licensee address:" (about top 336 to 387, x from 398).
LICENSEE_X_RANGE = (395.0, 560.0)
LICENSEE_TOP_RANGE = (333.0, 396.0)


def _licensee_address(page) -> str:
    """Lines of the Licensee address block, joined with newlines."""
    words = [
        w
        for w in page.extract_words()
        if LICENSEE_TOP_RANGE[0] <= w["top"] <= LICENSEE_TOP_RANGE[1]
        and LICENSEE_X_RANGE[0] <= w["x0"] <= LICENSEE_X_RANGE[1]
    ]
    lines: dict[float, list[dict]] = {}
    for w in words:
        lines.setdefault(round(w["top"]), []).append(w)
    # "Licensee address:" is the label itself, not part of the address.
    text_lines = []
    for top in sorted(lines):
        text = " ".join(w["text"] for w in sorted(lines[top], key=lambda w: w["x0"]))
        if text.startswith("Licensee address:"):
            continue
        text_lines.append(text)
    return "\n".join(text_lines)


# The "Delivery / Effort address" block sits in the middle column of the first page,
# below its label (about top 336 to 387, x from 228 to 395).
DELIVERY_X_RANGE = (226.0, 394.0)
DELIVERY_TOP_RANGE = (333.0, 396.0)


def _delivery_address(page) -> list[str]:
    """Lines of the Delivery / Effort address block, top to bottom."""
    words = [
        w
        for w in page.extract_words()
        if DELIVERY_TOP_RANGE[0] <= w["top"] <= DELIVERY_TOP_RANGE[1]
        and DELIVERY_X_RANGE[0] <= w["x0"] <= DELIVERY_X_RANGE[1]
    ]
    lines: dict[float, list[dict]] = {}
    for w in words:
        lines.setdefault(round(w["top"]), []).append(w)
    text_lines = []
    for top in sorted(lines):
        text = " ".join(w["text"] for w in sorted(lines[top], key=lambda w: w["x0"]))
        if text.startswith("Delivery"):
            continue
        text_lines.append(text)
    return text_lines


def _delivery_fields(lines: list[str]) -> dict[str, str]:
    """Splits the delivery block into the ship-to fields, in the order ADN prints them:
    company (may wrap onto a second line), street, then 'postcode city', then country."""
    fields = {"ship_to_company": "", "ship_to_street": "", "ship_to_postcode": "", "ship_to_city": "", "ship_to_country": ""}
    if not lines:
        return fields
    fields["ship_to_company"] = lines[0]
    rest = lines[1:]
    # The company wraps when its second half is printed on its own line ("GmbH").
    if rest and rest[0].split()[0] in ("GmbH", "AG", "Ltd", "B.V.", "BV", "Inc."):
        fields["ship_to_company"] += " " + rest.pop(0)
    if rest:
        fields["ship_to_street"] = rest.pop(0)
    postcode_city = re.match(r"^(\d{4,5}) (.+)$", rest[0]) if rest else None
    if postcode_city:
        fields["ship_to_postcode"], fields["ship_to_city"] = postcode_city.group(1), postcode_city.group(2)
        rest.pop(0)
    if rest:
        fields["ship_to_country"] = rest[0]
    return fields


def _search(patterns: dict[str, str], text: str) -> dict[str, str]:
    values = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.MULTILINE)
        values[key] = match.group(1).strip() if match else ""
    return values


def _to_plain_number(text: str) -> str:
    # ADN prints EU-style numbers: "1.200" is 1200 and "210,6000" is 210.6000.
    return str(Decimal(text.replace(".", "").replace(",", ".")))


def _split_serials(text: str) -> list[str]:
    return [serial.strip() for serial in text.split(",") if serial.strip()]


def _parse_line_items(lines: list[str]) -> list[dict]:
    items: list[dict] = []
    current: dict | None = None
    for line in lines:
        main = MAIN_ROW_RE.match(line)
        if main:
            numbers = main.group(3).split()
            # Fall back to ADN's own item number until the SKU line is seen.
            current = {
                "pos": main.group(1),
                "item_number": main.group(2) or "",
                "part_number": main.group(2) or "",
                "description": "",
                "qty": _to_plain_number(numbers[0]),
                "unit_cost": _to_plain_number(numbers[-2]),
                # The "Price per unit" text exactly as printed ("5.868,0000"), for comparing
                # against a JSON without converting either side.
                "unit_cost_as_printed": numbers[-2],
                "pct_disc": "",
                "terms": "",
                "unit_text": "",
                "_serials": [],
            }
            items.append(current)
            continue
        if current is None:
            continue

        sku = SKU_RE.match(line)
        unit = UNIT_RE.match(line)
        if sku:
            current["part_number"] = sku.group(1)
        elif unit and not current["unit_text"]:
            current["unit_text"] = unit.group(1)
        elif DESCRIPTION_RE.match(line) and not current["description"]:
            current["description"] = line
        elif SERIAL_LABEL_RE.match(line):
            current["_serials"].extend(_split_serials(SERIAL_LABEL_RE.match(line).group(1)))
        elif SERIAL_LIST_RE.match(line):
            # Long serial lists wrap onto lines with no label of their own.
            current["_serials"].extend(_split_serials(line))
        elif SUPPORT_PERIOD_RE.match(line):
            current["terms"] = line
        elif TERM_NUMBER_RE.match(line) and not current["terms"]:
            current["terms"] = line

    for item in items:
        serials = item.pop("_serials")
        if serials:
            item["description"] = f"{item['description']} (Serial: {', '.join(serials)})".strip()
    return items


def parse_template(path: Path) -> dict:
    with open_pdf(path) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]
        licensee_address = _licensee_address(pdf.pages[0])
        # The shared visible-text filter drops this block's Verdana text (it is not under
        # a white box), so read it from the unfiltered page.
        with pdfplumber.open(path) as raw:
            delivery_lines = _delivery_address(raw.pages[0])
            raw_header_text = raw.pages[0].extract_text() or ""
            raw_full_text = "\n".join(page.extract_text() or "" for page in raw.pages)

    full_text = "\n".join(page_texts)
    fields = _search(HEADER_PATTERNS, page_texts[0])
    fields["licensee_address"] = licensee_address
    fields.update(_delivery_fields(delivery_lines))
    # "Processed by" and the first "E-mail:" line sit in the same unfiltered header text.
    contact_email = _search(
        {
            "contact": r"Processed by: (.+)$",
            "email": r"^E-mail: (\S+)$",
            # The first "Phone:" on the page is the contact's; ADN's footer repeats "Phone:"
            # further down, which the first match skips.
            "phone": r"Phone: (\+\S[^\n]*)$",
        },
        raw_header_text,
    )
    fields["ship_to_contact"] = contact_email["contact"]
    fields["ship_to_email"] = contact_email["email"]
    fields["ship_to_phone"] = contact_email["phone"]
    # The licensee company is the first line of the licensee address block.
    fields["licensee_company"] = licensee_address.splitlines()[0] if licensee_address else ""
    # The totals print in the template's Verdana text, which the visible-text filter drops,
    # so they come from the unfiltered text; the filtered text fills anything still blank.
    totals = _search(TOTAL_PATTERNS, raw_full_text)
    for key, value in _search(TOTAL_PATTERNS, full_text).items():
        totals[key] = totals.get(key) or value
    fields.update(totals)
    # Header fields printed in the template's Verdana text, which the visible-text filter
    # drops, so they are read from the unfiltered text. The date is "Date: 30.10.2026".
    unfiltered = _search(
        {
            "po_date": r"^Date: (\d{2}\.\d{2}\.\d{4})",
            "distributor_name": r"^(ADN – Advanced Digital Network Distribution GmbH)\b",
            "reseller_name": r"^Reseller address:\n(.+)$",
            "goods_value": r"Value of goods ([\d.,]+) [A-Z]{3}",
            "vat_amount": r"VAT \d+% ([\d.,]+) [A-Z]{3}",
            "currency": r"Sum total [\d.,]+ ([A-Z]{3})",
        },
        raw_full_text,
    )
    for key, value in unfiltered.items():
        fields[key] = value or fields.get(key, "")
    # The invoice address is ADN's own company line, the same name as the distributor.
    fields["bill_to_name"] = fields.get("distributor_name", "")
    # The contingency note sits on the first page, under the Enduser-PO line.
    fields["contingency_note"] = _search(
        {"note": r"^(ADN Distribution GmbH ACCEPTS ALL ADDITIONAL TERMS ON .+)$"}, raw_header_text
    )["note"]
    return {
        "fields": fields,
        "line_items": _parse_line_items(full_text.splitlines()),
        # Totals are recalculated from the line items when the PDF is generated.
        "hidden_fields": ["total"],
    }
