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
  - Column order (`column_order`, the form's arrangement of the Line items table): the
    132-character grid is re-laid with the columns in the requested order, each keeping its
    own character width, so the table is still 132 wide. The header line, every item /
    info row, the "continued" row, the totals box under the Quantity and Extended cells,
    the cost box on the last page's "VENDORS PLEASE NOTE" row and the MERCHANDISE notice
    all follow the layout. LINE+S and QUANTITY+UNIT move as one (the form has no column
    for S or UNIT), IM SKU travels just before MFG PART NO.; the form's % disc. and Terms
    have no column here and are ignored. The form's untouched default order, like no
    order at all, keeps the sample's own layout, byte for byte.
"""

import io
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.pdfgen import canvas

import config
from pdf_engine.common import order_columns
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

GRID_WIDTH = 132

# --- Column layout (for `column_order`) -----------------------------------------------
# The items grid's columns in the sample's order. The form has no column for S or UNIT, so
# LINE+S and QUANTITY+UNIT are one movable column each ("line_s", "qty_unit"). Widths are in
# characters; a "|" separator sits between columns (and inside the two composites, at
# COL_INNER_SEP), so the sample's separators fall at 8, 10, 25, 31, 43, 74, 108, 120.
COLUMNS = ("line_s", "qty_unit", "im_sku", "part_number", "description", "cost", "ext")
COL_WIDTHS = {"line_s": 10, "qty_unit": 20, "im_sku": 11, "part_number": 30, "description": 33, "cost": 11, "ext": 11}
COL_INNER_SEP = {"line_s": 8, "qty_unit": 14}
QTY_CELL_WIDTH = 14  # the QUANTITY cell inside "qty_unit"
# The form's keys for the columns this PDF has (unit_cost / total are COST / EXTENDED).
FORM_KEYS = {"sno": "line_s", "qty": "qty_unit", "part_number": "part_number", "description": "description",
             "unit_cost": "cost", "total": "ext"}
# The form's own default order. Sent unchanged (or not sent), it means "the sample's layout".
FORM_DEFAULT_ORDER = ("sno", "part_number", "description", "qty", "unit_cost", "pct_disc", "terms", "total")
ANCHORS = {"im_sku": "part_number"}  # IM SKU has no form column: it sits just before MFG PART NO.
HEADER_ROW = 23  # index of the column-header line in HEADER_TEMPLATE


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


VENDORS_NOTE = "VENDORS PLEASE NOTE ANY CHANGES IN PRICE OR TERMS NEED APPROVAL BEFORE SHIPMENT"
MERCHANDISE_NOTE = (
    "MERCHANDISE SHIPPED ON THIS PURCHASE ORDER NOT IN",
    "AGREEMENT WITH THE SPECIFICS AS OUTLINED ABOVE WILL BE",
    "RETURNED UNLESS PRIOR APPROVAL HAS BEEN OBTAINED",
)
CONTINUED_TEXT = "*** CONTINUED ON NEXT PAGE ***"


class _Layout:
    """Where each column of the items grid sits for one PO.

    `order` is the left-to-right column keys, `start[key]` each column's first character
    and `seps` the columns of the "|" separators between them (and inside the LINE+S and
    QUANTITY+UNIT pairs). A column keeps its width wherever it moves, so the grid is always
    GRID_WIDTH wide. The sample's own order gives its separators (8, 10, 25, 31, 43, 74,
    108, 120) and cell starts (0, 11, 32, 44, 75, 109, 121) exactly."""

    def __init__(self, column_order: list[str] | None = None) -> None:
        requested = [FORM_KEYS[k] for k in (column_order or []) if k in FORM_KEYS]
        # The form's own default order means "untouched": print the sample's layout.
        if requested == [FORM_KEYS[k] for k in FORM_DEFAULT_ORDER if k in FORM_KEYS]:
            requested = []
        self.order = order_columns(requested, COLUMNS, ANCHORS)
        self.native = self.order == list(COLUMNS)
        self.start: dict[str, int] = {}
        seps: list[int] = []
        x = 0
        for i, key in enumerate(self.order):
            self.start[key] = x
            if key in COL_INNER_SEP:
                seps.append(x + COL_INNER_SEP[key])
            x += COL_WIDTHS[key]
            if i < len(self.order) - 1:
                seps.append(x)
                x += 1
        self.seps = tuple(sorted(seps))

    def header_line(self) -> str:
        """The column-header line with each column's title moved along with its column."""
        parts = HEADER_TEMPLATE[HEADER_ROW].split("|")
        cells = {
            "line_s": parts[0] + "|" + parts[1], "qty_unit": parts[2] + "|" + parts[3], "im_sku": parts[4],
            "part_number": parts[5], "description": parts[6], "cost": parts[7], "ext": parts[8],
        }
        return "|".join(cells[key] for key in self.order)

    def cell_box(self, key: str, width: int) -> tuple[int | None, int | None]:
        """Columns of the vertical rules on either side of a cell's first `width` characters;
        None where that side is the edge of the grid."""
        start = self.start[key]
        return (start - 1 if start > 0 else None), (start + width if start + width < GRID_WIDTH else None)

    def box_extent(self, key: str, width: int) -> tuple[int, int]:
        """First and last column a cell's box (rules included) occupies."""
        left, right = self.cell_box(key, width)
        start = self.start[key]
        return (left if left is not None else start), (right if right is not None else start + width - 1)


