"""Template parser for NextGen Distribution Pty Ltd purchase orders.

The sample is a landscape, 3-page document: a header (PO number, date,
supplier number), delivery and invoice address blocks, then an items table that
runs across all pages, grouped under section headings ("Expansion Quote",
"Renewal Quote"), and a footer on the last page (partner, payment and shipping
terms, end user, quote, order total).

Each item is a main row plus wrapped continuation lines: the part number wraps
mid-token ("RS-HW-SVC-PE-S" / "3") and the description wraps by words. The
cells of one row can sit a couple of points apart vertically, so rows are
anchored on their Total (Ext) value rather than clustered by `top`, and the
section heading is carried across page breaks.

Beyond the editor's six columns, each item also keeps its structured values
(`section`, `start_date`, `end_date`, `term_qty`, `term_unit`, `billing_term`,
`amount`) so nothing printed is lost. `terms` summarizes the term and the dates
so they are visible in the form.

This loads the template into the editor; `generator_nextgen_distribution_pty_ltd`
regenerates the PDF from it. Each item also carries `amount_basis` (its qty, unit
price and terms as loaded) so the generator can tell whether the printed `amount`
still applies or the row was edited and must be recomputed. Street lines of the
two address blocks are kept on separate lines ("\\n") so they print as they do here.
"""

import re
from pathlib import Path

import pdfplumber

LINE_TOLERANCE = 2.0

# Items table columns (x0 ranges), measured from the sample.
COL_PART_NUMBER = (0, 95)
COL_DESCRIPTION = (95, 305)
COL_START_DATE = (305, 358)
COL_END_DATE = (358, 430)
COL_QTY = (430, 480)
COL_TERM_QTY = (480, 497)
COL_TERM_UNIT = (497, 550)
COL_BILLING = (550, 660)
COL_UNIT_PRICE = (660, 740)
COL_TOTAL_LEFT = 740

# A row's other cells can print up to a couple of points below its Total cell,
# so an item's band starts a little above its Total's own top.
ROW_TOP_SLACK = 4.0
# Items start below the two-line column header.
HEADER_HEIGHT = 20.0

# Header values print centered under their labels, so columns are split at the
# midpoints between the label centers.
HEADER_COLUMNS = {
    "supplier_no": (0, 181),
    "supplier_contact": (181, 343),
    "buyer": (343, 502),
    "po_date": (502, 656),
    "po_number": (656, 900),
}
HEADER_VALUE_OFFSET = (6.0, 22.0)  # below the label row's top

BLOCK_SPLIT_X = 430.0  # delivery address on the left, invoice address on the right

AMOUNT_RE = re.compile(r"^[\d,]+\.\d{2}$")
HEADING_RE = re.compile(r"^\w+ Quote$")
FOOTER_RE = re.compile(
    r"^(Partner:|Payment Terms:|EU:|EU PO#|Shipping Terms:|Rubrik Quote:|Nextgen accepts|Order Total|Page No\.)"
)

FOOTER_PATTERNS = {
    "partner": r"^Partner: (.+)$",
    "payment_terms": r"^Payment Terms: (.+)$",
    "end_user": r"^EU: (.+)$",
    "end_user_po": r"^EU PO# (\S+)",
    "shipping_terms": r"^Shipping Terms: (.+)$",
    "quote_number": r"^Rubrik Quote: (\S+)",
    "quote_date": r"dated (\S+)$",
    "total": r"^Order Total \(GST Exclusive\) (.+)$",
}


def _cluster_lines(words: list[dict]) -> list[list[dict]]:
    """Groups words onto printed lines, tolerating sub-point top offsets."""
    lines: list[list[dict]] = []
    anchor = None
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if anchor is not None and w["top"] - anchor <= LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
            anchor = w["top"]
    return lines


def _line_text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"]))


def _in_column(words: list[dict], column: tuple[float, float]) -> list[dict]:
    return [w for w in words if column[0] <= w["x0"] < column[1]]


def _single_line(words: list[dict], column: tuple[float, float]) -> str:
    return " ".join(w["text"] for w in sorted(_in_column(words, column), key=lambda w: w["x0"]))


def _plain_number(text: str) -> str:
    # The sample prints US-style numbers ("2,380.0000", "5,000").
    return text.replace(",", "").strip()


def _terms_text(term_qty: str, term_unit: str, start_date: str, end_date: str) -> str:
    unit = term_unit.strip()
    term = f"{term_qty} {unit}".strip() if unit and unit.upper() != "N/A" else unit
    if start_date or end_date:
        return f"{term} ({start_date} - {end_date})".strip()
    return term


def _parse_header(page) -> dict[str, str]:
    words = page.extract_words()
    values = {key: "" for key in HEADER_COLUMNS}
    buyer_label = next((w for w in words if w["text"] == "Buyer"), None)
    if buyer_label is None:
        return values
    lo = buyer_label["top"] + HEADER_VALUE_OFFSET[0]
    hi = buyer_label["top"] + HEADER_VALUE_OFFSET[1]
    row = [w for w in words if lo <= w["top"] < hi]
    for key, column in HEADER_COLUMNS.items():
        values[key] = _single_line(row, column)
    return values


