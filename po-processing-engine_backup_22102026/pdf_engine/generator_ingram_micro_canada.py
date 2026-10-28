"""Regenerates Ingram Micro Canada purchase orders.

The template is a fixed-width, dot-matrix style printout (Courier-Bold 7pt on a
character grid, borders drawn as text), so this generator builds the document the
same way the sample is built: as a stream of text rows, drawn on that grid.

  - Each "form page" is a 25-row header (PO# line, INGRAM MICRO banner, vendor /
    ship-to / PST blocks, the P.O. NUMBER row, shipping instructions, the column
    header), a body of item rows, a "*** CONTINUED ON NEXT PAGE ***" row and a
    closing block (the MERCHANDISE SHIPPED notice, AUTHORIZED BY, FROM / TO / BCC /
    SUBJECT). The last form page has no items: it carries the totals row instead.
  - The row stream is cut into 68-row sheets (612x792), so a sheet holds the tail of
    one form page and the head of the next, exactly as the sample's sheets do.
  - The body is dynamic: any number of items, with form pages added as needed. An
    item can run across a form page break, as it does in the sample.

Behaviors worth knowing:
  - Every number is recomputed: an item's extended amount is qty x cost (less any
    "% disc."), the totals row sums the items, and the items are renumbered from 003
    (lines 001 and 002 -- the DIRECT SHIP / RESELLER and HEADER blocks -- keep theirs).
  - The PO number, vendor number, quote number and quote date are written wherever the
    sample repeats them (PO# line on every form page, the P.O. NUMBER row, the SUBJECT
    line, the acceptance sentence).
  - Lines wrap at 30 characters in the description column, like the sample; text that
    would overflow a cell is cut, as it is in the original print.
  - FROM / TO / BCC are passed through sandbox_email.sandbox_text. The template has no
    link annotations, so none are produced.
  - The font is Courier-Bold 7pt like the sample's, so the output matches the original
    glyph for glyph.
"""

import io
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.pdfgen import canvas

import config
from pdf_engine.paginate import _to_decimal
from sandbox_email import sandbox_text

SLUG = "Ingram Micro Canada"

PAGE_W, PAGE_H = 612.0, 792.0
FONT = "Courier-Bold"
FONT_SIZE = 7.0
GRID_X0 = 15.0
GRID_ADVANCE = 4.2
GRID_TOP0 = 24.858
GRID_PITCH = 10.5
ROWS_PER_SHEET = 68
# Courier's baseline sits this far below the top of the character box.
BASELINE_FACTOR = 0.8

RULE = "=" * 132
SEPARATORS = (8, 10, 25, 31, 43, 74, 108, 120)
DESC_WIDTH = 31  # a printed line holds at most 31 characters; longer text is hard-broken here
FIRST_BODY_ROWS = 60  # body rows on the first form page (the sample's page 1)
BODY_ROWS = 64  # body rows on later form pages

QTY_RIGHT_EDGE = 25  # quantity is right-aligned inside its cell (cell spans 11..24)
COST_FIELD_WIDTH = 11
EXT_FIELD_WIDTH = 12


# --- Row building ---------------------------------------------------------------
# The header, the P.O. NUMBER / shipping rows and the closing block are fixed print
# with irregular column positions, so they are kept verbatim from the sample and only
# the editable values are written into them (at the columns the parser reads them from).
HEADER_TEMPLATE = [
    "                                                PO# 30-73066-D",
    "  ****************************************************                                                 PURCHASE ORDER",
    "  * INGRAM MICRO                                     *",
    "  * 55 STANDISH COURT,MISSISSAUGA, ONTARIO L5R 4A1   *                                        PLEASE ACKNOWLEDGE THIS ORDER",
    "  * TEL.(905) 755-5000  FAX (905) 755-1300  *                                        PROMPTLY AND ADVISE SHIPPING DATE.",
    "  ****************************************************                                        BILL OF LADING MUST ACCOMPANY INVOICE.",
    "                                                                                                      IMPORTANT",
    "  VENDOR #  VENDOR                                     S                                      THE PURCHASE ORDER NUMBER MUST",
    "                                                       H                                      APPEAR ON ALL INVOICES, SHIPPING",
    "                                                       I                                      PAPERS AND PACKAGES.  PACKING SLIP",
    "                                                       P                                      MUST ACCOMPANY SHIPMENT.  INVOICE",
    "                                                                                                  EACH PURCHASE ORDER SEPARATELY.",
    "                                                       T",
    "                                                       O                                      PST EXEMPT #",
    "",
    "",
    "=" * 132,
    "  P.O. NUMBER   |VENDOR #  |VEND. TELEPHONE NO.   |P.O. DATE  |SHIP DATE  |DELIVERY DATE  |PAYMENT TERMS      |CURRENCY|",
    "",
    "=" * 132,
    "  SHIPPING INSTRUCTIONS                     |SHIP VIA                                  |FREIGHT TERMS",
    "",
    "=" * 132,
    "  LINE  |S|   QUANTITY   |UNIT | IM SKU    |         MFG PART NO.         |           DESCRIPTION           |   COST    |   EXTENDED",
    "=" * 132,
]
# The header lines above carry the right-hand notice text at column 102 for every row;
# the left/middle values below are written in at these columns.
HEADER_EDGE = 102

