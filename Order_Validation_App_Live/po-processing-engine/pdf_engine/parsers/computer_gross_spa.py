"""Template parser for Computer Gross spa purchase orders.

The sample is a single landscape page: a header block (PO number, date,
payment terms, bill-to), a four-column details block (Distributor, Reseller,
End User, Ship To), the items table, the total, and the shipping / importer-of-
record (IOR) lines. Everything is split by x-position and label row rather than
by fixed boxes, so a differently sized PO still reads correctly.

This only loads the template into the editor. There is no generator for
Computer Gross spa yet, so generate/preview are rejected until one is added.
"""

import re
from pathlib import Path

import pdfplumber

LINE_TOLERANCE = 2.0

# Details block: label rows and the four value columns (x0 ranges).
DETAIL_COLUMNS = {
    "distributor": (118, 262),
    "reseller": (262, 366),
    "end_user": (366, 458),
    "ship_to": (458, 620),
}
DETAIL_ROWS = {
    "Company Name:": "company",
    "Address:": "address",
    "City:": "city",
    "Postal Code:": "postal_code",
    "Contact Person:": "contact",
    "Tel:": "phone",
    "E-mail:": "email",
}
DETAILS_TOP = (183.0, 235.0)
END_USER_PO_TOP = (256.0, 264.0)
END_USER_PO_LEFT = 118.0
VAT_TOP = (458.0, 466.0)

# Items table columns (x0 ranges), measured from the sample.
COL_PART_NUMBER = (28, 120)
COL_DESCRIPTION = (120, 290)
COL_QTY = (290, 340)
COL_TERM = (340, 365)
COL_PRICE = (490, 560)
COL_TOTAL = (560, 700)
ITEMS_TOP = (284.0, 366.0)

IOR_ROWS = {
    "IOR Name": "ior_name",
    "IOR Street Address": "ior_street",
    "IOR City": "ior_city",
    "IOR State": "ior_state",
    "IOR Zip": "ior_zip",
    "IOR Country": "ior_country",
    "IOR Contact (Name,Phone,Email)": "ior_contact",
}

HEADER_PATTERNS = {
    "po_number": r"Ordine di acquisto nr\.: (\S+)",
    "po_date": r"Date: (\S+)",
    "payment_terms": r"Pagamento: (.+)",
    "quote_number": r"Quote ID: (\S+)|^(Q-\d+)$",
    "total": r"TOTAL (\S+)",
    "quote_date": r"DATED (\S+)",
}


def _cluster_lines(words: list[dict]) -> list[list[dict]]:
    """Groups words onto printed lines, tolerating the 4pt/5pt font offset."""
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


def _plain_number(text: str) -> str:
    # Prices print EU-style ("$13.520,00", "1294,8", "1,23"): "." groups
    # thousands and "," is the decimal mark.
    text = text.replace("$", "").strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return text


def _parse_header(page) -> dict[str, str]:
    values = {key: "" for key in HEADER_PATTERNS}
    lines = [
        " ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"]))
        for line in _cluster_lines(page.extract_words())
    ]
    for line in lines:
        for key, pattern in HEADER_PATTERNS.items():
            if values[key]:
                continue
            match = re.search(pattern, line)
            if match:
                values[key] = next(g for g in match.groups() if g).strip()
    # "Quote ID:" prints its value far to the right on the same line, so the
    # first pattern normally matches; the bare Q-number is only a fallback.
    # The end-user PO value prints in larger text, about a point above its
    # label's baseline, so it never lands on the label's line.
    values["end_user_po"] = " ".join(
        w["text"]
        for w in sorted(page.extract_words(), key=lambda w: w["x0"])
        if END_USER_PO_TOP[0] <= w["top"] < END_USER_PO_TOP[1] and w["x0"] >= END_USER_PO_LEFT
    )
    return values


def _parse_billing(page) -> dict[str, str]:
    """Bill-to line and invoice / license emails, left of the NOTE block."""
    words = [w for w in page.extract_words() if 120 <= w["x0"] < 440 and 120 <= w["top"] < 152]
    lines = _cluster_lines(words)
    texts = [" ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"])) for line in lines]
    return {
        "bill_to": texts[0] if texts else "",
        "license_email": texts[1] if len(texts) > 1 else "",
        # The invoice emails wrap onto a second line ("... +" / "...").
        "invoice_email": " ".join(texts[2:]),
    }


def _parse_details(page) -> dict[str, str]:
    words = [w for w in page.extract_words() if DETAILS_TOP[0] <= w["top"] < DETAILS_TOP[1]]
    values: dict[str, str] = {}
    for line in _cluster_lines(words):
        label = _text(line, (0, 118))
        key = DETAIL_ROWS.get(label)
        if not key:
            continue
        for column, x_range in DETAIL_COLUMNS.items():
            values[f"{column}_{key}"] = _text(line, x_range)
    return values


def _parse_items(page) -> list[dict]:
    words = [w for w in page.extract_words() if ITEMS_TOP[0] <= w["top"] < ITEMS_TOP[1]]
    items: list[dict] = []
    for line in _cluster_lines(words):
        part_number = _text(line, COL_PART_NUMBER)
        # The table is followed by blank rows that print only "$0,00"; a real
        # row always has a part number.
        if not part_number:
            continue
        items.append(
            {
                "part_number": part_number,
                "description": _text(line, COL_DESCRIPTION),
                "qty": _plain_number(_text(line, COL_QTY)),
                "unit_cost": _plain_number(_text(line, COL_PRICE)),
                "pct_disc": "",
                "terms": _text(line, COL_TERM),
            }
        )
    return items


def _parse_shipping(page) -> dict[str, str]:
    words = [w for w in page.extract_words() if 380.0 <= w["top"] < 475.0]
    values: dict[str, str] = {}
    for line in _cluster_lines(words):
        label = _text(line, (0, 118))
        value = _text(line, (118, 700))
        if label.startswith("Shipping"):
            # The shipping method is printed in larger text, further right.
            values["shipping_method"] = _text(line, (200, 700))
        elif label in IOR_ROWS:
            values[IOR_ROWS[label]] = value
    # The VAT number prints on the "Excluding APAC & Non-EU" label row, run
    # together with it with no space ("Non-EU04801490485"), so pdfplumber
    # returns one word that starts inside the label column. Take the trailing
    # run of digits from that row instead of filtering by x-position.
    vat_row = " ".join(
        w["text"]
        for w in sorted(page.extract_words(), key=lambda w: w["x0"])
        if VAT_TOP[0] <= w["top"] < VAT_TOP[1]
    )
    vat_match = re.search(r"\d{8,}$", vat_row)
    values["vat_number"] = vat_match.group(0) if vat_match else ""
    return values


def parse_template(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        fields = _parse_header(page)
        fields.update(_parse_billing(page))
        fields.update(_parse_details(page))
        fields.update(_parse_shipping(page))
        items = _parse_items(page)
    return {"fields": fields, "line_items": items}
