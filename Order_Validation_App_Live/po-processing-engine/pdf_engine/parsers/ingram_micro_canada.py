"""Template parser for Ingram Micro Canada purchase orders.

The sample is a fixed-width, dot-matrix style printout: every glyph is Courier-Bold
7pt on a character grid (4.2pt per column, 10.5pt per row), with the form's borders
drawn as text ("|", "====", "****"). It is not a set of pages in the usual sense but a
continuous stream of text rows cut into 68-row sheets, so one sheet holds the tail of
one "form page" and the head of the next. This parser rebuilds that stream of rows,
splits it back into form pages, and reads:

  - the form header (PO number, vendor, ship-to, the P.O. NUMBER / VENDOR # / DATE /
    PAYMENT TERMS / CURRENCY row, shipping instructions),
  - line 001 (DIRECT SHIP / RESELLER INFO) and line 002 (HEADER: quote, EU PO, ship-to
    contact, shipping terms, acceptance sentence), which are printed in the items grid
    but are not priced items,
  - the priced items (line 003 onward): a main row (quantity, unit, IM SKU, MFG PART NO.,
    cost, extended) plus wrapped description lines, an "EU#-" line, "MC#C", a term line
    and an optional serial-number line, followed by an END USER INFO block,
  - the closing block (authorized-by, FROM / TO / BCC / SUBJECT) and the printed totals.

The END USER INFO block is identical under every item, so it is loaded once as header
fields and redrawn under each item by the generator.

Each item exposes the editor's six columns (part_number, description, qty, unit_cost,
pct_disc, terms) and keeps its other printed values (line number, unit, IM SKU,
serial number, EU number) so nothing printed is lost.
"""

import re
from pathlib import Path

import pdfplumber

# --- The sample's character grid --------------------------------------------------
GRID_X0 = 15.0
GRID_ADVANCE = 4.2
GRID_TOP0 = 24.858
GRID_PITCH = 10.5

# Column separators of the items grid ("LINE |S| QUANTITY |UNIT | IM SKU | ..."), as
# character indexes; fields are the text between them.
SEPARATORS = (8, 10, 25, 31, 43, 74, 108, 120)
F_LINE, F_S, F_QTY, F_UNIT, F_SKU, F_MFG, F_DESC, F_COST, F_EXT = range(9)

DESC_WIDTH = 32  # characters between the DESCRIPTION separators
DESC_TEXT_WIDTH = 30  # a wrapped description / info line holds at most this many characters

_LINE_NO_RE = re.compile(r"^  (\d{3}) ")


# Separators ("|") of the P.O. NUMBER row and of the SHIPPING INSTRUCTIONS row.
PO_ROW_SEPARATORS = (16, 27, 50, 62, 74, 90, 110, 119)
SHIP_ROW_SEPARATORS = (44, 87)


def _cells(row: str, separators: tuple[int, ...]) -> list[str]:
    """The text of each cell between the separators (and before the first / after the last)."""
    edges = [-1, *separators, len(row)]
    return [row[a + 1 : b] if a + 1 < len(row) else "" for a, b in zip(edges, edges[1:])]


def _field(row: str, index: int) -> str:
    start = 0 if index == 0 else SEPARATORS[index - 1] + 1
    end = SEPARATORS[index] if index < len(SEPARATORS) else len(row)
    return row[start:end]


def read_rows(path: Path) -> list[str]:
    """The whole document as one stream of text rows (physical sheets concatenated)."""
    rows: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            lines: dict[int, dict[int, str]] = {}
            for char in page.chars:
                r = round((char["top"] - GRID_TOP0) / GRID_PITCH)
                c = round((char["x0"] - GRID_X0) / GRID_ADVANCE)
                lines.setdefault(r, {})[c] = char["text"]
            if not lines:
                continue
            for r in range(max(lines) + 1):
                cells = lines.get(r, {})
                rows.append("".join(cells.get(i, " ") for i in range(max(cells) + 1)).rstrip() if cells else "")
    return rows


def _is_form_start(row: str) -> bool:
    return row.strip().startswith("PO# ") and len(row) - len(row.lstrip()) > 40


def _is_column_header(row: str) -> bool:
    return row.strip().startswith("LINE  |S|")


def _form_pages(rows: list[str]) -> list[list[str]]:
    starts = [i for i, row in enumerate(rows) if _is_form_start(row)]
    return [rows[s : (starts[k + 1] if k + 1 < len(starts) else len(rows))] for k, s in enumerate(starts)]


def _after(row: str, label: str) -> str:
    return row.split(label, 1)[1].strip() if label in row else ""


def _slice(row: str, start: int, end: int | None = None) -> str:
    return row[start:end].strip() if len(row) > start else ""