# P.O. NUMBER row cells (between the "|" at these columns) and shipping-row cells.
PO_ROW_SEPARATORS = (16, 27, 50, 62, 74, 90, 110, 119)
SHIP_ROW_SEPARATORS = (44, 87)


def _put(row: str, col: int, text: str) -> str:
    """Writes `text` into `row` starting at character column `col` (padding as needed)."""
    if len(row) < col:
        row = row.ljust(col)
    return row[:col] + text + row[col + len(text) :]


def _cell(text: str, width: int) -> str:
    return text[:width].ljust(width)


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _chunks(text: str, width: int) -> list[str]:
    """Hard-breaks the text every `width` characters, mid-word -- the sample's print
    fields do the same ("...SUPPORT PRE" / "PAY")."""
    return [text[i : i + width] for i in range(0, len(text), width)] or [""]


def _wrap(text: str, width: int) -> list[str]:
    """Description lines. The editor holds the description as one string, so the
    original line breaks are rebuilt: break at the last space that fits in `width`
    (the sample's "SUPPORT FOR R6000SE HARDWARE" / "PREPAY PREMIUM SUPPORT"), and
    hard-break mid-word only when a single run of letters is longer than the line
    (the sample's "...SUPPORT PRE" / "PAY")."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return [""]
    lines: list[str] = []
    while len(text) > width:
        cut = text.rfind(" ", 0, width + 1)
        cut = cut if cut > 0 else width
        lines.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    lines.append(text)
    return lines


def _grid_row(line: str, text: str, qty: str = "", unit: str = "", sku: str = "", mfg: str = "",
              cost: str = "", ext: str = "") -> str:
    """One row of the items grid. The separators sit at 8, 10, 25, 31, 43, 74, 108, 120;
    cells: LINE 0..7, S 9, QUANTITY 11..24, UNIT 26..30, IM SKU 32..42, MFG 44..73,
    DESCRIPTION 75..107, COST 109..119, EXTENDED 121..."""
    row = _put("", 2, line) if line else ""
    for sep in SEPARATORS:
        row = _put(row, sep, "|")
    row = _put(row, 11, qty.rjust(7))  # quantity ends at column 17, as in the sample
    row = _put(row, 28, unit) if unit else row
    row = _put(row, 32, sku)
    row = _put(row, 44, mfg[:30])
    row = _put(row, 75, text[:33])
    if cost:
        # The sample centers the cost in its 11-wide cell with the odd space on the right.
        pad = 11 - len(cost)
        row = _put(row, 109, " " * (pad // 2) + cost + " " * (pad - pad // 2))
    if ext:
        row = _put(row, 121, ext.rjust(11))
    return row.rstrip()


def _info_row(text: str, line: str = "") -> str:
    return _grid_row(line, text)


def _header_rows(fields: dict) -> list[str]:
    po = str(fields.get("po_number") or "")
    rows = list(HEADER_TEMPLATE)
    rows[0] = _put(rows[0], 48, f"PO# {po}".ljust(len(rows[0]) - 48))
    rows[8] = _put(rows[8], 3, str(fields.get("vendor_number") or ""))
    rows[9] = _put(rows[9], 9, str(fields.get("vendor_name") or ""))
    rows[10] = _put(rows[10], 9, str(fields.get("vendor_address1") or ""))
    rows[12] = _put(rows[12], 9, str(fields.get("vendor_address2") or ""))
    attn = f"ATTN: {fields.get('vendor_attn') or ''} REF# {fields.get('vendor_ref') or ''}".rstrip()
    rows[13] = _put(rows[13], 2, attn)
    rows[9] = _put(rows[9], 58, str(fields.get("ship_to_name") or "")[:31])
    rows[10] = _put(rows[10], 58, str(fields.get("ship_to_address1") or "")[:31])
    rows[11] = _put(rows[11], 58, str(fields.get("ship_to_address2") or "")[:31])
    rows[12] = _put(rows[12], 58, str(fields.get("ship_to_city") or "")[:21])
    rows[12] = _put(rows[12], 80, str(fields.get("ship_to_state_zip") or ""))
    rows[14] = _put(rows[14], 94, f"ONT:  {fields.get('pst_ont') or ''}".rstrip())
    rows[15] = _put(rows[15], 94, f"BC :  {fields.get('pst_bc') or ''}".rstrip())

    # P.O. NUMBER row: cells between the separators.
    payment = str(fields.get("payment_terms") or "")
    payment = re.sub(r"\s+", "  ", payment, count=1)  # the sample prints "NET  45"
    cells = [
        (2, po, 14), (17, str(fields.get("vendor_code") or ""), 10), (28, str(fields.get("vendor_phone") or ""), 22),
        (51, str(fields.get("po_date") or ""), 11), (63, str(fields.get("ship_date") or ""), 11),
        (75, str(fields.get("delivery_date") or ""), 15), (91, payment.rjust(18), 18),
        (111, str(fields.get("currency") or ""), 8),
    ]
    row = ""
    for col, text, width in cells:
        row = _put(row, col, _cell(text, width))
    for sep in PO_ROW_SEPARATORS:
        row = _put(row, sep, "|")
    rows[18] = row.rstrip()

    row = _put("", 2, str(fields.get("ship_point") or "")[:42])
    row = _put(row, 45, str(fields.get("ship_via") or "")[:42])
    row = _put(row, 88, str(fields.get("freight_terms") or ""))
    for sep in SHIP_ROW_SEPARATORS:
        row = _put(row, sep, "|")
    rows[21] = row.rstrip()
    return [r.rstrip() for r in rows]


def _continued_row() -> str:
    return "        | |*** CONTINUED ON NEXT PAGE ***  |                    |                    *** CONTINUED ON NEXT PAGE ***     |"


def _closing_rows(fields: dict, total_row: str | None = None) -> list[str]:
    rows = [total_row if total_row is not None else "          |              |" + " " * 94 + "|"]
    rows.append("          |              |                    MERCHANDISE SHIPPED ON THIS PURCHASE ORDER NOT IN                         |")
    rows.append("           ==============                     AGREEMENT WITH THE SPECIFICS AS OUTLINED ABOVE WILL BE                     ===========")
    rows.append("                                              RETURNED UNLESS PRIOR APPROVAL HAS BEEN OBTAINED")
    rows.append(" " * 47 + f"AUTHORIZED BY: {fields.get('authorized_by') or ''}".rstrip())
    rows.append("  FROM    : " + sandbox_text(str(fields.get("mail_from") or "")))
    rows.append("  TO      : " + sandbox_text(str(fields.get("mail_to") or "")))
    rows.append("  BCC     : " + sandbox_text(str(fields.get("mail_bcc") or "")))
    rows.append("  SUBJECT : " + str(fields.get("mail_subject") or ""))
    return rows


# --- Items --------------------------------------------------------------------------
def _end_user_rows(fields: dict) -> list[str]:
    """The END USER INFO block printed under every item. Each value is hard-broken at
    DESC_WIDTH characters, mid-word, as the sample's print fields are. (The sample
    breaks its own name as "...CORP" / "ORAT" / "ION" -- a break set by the print
    system's field layout that cannot be derived from one example -- so an unedited
    name prints as "...CORP" / "ORATION" here.)"""
    state = f"ST: {fields.get('end_user_state') or ''}  ZIP: {fields.get('end_user_zip') or ''}      CTRY:"
    country = str(fields.get("end_user_country") or "")
    lines = ["********** END USER INFO ******", "****"]
    name = str(fields.get("end_user_name") or "")
    pieces = str(fields.get("end_user_name_pieces") or "").split("|")
    if pieces and "".join(pieces).strip() == name.strip():
        # The name is unedited: print it in the pieces the template used.
        lines += ["EUSR NAME:" + pieces[0]] + pieces[1:]
    else:
        lines += _chunks("EUSR NAME:" + name, DESC_WIDTH)
    lines += _chunks("EUSR ADD1:" + str(fields.get("end_user_address1") or ""), DESC_WIDTH)
    if fields.get("end_user_address2"):
        lines += _chunks("EUSR ADD2:" + str(fields.get("end_user_address2") or ""), DESC_WIDTH)
    lines += _chunks("EUSR CITY:" + str(fields.get("end_user_city") or ""), DESC_WIDTH)
    lines.append(state)
    if country:
        lines.append(country)
    lines += _chunks("EUSR CONT:" + str(fields.get("end_user_contact") or ""), DESC_WIDTH)
    lines += _chunks("EUSR PHON:" + str(fields.get("end_user_phone") or ""), DESC_WIDTH)
    lines += _chunks("EUSR EMAL:" + str(fields.get("end_user_email") or ""), DESC_WIDTH)
    lines.append("")
    return [_info_row(line) for line in lines]


def _special_rows(fields: dict) -> list[str]:
    """Lines 001 (DIRECT SHIP / RESELLER INFO) and 002 (HEADER) -- not priced items."""
    rows = [
        _info_row("********* DIRECT SHIP INFO ****", "001"),
        _info_row("****", "001"),
        _info_row("********** RESELLER INFO ******"),
        _info_row("****"),
        _info_row(f"RSLR CONT:{fields.get('reseller_contact') or ''}"[:DESC_WIDTH + 2]),
        _info_row(f"RSLR PHON:{fields.get('reseller_phone') or ''}"[:DESC_WIDTH + 2]),
        _info_row("********** END USER INFO ******"),
        _info_row("****"),
        _info_row(""),
        _info_row("HEADER", "002"),
        _info_row(f"QUOTE # {fields.get('quote_number') or ''}"),
        _info_row(f"EU PO# {fields.get('end_user_po') or ''}"),
        _info_row("***SHIP-TO CONTACT INFO***"),
        _info_row(f"NAME: {fields.get('ship_to_contact_name') or ''}"),
        _info_row(f"PHONE: {fields.get('ship_to_contact_phone') or ''}"),
        _info_row(f"EMAIL: {fields.get('ship_to_contact_email') or ''}"),
        _info_row(f"SHIPPING TERMS: {fields.get('shipping_terms') or ''}"),
        _info_row("INGRAM MICRO ACCEPTS ALL"),
        _info_row(" ADDITIONAL TERMS ON RUBRIK QUO"),
        _info_row("TE #"),
        _info_row(f" {fields.get('quote_number') or ''} DATED {fields.get('quote_date') or ''}"),
        _info_row(""),
    ]
    return rows


class _Item:
    def __init__(self, raw: dict, number: int) -> None:
        self.raw = raw
        self.line = f"{number:03d}"
        self.qty = _to_decimal(raw.get("qty"))
        self.cost = _to_decimal(raw.get("unit_cost"))
        pct = _to_decimal(raw.get("pct_disc"))
        self.net_cost = self.cost * (Decimal("1") - pct / Decimal("100"))
        self.extended = (self.qty * self.net_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _item_rows(item: _Item, fields: dict) -> list[str]:
    raw = item.raw
    desc_lines = _wrap(str(raw.get("description") or ""), DESC_WIDTH)
    qty_text = f"{int(item.qty)}" if item.qty == item.qty.to_integral_value() else f"{item.qty.normalize():f}"
    rows = [
        _grid_row(
            item.line, desc_lines[0], qty=qty_text, unit=str(raw.get("unit") or "EA"), sku=str(raw.get("im_sku") or ""),
            mfg=str(raw.get("part_number") or ""), cost=_money(item.net_cost), ext=_money(item.extended),
        )
    ]
    rows += [_info_row(line) for line in desc_lines[1:]]

    eu_number = str(raw.get("eu_number") or fields.get("eu_number") or "")
    eu_name = str(raw.get("eu_name") or fields.get("eu_name") or "")
    eu_text = f"EU#- {eu_number} {eu_name}".rstrip()
    first = eu_text[:DESC_WIDTH]
    rows.append(_info_row(first))
    rest = eu_text[DESC_WIDTH:]
    while rest:
        rows.append(_info_row(rest[:DESC_WIDTH]))
        rest = rest[DESC_WIDTH:]
    rows.append(_info_row("MC#C"))
    terms = re.sub(r"\s+", " ", str(raw.get("terms") or "").strip())
    match = re.match(r"^(\d+) MONTHS? (.*)$", terms, re.IGNORECASE)
    rows.append(_info_row(f"{match.group(1)} MONTHS  {match.group(2)}" if match else terms))
    serial = str(raw.get("serial_number") or "").strip()
    if serial:
        serial_line = f" {serial}"
        for i in range(0, len(serial_line), DESC_WIDTH):
            rows.append(_info_row(serial_line[i : i + DESC_WIDTH]))
    rows += _end_user_rows(fields)
    return rows


def _paginate(body: list[str]) -> list[list[str]]:
    """Splits the body rows into form pages (60 rows on the first, 64 after); every
    form page after the last full one is the item-less page that carries the totals."""
    pages: list[list[str]] = []
    start, size = 0, FIRST_BODY_ROWS
    while start < len(body):
        pages.append(body[start : start + size])
        start += size
        size = BODY_ROWS
    return pages or [[]]


def _build_stream(fields: dict, items: list[_Item], line_items: list[dict]) -> list[str]:
    body = _special_rows(fields)
    for item in items:
        body += _item_rows(item, fields)

    total_qty = sum((i.qty for i in items), Decimal("0"))
    total_ext = sum((i.extended for i in items), Decimal("0"))
    qty_text = f"{int(total_qty)}" if total_qty == total_qty.to_integral_value() else f"{total_qty.normalize():f}"
    total_row = "          |" + qty_text.rjust(8) + " " * 6 + "|" + " " * 94 + "| " + _money(total_ext)

    stream: list[str] = []
    for page_body in _paginate(body):
        stream += _header_rows(fields)
        stream += page_body
        stream.append(_continued_row())
        stream.append(RULE)
        stream += _closing_rows(fields)
    # The last form page: header, the "VENDORS PLEASE NOTE" row, the totals row and the closing block.
    stream += _header_rows(fields)
    stream.append("  VENDORS PLEASE NOTE ANY CHANGES IN PRICE OR TERMS NEED APPROVAL BEFORE SHIPMENT" + " " * 27 + "|           |")
    stream.append(RULE)
    stream += _closing_rows(fields, total_row)[:5]
    # The sample's last form page ends after the AUTHORIZED BY line.
    del line_items
    return stream


# --- Drawing ---------------------------------------------------------------------------
def _draw_sheet(c: canvas.Canvas, rows: list[str]) -> None:
    c.setFont(FONT, FONT_SIZE)
    for index, row in enumerate(rows):
        if not row.strip():
            continue
        top = GRID_TOP0 + GRID_PITCH * index
        baseline = PAGE_H - top - FONT_SIZE * BASELINE_FACTOR
        # Draw character by character on the grid so columns stay aligned.
        for col, ch in enumerate(row):
            if ch != " ":
                c.drawString(GRID_X0 + GRID_ADVANCE * col, baseline, ch)
    c.showPage()


def generate_ingram_micro_canada_po(fields: dict, line_items: list[dict]) -> bytes:
    fields = dict(fields)
    live = [i for i in line_items if i and (i.get("part_number") or i.get("description"))]
    items = [_Item(raw, number) for number, raw in enumerate(live, start=3)]
    stream = _build_stream(fields, items, live)

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(PAGE_W, PAGE_H))
    for start in range(0, len(stream), ROWS_PER_SHEET):
        _draw_sheet(c, stream[start : start + ROWS_PER_SHEET])
    c.save()
    pdf_output = buffer.getvalue()

    po_number = (fields.get("po_number") or "PO").strip().replace("/", "-").replace(" ", "_") or "PO"
    out_dir = Path(config.GENERATED_DIR) / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{po_number}.pdf").write_bytes(pdf_output)
    return pdf_output