NATIVE = _Layout(None)


def _free_regions(extents: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The (first, last) column runs of the grid not covered by any of the boxes."""
    regions: list[tuple[int, int]] = []
    pos = 0
    for lo, hi in sorted(extents):
        if lo > pos:
            regions.append((pos, lo - 1))
        pos = max(pos, hi + 1)
    if pos < GRID_WIDTH:
        regions.append((pos, GRID_WIDTH - 1))
    return regions


def _place_notice(lines: list[str] | tuple[str, ...], regions: list[tuple[int, int]], center: bool) -> tuple[int, list[str]]:
    """(start column, lines) printing a notice in the widest free region: as given when it
    fits (centred, or indented two columns), else re-wrapped to that region's width."""
    first, last = max(regions, key=lambda r: r[1] - r[0])
    width = last - first + 1
    longest = max(len(line) for line in lines)
    if longest > width - 2:
        return first + 1, _wrap(" ".join(lines), width - 2)
    return (first + (width - longest) // 2 if center else first + 2), list(lines)


def _grid_row(line: str, text: str, qty: str = "", unit: str = "", sku: str = "", mfg: str = "",
              cost: str = "", ext: str = "", lay: _Layout | None = None) -> str:
    """One row of the items grid. In the sample's layout the separators sit at 8, 10, 25, 31,
    43, 74, 108, 120; cells: LINE 0..7, S 9, QUANTITY 11..24, UNIT 26..30, IM SKU 32..42,
    MFG 44..73, DESCRIPTION 75..107, COST 109..119, EXTENDED 121... `lay` moves them."""
    lay = lay or NATIVE
    start = lay.start
    row = _put("", start["line_s"] + 2, line) if line else ""
    for sep in lay.seps:
        row = _put(row, sep, "|")
    row = _put(row, start["qty_unit"], qty.rjust(7))  # quantity ends 7 columns in, as in the sample
    row = _put(row, start["qty_unit"] + 17, unit) if unit else row
    row = _put(row, start["im_sku"], sku)
    row = _put(row, start["part_number"], mfg[:30])
    row = _put(row, start["description"], text[:33])
    if cost:
        # The sample centers the cost in its 11-wide cell with the odd space on the right.
        pad = 11 - len(cost)
        row = _put(row, start["cost"], " " * (pad // 2) + cost + " " * (pad - pad // 2))
    if ext:
        row = _put(row, start["ext"], ext.rjust(11))
    return row.rstrip()


def _info_row(text: str, line: str = "", lay: _Layout | None = None) -> str:
    return _grid_row(line, text, lay=lay)


def _header_rows(fields: dict, lay: _Layout | None = None) -> list[str]:
    po = str(fields.get("po_number") or "")
    rows = list(HEADER_TEMPLATE)
    if lay is not None and not lay.native:
        rows[HEADER_ROW] = lay.header_line()
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


def _continued_row(lay: _Layout | None = None) -> str:
    if lay is None or lay.native:
        return "        | |*** CONTINUED ON NEXT PAGE ***  |                    |                    *** CONTINUED ON NEXT PAGE ***     |"
    # Reordered grid: every separator, with the notice in the MFG PART NO. and DESCRIPTION cells.
    row = ""
    for sep in lay.seps:
        row = _put(row, sep, "|")
    row = _put(row, lay.start["part_number"], CONTINUED_TEXT)
    row = _put(row, lay.start["description"], CONTINUED_TEXT)
    return row.rstrip()


def _rules_row(lay: _Layout, qty_total: str = "", ext_total: str = "", rules: bool = True) -> str:
    """The closing box's row: the rules around the QUANTITY cell and either side of EXTENDED,
    with the quantity and extended totals in those cells (as the sample's totals row)."""
    row = ""
    if qty_total:
        row = _put(row, lay.start["qty_unit"], qty_total.rjust(8))
    if ext_total:
        row = _put(row, lay.start["ext"] + 1, ext_total)
    if rules:
        for cell, width in (("qty_unit", QTY_CELL_WIDTH), ("ext", COL_WIDTHS["ext"])):
            for col in lay.cell_box(cell, width):
                if col is not None:
                    row = _put(row, col, "|")
    return row.rstrip()


def _total_row(lay: _Layout, qty_text: str, ext_text: str) -> str:
    if lay.native:
        return "          |" + qty_text.rjust(8) + " " * 6 + "|" + " " * 94 + "| " + ext_text
    return _rules_row(lay, qty_text, ext_text)


def _closing_head(lay: _Layout, total_row: str | None) -> list[str]:
    """The totals / MERCHANDISE SHIPPED box rows (the sample's first four closing rows),
    with the box, its totals and the notice laid out on `lay`'s columns."""
    if lay.native:
        return [
            total_row if total_row is not None else "          |              |" + " " * 94 + "|",
            "          |              |                    MERCHANDISE SHIPPED ON THIS PURCHASE ORDER NOT IN                         |",
            "           ==============                     AGREEMENT WITH THE SPECIFICS AS OUTLINED ABOVE WILL BE                     ===========",
            "                                              RETURNED UNLESS PRIOR APPROVAL HAS BEEN OBTAINED",
        ]
    # Reordered grid. As in the sample: the totals row, a second row continuing the box's
    # rules, then the "=" rules closing the QUANTITY and EXTENDED cells; the notice starts on
    # the second row, centred in the widest stretch the two boxes leave free.
    extents = [lay.box_extent("qty_unit", QTY_CELL_WIDTH), lay.box_extent("ext", COL_WIDTHS["ext"])]
    col, lines = _place_notice(MERCHANDISE_NOTE, _free_regions(extents), center=True)
    box = [_rules_row(lay), ""]
    box[1] = _put(_put("", lay.start["qty_unit"], "=" * QTY_CELL_WIDTH), lay.start["ext"], "=" * COL_WIDTHS["ext"])
    rows = [total_row if total_row is not None else _rules_row(lay)]
    for i in range(max(len(lines), 3)):
        row = box[i] if i < len(box) else ""
        if i < len(lines):
            row = _put(row, col, lines[i])
        rows.append(row.rstrip())
    return rows


def _vendors_rows(lay: _Layout) -> list[str]:
    """The last page's "VENDORS PLEASE NOTE" row, boxed over the COST cell as in the sample."""
    if lay.native:
        return ["  " + VENDORS_NOTE + " " * 27 + "|           |"]
    cost_rules = [c for c in lay.cell_box("cost", COL_WIDTHS["cost"]) if c is not None]
    col, lines = _place_notice([VENDORS_NOTE], _free_regions([lay.box_extent("cost", COL_WIDTHS["cost"])]), center=False)
    rows = []
    for line in lines:
        row = _put("", col, line)
        for rule in cost_rules:
            row = _put(row, rule, "|")
        rows.append(row.rstrip())
    return rows


def _closing_rows(fields: dict, total_row: str | None = None, lay: _Layout | None = None, last_page: bool = False) -> list[str]:
    lay = lay or NATIVE
    rows = _closing_head(lay, total_row)
    rows.append(" " * 47 + f"AUTHORIZED BY: {fields.get('authorized_by') or ''}".rstrip())
    if last_page:
        # The sample's last form page ends after the AUTHORIZED BY line.
        return rows
    rows.append("  FROM    : " + sandbox_text(str(fields.get("mail_from") or "")))
    rows.append("  TO      : " + sandbox_text(str(fields.get("mail_to") or "")))
    rows.append("  BCC     : " + sandbox_text(str(fields.get("mail_bcc") or "")))
    rows.append("  SUBJECT : " + str(fields.get("mail_subject") or ""))
    return rows


# --- Items --------------------------------------------------------------------------
def _end_user_rows(fields: dict, lay: _Layout | None = None) -> list[str]:
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
    return [_info_row(line, lay=lay) for line in lines]


def _special_rows(fields: dict, lay: _Layout | None = None) -> list[str]:
    """Lines 001 (DIRECT SHIP / RESELLER INFO) and 002 (HEADER) -- not priced items."""
    rows = [
        _info_row("********* DIRECT SHIP INFO ****", "001", lay=lay),
        _info_row("****", "001", lay=lay),
        _info_row("********** RESELLER INFO ******", lay=lay),
        _info_row("****", lay=lay),
        _info_row(f"RSLR CONT:{fields.get('reseller_contact') or ''}"[:DESC_WIDTH + 2], lay=lay),
        _info_row(f"RSLR PHON:{fields.get('reseller_phone') or ''}"[:DESC_WIDTH + 2], lay=lay),
        _info_row("********** END USER INFO ******", lay=lay),
        _info_row("****", lay=lay),
        _info_row("", lay=lay),
        _info_row("HEADER", "002", lay=lay),
        _info_row(f"QUOTE # {fields.get('quote_number') or ''}", lay=lay),
        _info_row(f"EU PO# {fields.get('end_user_po') or ''}", lay=lay),
        _info_row("***SHIP-TO CONTACT INFO***", lay=lay),
        _info_row(f"NAME: {fields.get('ship_to_contact_name') or ''}", lay=lay),
        _info_row(f"PHONE: {fields.get('ship_to_contact_phone') or ''}", lay=lay),
        _info_row(f"EMAIL: {fields.get('ship_to_contact_email') or ''}", lay=lay),
        _info_row(f"SHIPPING TERMS: {fields.get('shipping_terms') or ''}", lay=lay),
        _info_row("INGRAM MICRO ACCEPTS ALL", lay=lay),
        _info_row(" ADDITIONAL TERMS ON RUBRIK QUO", lay=lay),
        _info_row("TE #", lay=lay),
        _info_row(f" {fields.get('quote_number') or ''} DATED {fields.get('quote_date') or ''}", lay=lay),
        _info_row("", lay=lay),
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


def _item_rows(item: _Item, fields: dict, lay: _Layout | None = None) -> list[str]:
    raw = item.raw
    desc_lines = _wrap(str(raw.get("description") or ""), DESC_WIDTH)
    qty_text = f"{int(item.qty)}" if item.qty == item.qty.to_integral_value() else f"{item.qty.normalize():f}"
    rows = [
        _grid_row(
            item.line, desc_lines[0], qty=qty_text, unit=str(raw.get("unit") or "EA"), sku=str(raw.get("im_sku") or ""),
            mfg=str(raw.get("part_number") or ""), cost=_money(item.net_cost), ext=_money(item.extended), lay=lay,
        )
    ]
    rows += [_info_row(line, lay=lay) for line in desc_lines[1:]]

    eu_number = str(raw.get("eu_number") or fields.get("eu_number") or "")
    eu_name = str(raw.get("eu_name") or fields.get("eu_name") or "")
    eu_text = f"EU#- {eu_number} {eu_name}".rstrip()
    first = eu_text[:DESC_WIDTH]
    rows.append(_info_row(first, lay=lay))
    rest = eu_text[DESC_WIDTH:]
    while rest:
        rows.append(_info_row(rest[:DESC_WIDTH], lay=lay))
        rest = rest[DESC_WIDTH:]
    rows.append(_info_row("MC#C", lay=lay))
    terms = re.sub(r"\s+", " ", str(raw.get("terms") or "").strip())
    match = re.match(r"^(\d+) MONTHS? (.*)$", terms, re.IGNORECASE)
    rows.append(_info_row(f"{match.group(1)} MONTHS  {match.group(2)}" if match else terms, lay=lay))
    serial = str(raw.get("serial_number") or "").strip()
    if serial:
        serial_line = f" {serial}"
        for i in range(0, len(serial_line), DESC_WIDTH):
            rows.append(_info_row(serial_line[i : i + DESC_WIDTH], lay=lay))
    rows += _end_user_rows(fields, lay)
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


def _build_stream(fields: dict, items: list[_Item], line_items: list[dict], lay: _Layout | None = None) -> list[str]:
    lay = lay or NATIVE
    body = _special_rows(fields, lay)
    for item in items:
        body += _item_rows(item, fields, lay)

    total_qty = sum((i.qty for i in items), Decimal("0"))
    total_ext = sum((i.extended for i in items), Decimal("0"))
    qty_text = f"{int(total_qty)}" if total_qty == total_qty.to_integral_value() else f"{total_qty.normalize():f}"
    total_row = _total_row(lay, qty_text, _money(total_ext))

    stream: list[str] = []
    for page_body in _paginate(body):
        stream += _header_rows(fields, lay)
        stream += page_body
        stream.append(_continued_row(lay))
        stream.append(RULE)
        stream += _closing_rows(fields, lay=lay)
    # The last form page: header, the "VENDORS PLEASE NOTE" row, the totals row and the closing block
    # (which ends after the AUTHORIZED BY line, as the sample's does).
    stream += _header_rows(fields, lay)
    stream += _vendors_rows(lay)
    stream.append(RULE)
    stream += _closing_rows(fields, total_row, lay=lay, last_page=True)
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


def generate_ingram_micro_canada_po(fields: dict, line_items: list[dict], column_order: list[str] | None = None) -> bytes:
    fields = dict(fields)
    live = [i for i in line_items if i and (i.get("part_number") or i.get("description"))]
    items = [_Item(raw, number) for number, raw in enumerate(live, start=3)]
    stream = _build_stream(fields, items, live, _Layout(column_order))

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