def _parse_form_header(page: list[str]) -> dict[str, str]:
    """Header values from the first form page's first 25 rows."""
    values: dict[str, str] = {}
    head = page[:25]
    values["po_number"] = _after(head[0], "PO#")

    # Vendor block (left) and ship-to block (middle).
    values["vendor_number"] = _slice(head[8], 0, 20)
    values["vendor_name"] = _slice(head[9], 0, 53)
    values["vendor_address1"] = _slice(head[10], 0, 53)
    values["vendor_address2"] = _slice(head[12], 0, 53)
    attn = _slice(head[13], 0, 53)
    match = re.match(r"ATTN:\s*(.*?)\s+REF#\s*(.*)$", attn)
    values["vendor_attn"] = match.group(1) if match else attn
    values["vendor_ref"] = match.group(2) if match else ""
    # The ship-to block's lines start at column 56 (row 11's "NEVINE COMPANION" is the
    # second address line, printed one row above the city line).
    values["ship_to_name"] = _slice(head[9], 56, 87)
    values["ship_to_address1"] = _slice(head[10], 56, 87)
    values["ship_to_address2"] = _slice(head[11], 56, 87)
    city_row = head[12]
    values["ship_to_city"] = _slice(city_row, 56, 79)
    values["ship_to_state_zip"] = _slice(city_row, 79, 95)

    # PST exempt numbers (right block).
    values["pst_ont"] = _after(head[14], "ONT:")
    values["pst_bc"] = _after(head[15], "BC :")

    # P.O. NUMBER row: cells between the "|" separators at PO_ROW_SEPARATORS.
    # The row ends with a closing "|", so _cells yields one empty trailing cell: drop it.
    cells = _cells(head[18], PO_ROW_SEPARATORS)[:8]
    (values["po_number_row"], values["vendor_code"], values["vendor_phone"], values["po_date"],
     values["ship_date"], values["delivery_date"], payment, values["currency"]) = [c.strip() for c in cells]
    values["payment_terms"] = re.sub(r"\s+", " ", payment)

    # Shipping instructions: cells between the separators at SHIP_ROW_SEPARATORS.
    values["ship_point"], values["ship_via"], values["freight_terms"] = [
        c.strip() for c in _cells(head[21], SHIP_ROW_SEPARATORS)
    ]
    return values


def _info_lines(block: list[str]) -> list[str]:
    return [_field(row, F_DESC).rstrip() for row in block]


def _value_after(lines: list[str], prefix: str) -> str:
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def _parse_special_lines(blocks: list[list[str]]) -> dict[str, str]:
    """Values from line 001 (DIRECT SHIP / RESELLER INFO) and line 002 (HEADER)."""
    values: dict[str, str] = {}
    reseller = _info_lines([r for b in blocks if b[0][2:5] == "001" for r in b])
    values["reseller_contact"] = _value_after(reseller, "RSLR CONT:")
    values["reseller_phone"] = _value_after(reseller, "RSLR PHON:")

    header_block = next((b for b in blocks if b[0][2:5] == "002"), [])
    lines = _info_lines(header_block)
    values["quote_number"] = _value_after(lines, "QUOTE #")
    values["end_user_po"] = _value_after(lines, "EU PO#")
    values["ship_to_contact_name"] = _value_after(lines, "NAME:")
    values["ship_to_contact_phone"] = _value_after(lines, "PHONE:")
    values["ship_to_contact_email"] = _value_after(lines, "EMAIL:")
    values["shipping_terms"] = _value_after(lines, "SHIPPING TERMS:")
    sentence = " ".join(line.strip() for line in lines[lines.index("INGRAM MICRO ACCEPTS ALL") :]) if (
        "INGRAM MICRO ACCEPTS ALL" in lines
    ) else ""
    match = re.search(r"(Q-\d+)\s+DATED\s+(\S+)", sentence)
    values["quote_date"] = match.group(2) if match else ""
    return values


def _parse_end_user(lines: list[str]) -> dict[str, str]:
    """The END USER INFO block that follows every item. Lines wrap at 30 characters,
    so a value can continue on the next line (the sample splits NAME across 3 lines)."""
    # Re-join wrapped continuation lines: a line that doesn't start with a known prefix
    # continues the previous value.
    prefixes = ("EUSR NAME:", "EUSR ADD1:", "EUSR ADD2:", "EUSR CITY:", "ST:", "EUSR CONT:", "EUSR PHON:", "EUSR EMAL:")
    entries: list[list[str]] = []
    for line in lines:
        if any(line.startswith(p) for p in prefixes):
            entries.append([line])
        elif entries and line:
            entries[-1].append(line)
    joined = {}
    for entry in entries:
        for prefix in prefixes:
            if entry[0].startswith(prefix):
                text = entry[0][len(prefix) :]
                for cont in entry[1:]:
                    text += cont
                joined[prefix] = text
    # Keep the name's printed pieces ("...CORP" / "ORAT" / "ION"): the print system breaks
    # it in fixed-length pieces that can't be derived, so the generator re-uses them while
    # the name is unedited ("end_user_name_pieces" is the name's lines joined by "|").
    name_pieces = next((e for e in entries if e[0].startswith("EUSR NAME:")), [""])
    values = {
        "end_user_name_pieces": "|".join([name_pieces[0][len("EUSR NAME:") :]] + name_pieces[1:]),
        "end_user_name": joined.get("EUSR NAME:", "").strip(),
        "end_user_address1": joined.get("EUSR ADD1:", "").strip(),
        "end_user_address2": joined.get("EUSR ADD2:", "").strip(),
        "end_user_city": joined.get("EUSR CITY:", "").strip(),
        "end_user_contact": joined.get("EUSR CONT:", "").strip(),
        "end_user_phone": joined.get("EUSR PHON:", "").strip(),
        "end_user_email": joined.get("EUSR EMAL:", "").strip(),
    }
    state_line = joined.get("ST:", "")
    match = re.match(r"\s*(\S*)\s+ZIP:\s*(\S*)\s+CTRY:\s*(\S*)", state_line)
    values["end_user_state"] = match.group(1) if match else ""
    values["end_user_zip"] = match.group(2) if match else ""
    values["end_user_country"] = match.group(3) if match else ""
    return values