def _parse_address_blocks(page) -> dict[str, str]:
    values = {
        "delivery_name": "",
        "delivery_address": "",
        "delivery_locality": "",
        "delivery_contact": "",
        "delivery_email": "",
        "invoice_name": "",
        "invoice_address": "",
        "invoice_email": "",
        "invoice_phone": "",
    }
    words = page.extract_words()
    label = next((w for w in words if w["text"] == "Delivery"), None)
    table_header = next((w for w in words if w["text"] == "Part" and w["x0"] < 40), None)
    if label is None or table_header is None:
        return values
    region = [w for w in words if label["top"] + 8.0 <= w["top"] < table_header["top"] - 4.0]

    rest: list[str] = []
    for line in _cluster_lines([w for w in region if w["x0"] < BLOCK_SPLIT_X]):
        text = _line_text(line)
        if text.startswith("Contact:"):
            values["delivery_contact"] = text[len("Contact:"):].strip()
        elif text.startswith("Email:"):
            values["delivery_email"] = text[len("Email:"):].strip()
        else:
            rest.append(text)
    if rest:
        values["delivery_name"] = rest[0]
    if len(rest) > 1:
        values["delivery_locality"] = rest[-1]
        values["delivery_address"] = "\n".join(rest[1:-1])

    rest = []
    for line in _cluster_lines([w for w in region if w["x0"] >= BLOCK_SPLIT_X]):
        text = _line_text(line)
        if text.startswith("Email:"):
            values["invoice_email"] = text[len("Email:"):].strip()
        elif text.startswith("Phone:"):
            values["invoice_phone"] = text[len("Phone:"):].strip()
        else:
            rest.append(text)
    if rest:
        values["invoice_name"] = rest[0]
        values["invoice_address"] = "\n".join(rest[1:])
    return values


def _parse_items_page(page, section: str) -> tuple[list[dict], str]:
    """Items on one page; `section` is the heading in force when the page
    starts, and the heading in force at its end is returned for the next page."""
    words = page.extract_words()
    header = next((w for w in words if w["text"] == "Part" and w["x0"] < 40), None)
    if header is None:
        return [], section
    top_limit = header["top"] + HEADER_HEIGHT
    bottom_limit = float(page.height)

    headings: list[tuple[float, str]] = []
    skipped: set[int] = set()
    for line in _cluster_lines(words):
        line_top = min(w["top"] for w in line)
        if line_top < top_limit:
            continue
        text = _line_text(line)
        if FOOTER_RE.match(text):
            bottom_limit = min(bottom_limit, line_top - 1.0)
        elif HEADING_RE.match(text) and all(w["x0"] < COL_PART_NUMBER[1] for w in line):
            headings.append((line_top, text))
            skipped.update(id(w) for w in line)

    pool = [w for w in words if top_limit <= w["top"] < bottom_limit and id(w) not in skipped]
    anchors = sorted(
        (w for w in pool if w["x0"] >= COL_TOTAL_LEFT and AMOUNT_RE.match(w["text"])),
        key=lambda w: w["top"],
    )

    items: list[dict] = []
    for index, anchor in enumerate(anchors):
        band_top = top_limit if index == 0 else anchor["top"] - ROW_TOP_SLACK
        band_bottom = anchors[index + 1]["top"] - ROW_TOP_SLACK if index + 1 < len(anchors) else bottom_limit
        row = [w for w in pool if band_top <= w["top"] < band_bottom]

        # The section in force is the latest heading printed above this row.
        for heading_top, heading_text in headings:
            if heading_top < anchor["top"]:
                section = heading_text

        part_words = sorted(_in_column(row, COL_PART_NUMBER), key=lambda w: w["top"])
        # The part number wraps mid-token with no space ("RS-HW-SVC-PE-S" / "3").
        part_number = "".join(w["text"] for w in part_words)
        description = " ".join(_line_text(line) for line in _cluster_lines(_in_column(row, COL_DESCRIPTION)))

        start_date = _single_line(row, COL_START_DATE)
        end_date = _single_line(row, COL_END_DATE)
        term_qty = _single_line(row, COL_TERM_QTY)
        term_unit = _single_line(row, COL_TERM_UNIT)

        qty = _plain_number(_single_line(row, COL_QTY))
        unit_cost = _plain_number(_single_line(row, COL_UNIT_PRICE))
        terms = _terms_text(term_qty, term_unit, start_date, end_date)
        items.append(
            {
                "part_number": part_number,
                "description": description,
                "qty": qty,
                "unit_cost": unit_cost,
                "pct_disc": "",
                "terms": terms,
                "amount_basis": f"{qty}|{unit_cost}|{terms}",
                "section": section,
                "start_date": start_date,
                "end_date": end_date,
                "term_qty": term_qty,
                "term_unit": term_unit,
                "billing_term": _single_line(row, COL_BILLING),
                "amount": _plain_number(anchor["text"]),
            }
        )

    # A heading printed after the last item still governs the next page.
    if headings and (not anchors or headings[-1][0] > anchors[-1]["top"]):
        section = headings[-1][1]
    return items, section


def parse_template(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]
        fields = _parse_header(pdf.pages[0])
        fields.update(_parse_address_blocks(pdf.pages[0]))

        items: list[dict] = []
        section = ""
        for page in pdf.pages:
            page_items, section = _parse_items_page(page, section)
            items.extend(page_items)

    text = "\n".join(page_texts)
    for key, pattern in FOOTER_PATTERNS.items():
        match = re.search(pattern, text, re.MULTILINE)
        fields[key] = match.group(1).strip() if match else ""
    return {"fields": fields, "line_items": items}
