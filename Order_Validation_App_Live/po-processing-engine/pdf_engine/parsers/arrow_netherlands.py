"""Template parser for Arrow ECS BV (Netherlands) purchase orders.

The sample is a landscape, 16-page document: 15 pages of line items (the last
one also carries the totals and payment/delivery terms) followed by a
"Complementary Order Information" page. Each item prints as a main row plus
one or two wrapped continuation lines, so rows are split into columns by
x-position and continuation lines are folded back into their item.

A subscription line prints its term at the end of its description ("Premium
support : 36 months"); that number is also returned as the item's `terms`, so
it can be compared with a JSON subscription term. The description keeps the
text as printed.
"""

import re
from pathlib import Path

import pdfplumber

from pdf_engine.extractor import open_pdf

# Column boundaries (x0 ranges) measured from the sample's items table.
COL_LINE_NO = (0, 55)
COL_ARROW_ITEM = (55, 146)
COL_VENDOR_ITEM = (146, 271)
COL_DESCRIPTION = (271, 470)
COL_QTY = (470, 530)
COL_RRP = (530, 612)
COL_DISCOUNT = (612, 700)
# Unit price text ends near x=747 and Total price is right-aligned to x=826, so a wide
# total ("10,588,320.00$") starts as far left as x=768. Cut between them at 757.
COL_UNIT_PRICE = (700, 757)
COL_TOTAL = (757, 900)

HEADER_ROW_TOP = 70.0  # items start below the repeated column-header row
FOOTER_TOP = 460.0  # the Arrow ECS address footer begins below this
LINE_TOLERANCE = 2.0
MAIN_ROW_RE = re.compile(r"^\d+$")
TOTALS_START_RE = re.compile(r"^(Total (excl|incl)\.|VAT\b|Terms of payment|Delivery terms)")
# A subscription line ends its description with its term, e.g. "... : 36 months".
TERM_IN_DESCRIPTION_RE = re.compile(r":\s*(\d+)\s*months?\s*$", re.IGNORECASE)

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


def _term_from_description(description: str) -> str:
    """The term in months that a subscription line prints at the end of its
    description, e.g. "Premium support : 36 months" -> "36". Lines without one
    (hardware, cables) have no term and return ""."""
    match = TERM_IN_DESCRIPTION_RE.search(description)
    return match.group(1) if match else ""


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
    # The description is complete only once its continuation lines are folded in,
    # so the term is read after the whole page has been walked.
    for item in items:
        item["terms"] = _term_from_description(item["description"])
    return items


# First-page Ship To / Billing panels (x ranges) and the band their address lines sit in.
SHIP_TO_X = (219.6, 413.0)
BILLING_X = (418.0, 612.0)
ADDRESS_TOP = (90.0, 172.0)
# The Ship To panel's contact rows sit below its address; values start right of the label.
SHIP_TO_CONTACT_TOP = (170.0, 225.0)
SHIP_TO_VALUE_X = 257.0
SHIP_TO_CONTACT_KEYS = {
    "Contact:": "ship_to_contact",
    "Phone:": "ship_to_phone",
    "E-mail:": "ship_to_email",
}
# Complementary page's Special Information panel (x0 range, and below its title).
SPECIAL_X = (366.0, 820.0)
SPECIAL_TOP = (80.0, 327.0)


def _block_lines(words: list[dict]) -> list[str]:
    return [" ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"])) for line in _cluster_lines(words)]


def _parse_header_blocks(page) -> dict[str, str]:
    """Ship To / Billing addresses and the Ship To contact rows on the first page."""
    words = page.extract_words()
    values: dict[str, str] = {}
    for key, (x0, x1) in (("ship_to_block", SHIP_TO_X), ("bill_to_block", BILLING_X)):
        in_block = [w for w in words if x0 <= w["x0"] < x1 and ADDRESS_TOP[0] < w["top"] < ADDRESS_TOP[1]]
        values[key] = "\n".join(_block_lines(in_block))
    contact_words = [
        w
        for w in words
        if SHIP_TO_X[0] <= w["x0"] < SHIP_TO_X[1] and SHIP_TO_CONTACT_TOP[0] <= w["top"] < SHIP_TO_CONTACT_TOP[1]
    ]
    for key in SHIP_TO_CONTACT_KEYS.values():
        values[key] = ""
    for line in _cluster_lines(contact_words):
        ordered = sorted(line, key=lambda w: w["x0"])
        label = " ".join(w["text"] for w in ordered if w["x0"] < SHIP_TO_VALUE_X)
        value = " ".join(w["text"] for w in ordered if w["x0"] >= SHIP_TO_VALUE_X)
        key = SHIP_TO_CONTACT_KEYS.get(label)
        if key:
            values[key] = value
    return values


def _parse_complementary_page(page) -> dict[str, str]:
    """Reseller / end-user / special-information blocks on the final page.

    Labels sit at x<100 and values start at x=105, so each value is the text
    to the right of its label on the same printed line. A Street value that wraps
    prints its continuation on an unlabelled line, which is folded back in.
    """
    words = page.extract_words()
    left_words = [w for w in words if w["x0"] < 360]
    values: dict[str, str] = {}
    section = "reseller"
    street_key = None
    for line in _cluster_lines(left_words):
        label = " ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"]) if w["x0"] < 100)
        value = " ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"]) if w["x0"] >= 100)
        if label.startswith("End User Information"):
            section = "end_user"
            street_key = None
            continue
        key = {
            "Company:": "company",
            "Street:": "street",
            "ZipCode, City:": "zip_city",
            "Country:": "country",
            "Contact name:": "contact",
            "Contact:": "contact",
            "Email:": "email",
            "Phone:": "phone",
            "Order Reference:": "order_reference",
        }.get(label)
        if key:
            values[f"{section}_{key}"] = value
            street_key = f"{section}_street" if key == "street" else None
        elif not label and value and street_key:
            values[street_key] += f"\n{value}"

    special_words = [
        w
        for w in words
        if SPECIAL_X[0] <= w["x0"] < SPECIAL_X[1] and SPECIAL_TOP[0] < w["top"] < SPECIAL_TOP[1]
    ]
    values["special_information"] = "\n".join(_block_lines(special_words))
    return values


def parse_template(path: Path) -> dict:
    with open_pdf(path) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]
        items: list[dict] = []
        # Every page except the trailing "Complementary Order Information" one
        # is an items page.
        for page in pdf.pages[:-1]:
            items.extend(_parse_items_page(page))
        header_blocks = _parse_header_blocks(pdf.pages[0])
        complementary = _parse_complementary_page(pdf.pages[-1])

    fields = _search(HEADER_PATTERNS, page_texts[0])
    fields.update(header_blocks)
    fields.update(_search(TOTAL_PATTERNS, "\n".join(page_texts)))
    fields.update(complementary)
    return {"fields": fields, "line_items": items}