def _parse_items(blocks: list[list[str]]) -> tuple[list[dict], dict[str, str]]:
    items: list[dict] = []
    end_user: dict[str, str] = {}
    for block in blocks:
        main = block[0]
        if not _field(main, F_COST).strip():  # lines 001 / 002 carry no price
            continue
        lines = _info_lines(block)
        end = next((i for i, line in enumerate(lines) if "END USER INFO" in line), len(lines))
        head = lines[:end]
        if not end_user and end < len(lines):
            end_user = _parse_end_user(lines[end:])

        eu_at = next((i for i, line in enumerate(head) if line.startswith("EU#-")), len(head))
        mc_at = next((i for i, line in enumerate(head) if line.startswith("MC#C")), len(head))
        description = " ".join(line.strip() for line in head[:eu_at])
        eu_text = "".join(head[eu_at:mc_at])
        eu_match = re.match(r"EU#-\s*(\S+)\s*(.*)$", eu_text.strip())
        tail = head[mc_at + 1 :]
        terms = tail[0].strip() if tail else ""
        serial = "".join(line for line in tail[1:]).strip()
        items.append(
            {
                "part_number": _field(main, F_MFG).strip(),
                "description": re.sub(r"\s+", " ", description).strip(),
                "qty": _field(main, F_QTY).strip(),
                "unit_cost": _field(main, F_COST).strip(),
                "pct_disc": "",
                "terms": re.sub(r"\s+", " ", terms),
                "line_no": _field(main, F_LINE).strip(),
                "unit": _field(main, F_UNIT).strip(),
                "im_sku": _field(main, F_SKU).strip(),
                "eu_number": eu_match.group(1) if eu_match else "",
                "eu_name": eu_match.group(2).strip() if eu_match else "",
                "serial_number": serial,
                "amount": _field(main, F_EXT).strip(),
            }
        )
    return items, end_user


def _parse_closing(page: list[str]) -> dict[str, str]:
    values = {"authorized_by": "", "mail_from": "", "mail_to": "", "mail_bcc": "", "mail_subject": ""}
    for row in page:
        text = row.strip()
        if text.startswith("AUTHORIZED BY:"):
            values["authorized_by"] = text[len("AUTHORIZED BY:") :].strip()
        elif text.startswith("FROM"):
            values["mail_from"] = text.split(":", 1)[1].strip()
        elif text.startswith("TO ") or text.startswith("TO:"):
            values["mail_to"] = text.split(":", 1)[1].strip()
        elif text.startswith("BCC"):
            values["mail_bcc"] = text.split(":", 1)[1].strip()
        elif text.startswith("SUBJECT"):
            values["mail_subject"] = text.split(":", 1)[1].strip()
    return values


def _item_blocks(pages: list[list[str]]) -> list[list[str]]:
    """The items grid rows of every form page, joined, then split at each line number."""
    body: list[str] = []
    for page in pages:
        header_at = next((i for i, row in enumerate(page) if _is_column_header(row)), None)
        if header_at is None:
            continue
        for row in page[header_at + 2 :]:
            if "CONTINUED ON NEXT PAGE" in row or row.startswith("=="):
                break
            if row.strip().startswith("VENDORS PLEASE NOTE"):
                break
            body.append(row)
    blocks: list[list[str]] = []
    for row in body:
        if _LINE_NO_RE.match(row):
            blocks.append([row])
        elif blocks:
            blocks[-1].append(row)
    return blocks


def parse_template(path: Path) -> dict:
    rows = read_rows(path)
    pages = _form_pages(rows)
    fields = _parse_form_header(pages[0])
    blocks = _item_blocks(pages)
    fields.update(_parse_special_lines(blocks))
    items, end_user = _parse_items(blocks)
    fields.update(end_user)
    fields.update(_parse_closing(pages[0]))
    return {"fields": fields, "line_items": items}
