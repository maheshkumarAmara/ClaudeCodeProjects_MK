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

MAIN_ROW_RE = re.compile(r"^(\d+) (RUB\d+) (.+) (\d+) %$")
SKU_RE = re.compile(r"^\[([^\]]+)\]$")
# e.g. "RS-BT-EDG-PE-PP - Per 1 FETB Per Month": SKU followed by the unit of measure.
UNIT_RE = re.compile(r"^\S+ - (Per .+)$")
DESCRIPTION_RE = re.compile(r"^\d+ months? - .+$")
SERIAL_LABEL_RE = re.compile(r"^associated Serial Number: (.+)$")
SERIAL_LIST_RE = re.compile(r"^(?:[A-Z]{2}\d{6,}(?:,\s*)?)+$")
SUPPORT_PERIOD_RE = re.compile(r"^Support Period: .+$")

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
                "item_number": main.group(2),
                "part_number": main.group(2),
                "description": "",
                "qty": _to_plain_number(numbers[0]),
                "unit_cost": _to_plain_number(numbers[-2]),
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

    for item in items:
        serials = item.pop("_serials")
        if serials:
            item["description"] = f"{item['description']} (Serial: {', '.join(serials)})".strip()
    return items


def parse_template(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]

    full_text = "\n".join(page_texts)
    fields = _search(HEADER_PATTERNS, page_texts[0])
    fields.update(_search(TOTAL_PATTERNS, full_text))
    return {
        "fields": fields,
        "line_items": _parse_line_items(full_text.splitlines()),
        # Totals are recalculated from the line items when the PDF is generated.
        "hidden_fields": ["total"],
    }
