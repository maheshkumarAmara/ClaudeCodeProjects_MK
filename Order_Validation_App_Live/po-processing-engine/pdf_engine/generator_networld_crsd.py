"""Regenerates the Networld Corporation PO for the CRSD layout ("4700738674 .pdf").

Used only for Networld, and only when the form's CRSD date is filled in; with no CRSD the
ordinary generator (generator_networld_corporation.py, "4700670275 Details .pdf") is used.

The template is two pages:
  - Page 1, the Japanese "PURCHASING ORDER". Everything stays as the template prints it
    except the "*IMPORTANT NOTICE : CRSD July 1st, 2026" line, which carries the form's
    CRSD date.
  - Page 2, "Details of PO#": the same sheet as the ordinary Networld template, with the
    PO number, quote number, line items, total and label / value block taken from the form.

Behaviours worth knowing:
  - Page 1 is one big text block, so the old CRSD text is covered by a white box and the
    new date is drawn over it; main._build_po_pdf then removes the covered text (this
    distributor is listed in main._STRIP_PER_SHOW) so it is not left hidden in the file.
  - Page 2 has 5 row slots in the template, then the legal-terms row and the Total row.
    More rows grow the grid, and the legal-terms / Total rows and the label / value block
    move down with it. A PO that no longer fits the page continues on extra copies of
    page 2 (heading and column header repeated); the Total row and the label / value
    block go on the last one.
  - A row's Net Total Price is its unit cost, less any "% disc."; the Total row is
    Sum(qty x Net Total Price). "terms" is a display value.
  - Values print as "$1,234.56".
"""

import io
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pypdf import PageObject, PdfReader, PdfWriter, Transformation
from pypdf.generic import DecodedStreamObject, NameObject
from reportlab.pdfgen import canvas

import config
from pdf_engine import generator_networld_corporation as base
from pdf_engine.common import clip_text, fit_size
from pdf_engine.generator import _render_overlay
from pdf_engine.paginate import _to_decimal, wrap_text

SLUG = "Networld Corporation"
TEMPLATE_NAME = "4700738674 .pdf"

BLACK, WHITE = base.BLACK, base.WHITE
BLUE = base.BLUE
RED = base.RED
GREEN = base.GREEN
TEXT_SIZE = 9.4

# --- Page 1: the Japanese PO page ---------------------------------------------------
P1_W, P1_H = 841.606, 595.559
# The "*IMPORTANT NOTICE : CRSD July 1st, 2026" line (words x 102..288, top 427.1).
CRSD_LINE_TOP = 427.1
CRSD_LINE_X = 102.0
CRSD_COVER = (100.0, 426.0, 330.0, 437.2)  # left, top, right, bottom
P1_SIZE = 9.3  # the template line is MS-Mincho 9.3pt
# The quote number printed just above the CRSD notice ("Q-854316", words x 102.0..140.5, top 417.2).
QUOTE_LINE_TOP = 417.2
QUOTE_LINE_COVER = (100.0, 426.0 - 10.0, 330.0, 426.0)
# The PO# cell: rules at x=121.9 and x=240.9, 119.1..138.9 tall; the 10 digits (MS-Mincho 18.5pt)
# run x=140.6..237.1, top 120.0. Only the area between the rules is covered, so the "PO#" label
# and the cell's own borders stay as the template draws them.
PO_CELL_COVER = (122.8, 119.9, 240.0, 138.1)
PO_DIGITS_X = 140.6
PO_DIGITS_RIGHT = 237.1
PO_DIGITS_TOP = 120.0
PO_DIGITS_SIZE = 18.5
# The "TOTAL : USD" figure ("208,587.66", MS-Mincho 18.5pt, right edge x=764.4, top 407.7) sits in a cell
# between the rule at x=671.8, the top rule at y=406.8 and the double rule at y=426.6. The cover stays
# inside those so every rule is left as the template draws it.
TOTAL_CELL_COVER = (673.0, 408.0, 773.0, 426.3)
TOTAL_DIGITS_RIGHT = 764.4
TOTAL_DIGITS_TOP = 407.7
TOTAL_DIGITS_SIZE = 18.5
TOTAL_PITCH = 9.65  # the template's glyph column width (digits sit 9.65pt apart)
# The SHIP TO block at the bottom left (MS-Mincho 9.3pt). Row 1 is "SHIP TO:" (label at x=68) plus the
# first line (starting x=96); rows 2-5 are the address at x=113.4, and row 6 (one blank row lower) is
# the TEL line. The BILL TO block starts at x=306, so covers stop at x=300.
SHIPTO_LABEL_X = 68.0
SHIPTO_NAME_X = 113.4  # the template's own name column: "SHIP" at 68, "TO:" at 96.4..112.5, name from 113.4
SHIPTO_ADDR_X = 113.4
SHIPTO_COVER_RIGHT = 300.0
SHIPTO_TEXT_RIGHT = 296.0  # text never runs past here (BILL TO begins at x=306)
SHIPTO_MIN_SIZE = 6.0  # a long line shrinks to this, then is cut at SHIPTO_TEXT_RIGHT
SHIPTO_ROW_TOPS = (486.6, 496.5, 506.5, 516.4, 526.3, 546.1)
# The BILL TO block, to the right of SHIP TO (MS-Mincho 9.3pt). Row 1 is "BILL TO:" ("BILL" at 306.1, "TO:" at
# 334.5) plus the first line (from x=351.5); rows 2-4 are the address at x=351.5, then one blank row, then
# TEL and FAX on rows 5-6. "Signature" starts at x=556 on row 1, so covers stop at x=545 and text at x=540.
BILLTO_LABEL_X = 306.1
BILLTO_TO_X = 334.5
BILLTO_TEXT_X = 351.5
BILLTO_COVER_LEFT = 305.5
BILLTO_COVER_RIGHT = 545.0
BILLTO_TEXT_RIGHT = 540.0
BILLTO_ROW_TOPS = (486.6, 496.5, 506.5, 516.4, 536.2, 546.1)

# --- Page 2: the Details of PO# page --------------------------------------------------
P2_W, P2_H = 841.92, 595.32
GRID_LEFT, GRID_RIGHT = 23.5, 737.0
# Vertical rules (x, width) and the template's grid: header band 118.3-145.8, then item rows
# separated by 0.8pt rules. Rows are 11.6pt apart (one-line rows) with taller two-line rows.
_VRULES = ((22.7, 0.8), (179.9, 0.8), (552.0, 0.8), (596.0, 0.9), (647.9, 0.8), (736.2, 0.8))
HEAD_BOTTOM = 146.6        # bottom of the column-header band (its rule included)
ROW_TOP0 = 145.8           # top rule above the first item row
ROW_PITCH = 11.6
ROW_TEXT_OFFSET = 2.1      # text top below the row's top rule (147.9 - 145.8)
TEMPLATE_ROWS = 5          # item rows the template draws
RULE_THIN = 0.8
LEGAL_TEXT_OFFSET = 7.6    # legal-terms text top below its row's top rule
TOTAL_TOP_TEMPLATE = 238.9  # the template's rule above the legal-terms / Total row
TOTAL_ROW_HEIGHT = 262.2 - 238.9 + RULE_THIN
BLOCK_TOP = 280.0          # label / value block clip starts here
BLOCK_GAP = BLOCK_TOP - (TOTAL_TOP_TEMPLATE + TOTAL_ROW_HEIGHT)
PAGE_BOTTOM = 560.0
BLOCK_BOTTOM_PAD = 24.0
LAST_BLOCK_LINE_BOTTOM = 538.1

CODE_X = 24.8
DESC_X = 182.0
QTY_CENTER = (552.8 + 596.0) / 2
TERM_CENTER = (596.9 + 647.9) / 2
AMOUNT_RIGHT = 731.7
DESC_ROOM = 552.0 - DESC_X - 1.5
CODE_ROOM = 179.9 - CODE_X - 3.0

# --- Column order -----------------------------------------------------------------
# Same five columns as the ordinary layout (generator_networld_corporation.py), with this
# layout's own edges and widths; the form-key mapping, ignored keys and header redraw are shared.
COL_EDGES = tuple(x for x, _ in _VRULES)
COL_WIDTHS = {key: COL_EDGES[i + 1] - COL_EDGES[i] for i, key in enumerate(base.COLUMNS)}
CODE_PAD = CODE_X - COL_EDGES[0]
DESC_PAD = DESC_X - COL_EDGES[1]
AMOUNT_PAD = COL_EDGES[5] - AMOUNT_RIGHT
QTY_OFFSET = QTY_CENTER - COL_EDGES[2]
TERM_OFFSET = TERM_CENTER - COL_EDGES[3]
TOTAL_LABEL_PAD = COL_EDGES[4] - 646.4  # "Total" ends this far left of the amount column
# The teal column-header band and its title lines (template tops, measured from page 2).
BAND = (23.5, 118.7, 736.7, 146.3)
BAND_FILL = (0.0, 0.698039, 0.662745)
HEAD_TOPS = (121.6, 128.2, 134.8)


def _columns(column_order: list[str] | None) -> "base._Columns":
    return base._Columns(column_order, COL_EDGES, COL_WIDTHS, _VRULES)


DEFAULT_COLUMNS = _columns(None)

# Heading (page 2): the green PO number band and the quote number.
PO_NUMBER_BOX = (180.2, 66.0, 552.5, 86.6)
PO_NUMBER_RIGHT = 550.6
PO_NUMBER_TOP = 72.2
QUOTE_BOX = (180.5, 91.0, 420.0, 104.0)
QUOTE_X = 182.0
QUOTE_TOP = 92.7
LEGAL_BOX = (24.0, 241.0, 595.0, 261.0)
LEGAL_X = 24.8

VALUE_X = 182.0
VALUE_COVER_RIGHT = 760.0
# (key, text top, colour, underline). Tops measured from the template.
_VALUE_LINES = {
    "incoterms": (290.7, BLACK, False),
    "payment_terms": (304.4, BLACK, False),
    "order_notification_email": (318.8, BLUE, True),
    "billing_email": (332.5, BLUE, True),
    "end_user_name": (346.1, BLUE, True),
    "end_user_po": (359.8, BLUE, True),
    "forwarder_company": (400.5, BLACK, False),
    "forwarder_phone": (412.1, BLACK, False),
    "forwarder_fax": (423.8, BLACK, False),
    "forwarder_contact_1": (435.4, BLACK, False),
    "forwarder_contact_2": (447.1, BLACK, False),
    "ship_to_mail": (528.8, BLACK, False),
}
SHIP_TO_FIRST_TOP = 470.3
SHIP_TO_PITCH = 11.65
SHIP_TO_LINES = 5

# In this template a row's label and its old value are one text run (for example
# "IncotermsFCAorigin"), so covering only the value leaves that run in the file. The cover
# therefore starts at the label's left edge and the label is redrawn here, which lets the
# cleanup drop the whole old run. (key -> label as the template prints it.)
LABEL_X = 24.8
LABEL_COVER_LEFT = 23.5
LABEL_RIGHT_EDGE = 180.2  # where the heading's green PO band starts (the label sits left of it)
_LABELS = {
    "incoterms": "Incoterms",
    "payment_terms": "Payment Terms",
    "order_notification_email": "Order/shipping/license notification",
    "billing_email": "Email for billing invoice",
    "end_user_name": "End User Name",
    "end_user_po": "End User PO#",
    "forwarder_company": "Company Name",
    "forwarder_phone": "Phone#",
    "forwarder_fax": "Fax#",
    "ship_to_mail": "mail address",
}
# The label is bold on the three blue rows' neighbours only for the End User rows, as printed.
_BOLD_LABELS = {"end_user_name", "end_user_po"}


# --- Date -----------------------------------------------------------------------------
def _ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        return f"{day}th"
    return f"{day}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th') }"


def crsd_text(value: str) -> str:
    """"2026-07-01" (the form's date input) or "07/01/2026" -> "July 1st, 2026"; "" if unusable."""
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%b %d %Y", "%Y/%m/%d"):
        try:
            d: date = datetime.strptime(text, fmt).date()
            return f"{d.strftime('%B')} {_ordinal(d.day)}, {d.year}"
        except ValueError:
            continue
    return ""


# --- Rows -------------------------------------------------------------------------------
class _Row:
    def __init__(self, item: dict) -> None:
        self.code = str(item.get("part_number") or "")
        self.qty = _to_decimal(item.get("qty"))
        self.unit_cost = _to_decimal(item.get("unit_cost"))
        self.terms = str(item.get("terms") or "").strip()
        pct = _to_decimal(item.get("pct_disc"))
        description = str(item.get("description") or "")
        self.desc_lines = wrap_text(description, DESC_ROOM, TEXT_SIZE) if description else [""]
        # Net Total Price prints the row's unit cost (Salesforce SBQQ__NetPrice__c), not qty x unit cost.
        self.amount = (self.unit_cost * (Decimal("1") - pct / Decimal("100"))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        # The Total row is the sum of qty x that printed price, one term per row.
        self.line_total = (self.qty * self.amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def height(self) -> float:
        return ROW_PITCH * max(1, len(self.desc_lines))


def _draw_row(c: canvas.Canvas, row: _Row, top: float, cols=None) -> None:
    cols = cols or DEFAULT_COLUMNS
    text_top = top + ROW_TEXT_OFFSET
    box = cols.boxes
    _text(c, box["part_number"][0] + CODE_PAD, text_top, row.code, max_width=CODE_ROOM)
    for i, line in enumerate(row.desc_lines):
        _text(c, box["description"][0] + DESC_PAD, text_top + ROW_PITCH * i, line)
    _text(c, box["qty"][0] + QTY_OFFSET, text_top, base._qty_text(row.qty), align="center")
    _text(c, box["terms"][0] + TERM_OFFSET, text_top, row.terms, align="center")
    _text(c, box["amount"][1] - AMOUNT_PAD, text_top, base._money(row.amount), align="right")


# --- Drawing helpers (page 2 and page 1 use different page sizes) --------------------------
def _text(c, x, top, text, size=TEXT_SIZE, *, bold=False, align="left", color=BLACK, underline=False,
          max_width=None, links=None, page_h=P2_H) -> None:
    saved = base.PAGE_H
    base.PAGE_H = page_h
    try:
        base._text(c, x, top, text, size, bold=bold, align=align, color=color, underline=underline,
                   max_width=max_width, links=links)
    finally:
        base.PAGE_H = saved


def _cover(c, box, dy=0.0, fill=WHITE, page_h=P2_H) -> None:
    left, top, right, bottom = box
    c.saveState()
    c.setFillColorRGB(*fill)
    c.rect(left, page_h - bottom - dy, right - left, bottom - top, fill=1, stroke=0)
    c.restoreState()


def _hrule(c, y_top, thickness=RULE_THIN) -> None:
    c.saveState()
    c.setFillColorRGB(*BLACK)
    c.rect(GRID_LEFT, P2_H - y_top - thickness, GRID_RIGHT - GRID_LEFT, thickness, fill=1, stroke=0)
    c.restoreState()


# The legal-terms / Total row spans the description columns, so it has no rule at 179.9 or 552.0.
_TOTAL_ROW_VRULES = tuple(v for v in _VRULES if v[0] not in (179.9, 552.0))


def _total_row_vrules(cols) -> tuple:
    """The Total row's rules. Its red legal-terms line runs from the grid's left edge to
    LEGAL_BOX's right edge (595), so no rule may cross that span, wherever the columns are;
    the outer left border and the rules to the right of the span are kept. For the default
    order this is exactly _TOTAL_ROW_VRULES (the rules at 179.9 and 552.0 are dropped)."""
    legal_right = LEGAL_BOX[2]
    first = cols.rules[0]
    return (first,) + tuple(r for r in cols.rules[1:] if r[0] > legal_right)


def _vrules(c, y_top, y_bottom, rules=_VRULES) -> None:
    c.saveState()
    c.setFillColorRGB(*BLACK)
    for x, width in rules:
        c.rect(x, P2_H - y_bottom, width, y_bottom - y_top, fill=1, stroke=0)
    c.restoreState()


# --- Cutting pieces out of the template page 2 ----------------------------------------------
def _clip_piece(template_bytes: bytes, page_index: int, top: float, bottom: float) -> PageObject:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(template_bytes)))
    page = writer.pages[page_index]
    data = page.get_contents().get_data()
    stream = DecodedStreamObject()
    stream.set_data(f"q 0 {P2_H - bottom:.3f} {P2_W:.3f} {bottom - top:.3f} re W n\n".encode() + data + b"\nQ")
    page[NameObject("/Contents")] = writer._add_object(stream)
    if "/Annots" in page:
        del page["/Annots"]
    return page


def _compose_details_page(template_bytes: bytes, pieces, overlay_page) -> PageObject:
    page = PageObject.create_blank_page(width=P2_W, height=P2_H)
    for top, bottom, dy_down in pieces:
        piece = _clip_piece(template_bytes, 1, top, bottom)
        page.merge_transformed_page(piece, Transformation().translate(0, -dy_down))
    page.merge_page(overlay_page)
    return page


# --- Pagination of page 2 ----------------------------------------------------------------------
def _paginate(rows: list[_Row]) -> list[dict]:
    tail = (LAST_BLOCK_LINE_BOTTOM - TOTAL_TOP_TEMPLATE) + BLOCK_BOTTOM_PAD
    pages: list[dict] = []

    def new_page(first: bool) -> dict:
        page = {"rows": [], "first": first, "cursor": ROW_TOP0, "block": False}
        pages.append(page)
        return page

    page = new_page(True)
    for row in rows:
        if page["rows"] and page["cursor"] + row.height > PAGE_BOTTOM:
            page = new_page(False)
        page["rows"].append((row, page["cursor"]))
        page["cursor"] += row.height

    min_end = ROW_TOP0 + ROW_PITCH * TEMPLATE_ROWS if page["first"] else page["cursor"]
    # One empty row is always left between the last product and the Total row (a short PO's
    # padding to the template's slots already includes one).
    end = max(page["cursor"] + ROW_PITCH, min_end)
    if end + tail <= P2_H or (not rows and page["first"]):
        page["block"] = True
        page["cursor"] = end
        return pages

    last = new_page(False)
    if len(page["rows"]) > 1:
        moved, _ = page["rows"].pop()
        page["cursor"] -= moved.height
        last["rows"].append((moved, last["cursor"]))
        last["cursor"] += moved.height
    # The same one empty row between the last product and the Total row as above.
    last["cursor"] += ROW_PITCH
    last["block"] = True
    return pages


def _draw_heading(c, fields: dict) -> None:
    # "Details of PO#" and the PO number are one template run, and so are "Quote #:" and the
    # quote number, so each cover starts at the label's left edge and the label is redrawn.
    left, top, right, bottom = PO_NUMBER_BOX
    _cover(c, (LABEL_COVER_LEFT, top, LABEL_RIGHT_EDGE, bottom))
    _cover(c, PO_NUMBER_BOX, fill=GREEN)
    _text(c, LABEL_X, PO_NUMBER_TOP, "Details of PO#")
    _text(c, PO_NUMBER_RIGHT, PO_NUMBER_TOP, str(fields.get("po_number") or ""), align="right")
    left, top, right, bottom = QUOTE_BOX
    _cover(c, (LABEL_COVER_LEFT, top, right, bottom))
    _text(c, LABEL_X, QUOTE_TOP, "Quote #:")
    _text(c, QUOTE_X, QUOTE_TOP, str(fields.get("quote_number") or ""))


def _draw_value_block(c, fields: dict, dy: float, links: list) -> None:
    for key, (top, color, underline) in _VALUE_LINES.items():
        label = _LABELS.get(key)
        # Rows with a label also cover it (the template's label and old value are one run).
        _cover(c, ((LABEL_COVER_LEFT if label else VALUE_X - 2.0), top - 0.6, VALUE_COVER_RIGHT, top + 12.0), dy)
        if label:
            # The two End User labels print in red in the template, as well as bold.
            _text(c, LABEL_X, top + dy, label, bold=key in _BOLD_LABELS, color=RED if key in _BOLD_LABELS else BLACK)
        _text(c, VALUE_X, top + dy, str(fields.get(key) or ""), color=color, underline=underline,
              max_width=VALUE_COVER_RIGHT - VALUE_X - 6.0, links=links)
    # "SHIP TO :" and the first address line are one template run, so the cover starts at the label.
    _cover(c, (LABEL_COVER_LEFT, SHIP_TO_FIRST_TOP - 0.6, VALUE_COVER_RIGHT, SHIP_TO_FIRST_TOP + SHIP_TO_LINES * SHIP_TO_PITCH), dy)
    _text(c, LABEL_X, SHIP_TO_FIRST_TOP + dy, "SHIP TO :")
    for i, line in enumerate(str(fields.get("ship_to_block") or "").split("\n")[:SHIP_TO_LINES]):
        _text(c, VALUE_X, SHIP_TO_FIRST_TOP + SHIP_TO_PITCH * i + dy, line, max_width=VALUE_COVER_RIGHT - VALUE_X - 6.0)


def _draw_total_row(c, top: float, total: Decimal, fields: dict, cols=None) -> None:
    cols = cols or DEFAULT_COLUMNS
    bottom = top + TOTAL_ROW_HEIGHT - RULE_THIN
    _hrule(c, top)
    _hrule(c, bottom)
    quote = str(fields.get("quote_number") or "").strip()
    legal_date = _legal_date(fields)
    legal = f"<Networld Corporation> ACCEPTS ALL ADDITIONAL TERMS ON <{quote}> DATED <{legal_date}>" if quote else ""
    # The template prints the legal-terms line in red.
    _text(c, LEGAL_X, top + LEGAL_TEXT_OFFSET, legal, bold=True, color=RED, max_width=595.0 - LEGAL_X - 4.0)
    amount_left, amount_right = cols.boxes["amount"]
    _text(c, amount_left - TOTAL_LABEL_PAD, top + LEGAL_TEXT_OFFSET, "Total", bold=True, align="right")
    _text(c, amount_right - AMOUNT_PAD, top + LEGAL_TEXT_OFFSET, base._money(total), bold=True, align="right")


def _legal_date(fields: dict) -> str:
    """The date in the legal-terms line, kept as the template prints it unless the form has one."""
    raw = str(fields.get("legal_terms_date") or "").strip()
    return raw or "03/31/2026"


TEMPLATE_QUOTE = "Q-854316"  # the quote number the template's page 1 was made with
ITEM_CODE_X = 102.0  # item codes ("Q-854316", "Q-854316R", ...) start here, in the ITEM MODEL column
ITEM_CODES_BOTTOM = 400.0  # item rows end above the notes area (the quote line sits at 417)


def _template_item_codes(template_bytes: bytes) -> list[tuple[float, float, float, str]]:
    """(x0, x1, top, text) of each item code printed on page 1: words that start with the
    template's own quote number, in the ITEM MODEL column, above the notes area."""
    import pdfplumber

    found = []
    with pdfplumber.open(io.BytesIO(template_bytes)) as pdf:
        for w in pdf.pages[0].extract_words(x_tolerance=2):
            if w["text"].startswith(TEMPLATE_QUOTE) and abs(w["x0"] - ITEM_CODE_X) < 1.5 and w["top"] < ITEM_CODES_BOTTOM:
                found.append((w["x0"], w["x1"], w["top"], w["text"]))
    return found


def _ship_to_rows(ship_to_block: str) -> list[str]:
    """The form's ship-to lines for the template's six rows. Up to five lines fill rows 1-5 in
    order; a longer block keeps its first four lines and puts its last line (the TEL line) on
    row 6, as the template does. Blank lines are skipped; extra middle lines are dropped."""
    lines = [ln.strip() for ln in str(ship_to_block or "").splitlines() if ln.strip()]
    if len(lines) <= 5:
        return lines
    return lines[:4] + [""] + [lines[-1]]


def _bill_to_rows(bill_to_block: str) -> list[tuple[int, str]]:
    """(row index, text) for the form's bill-to lines on the template's six rows. Up to four
    lines fill rows 1-4; with more, the last two (TEL and FAX in the template) go on rows 5-6, a
    fifth line alone being the TEL row. Blank lines are skipped; extra middle lines are dropped."""
    lines = [ln.strip() for ln in str(bill_to_block or "").splitlines() if ln.strip()]
    if len(lines) <= 4:
        return list(enumerate(lines))
    if len(lines) == 5:
        return list(enumerate(lines[:4])) + [(4, lines[4])]
    return list(enumerate(lines[:4])) + [(4, lines[-2]), (5, lines[-1])]


_bill_to_default_cache: str | None = None


def template_bill_to_block() -> str:
    """The BILL TO text the CRSD template prints on page 1, one line per row (the form's starting
    value for BILL_TO_BLOCK). Read from the template itself; "" if it cannot be read."""
    global _bill_to_default_cache
    if _bill_to_default_cache is not None:
        return _bill_to_default_cache
    text = ""
    try:
        import pdfplumber

        path = Path(config.TEMPLATES_DIR) / SLUG / TEMPLATE_NAME
        with pdfplumber.open(path) as pdf:
            page = pdf.pages[0]
            lines = []
            for top in BILLTO_ROW_TOPS:
                # One crop per row, from the name column to the block's right edge: on row 1 the label and the
                # name read as one word ("TO:Networld"), so cropping (not filtering words) keeps just the
                # name, and "Signature" (x=556) lies past the crop.
                # (Rows are only about 10pt apart, so the crop stays inside the row's own text box.)
                crop = page.crop((BILLTO_TEXT_X - 0.5, top + 0.3, BILLTO_COVER_RIGHT, top + 9.0))
                lines.append((crop.extract_text(x_tolerance=2) or "").strip())
        text = "\n".join(ln for ln in lines if ln)
    except Exception:  # an unreadable template just means the field starts empty
        text = ""
    if text:  # only a successful read is remembered, so a failed one is retried next time
        _bill_to_default_cache = text
    return text


def _draw_page1_total(c: canvas.Canvas, text: str) -> None:
    """The page 1 "TOTAL : USD" figure, drawn like the template's: one monospaced glyph per
    9.65pt column (every character, the comma and period included, takes a column), right
    edge at x=764.4. A total with more digits than the cell holds shrinks its pitch and size
    so it stays right of the cell's left rule."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    room = TOTAL_DIGITS_RIGHT - 674.0
    pitch = min(TOTAL_PITCH, room / max(len(text), 1))
    size = TOTAL_DIGITS_SIZE * pitch / TOTAL_PITCH
    baseline = P1_H - TOTAL_DIGITS_TOP - size * 0.793
    c.saveState()
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Courier", size)
    left = TOTAL_DIGITS_RIGHT - pitch * len(text)
    for i, ch in enumerate(text):
        # Centre each glyph in its column the way a fixed-pitch font sets it.
        c.drawString(left + pitch * i + (pitch - stringWidth(ch, "Courier", size)) / 2, baseline, ch)
    c.restoreState()


def _crsd_page(template_bytes: bytes, crsd: str, quote_number: str = "", po_number: str = "",
               ship_to_block: str = "", bill_to_block: str = "", total: Decimal | None = None) -> PageObject:
    """Page 1 of the template with only the PO number, quote number (also inside the item
    codes), SHIP TO block, BILL TO block, CRSD notice and "TOTAL : USD" figure changed. The
    total is the same Sum(qty x Net Total Price) that page 2's Total row prints."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(template_bytes)))
    page = writer.pages[0]
    overlay_text = f"*IMPORTANT NOTICE : CRSD {crsd}"
    item_codes = _template_item_codes(template_bytes) if quote_number else []
    ship_rows = _ship_to_rows(ship_to_block)
    bill_rows = _bill_to_rows(bill_to_block)

    def draw(c: canvas.Canvas) -> None:
        if bill_rows:
            # Same approach as the SHIP TO block: every template row of the block is covered over the full
            # glyph height, row 1's "BILL TO:" label (one text run with the old name) is redrawn spaced as
            # the template spaces it, and the form's lines are drawn on their rows. "Signature" starts at
            # x=556 on row 1, past the cover's right edge (545), so it is left alone.
            for top in BILLTO_ROW_TOPS:
                _cover(c, (BILLTO_COVER_LEFT, top - 0.1, BILLTO_COVER_RIGHT, top + 9.5), page_h=P1_H)
            _text(c, BILLTO_LABEL_X, BILLTO_ROW_TOPS[0], "BILL", P1_SIZE, page_h=P1_H)
            _text(c, BILLTO_TO_X, BILLTO_ROW_TOPS[0], "TO:", P1_SIZE, page_h=P1_H)
            room = BILLTO_TEXT_RIGHT - BILLTO_TEXT_X
            for row, line in bill_rows:
                size = fit_size(line, "Helvetica", P1_SIZE, room, SHIPTO_MIN_SIZE)
                _text(c, BILLTO_TEXT_X, BILLTO_ROW_TOPS[row], clip_text(line, "Helvetica", size, room), size, page_h=P1_H)
        if ship_rows:
            # Every template row of the block is covered (each only inside its own text box, so nothing
            # around it is touched) and the form's lines are drawn in their place. On row 1 the template's
            # "SHIP TO:" label and the old name are one text run, so that cover starts at the label's left
            # edge and the label is redrawn here.
            # No rules run through this block, so each cover takes the full glyph height (top .. top+9.4):
            # a shorter box leaves descenders (p, y, g) outside it and the cleanup then keeps that text.
            for i, top in enumerate(SHIPTO_ROW_TOPS):
                left = SHIPTO_LABEL_X - 0.6 if i == 0 else SHIPTO_ADDR_X - 0.6
                _cover(c, (left, top - 0.1, SHIPTO_COVER_RIGHT, top + 9.5), page_h=P1_H)
            # The template spaces the label ("SHIP" at 68, "TO:" at 96.4), so it is drawn the same way,
            # which also keeps the redrawn "TO:" left of the name column (113.4).
            _text(c, SHIPTO_LABEL_X, SHIPTO_ROW_TOPS[0], "SHIP", P1_SIZE, page_h=P1_H)
            _text(c, 96.4, SHIPTO_ROW_TOPS[0], "TO:", P1_SIZE, page_h=P1_H)
            for i, line in enumerate(ship_rows):
                x = SHIPTO_NAME_X if i == 0 else SHIPTO_ADDR_X
                room = SHIPTO_TEXT_RIGHT - x
                # Shrink a long line down to a readable 6pt; if it still does not fit, cut it at the
                # limit, so it can never run into the BILL TO block that starts at x=306.
                size = fit_size(line, "Helvetica", P1_SIZE, room, SHIPTO_MIN_SIZE)
                _text(c, x, SHIPTO_ROW_TOPS[i], clip_text(line, "Helvetica", size, room), size, page_h=P1_H)
        # Each item code is the quote number plus a suffix ("R", "-1PS", "-2PS"): the code is
        # covered and redrawn with the form's quote number and the template's own suffix.
        for x0, x1, top, text in item_codes:
            # The code sits between two rules (168.7 / 178.6 for the first row, 9.9pt apart), so the cover
            # stays inside the code's own text box (top .. top+9.3) and leaves both rules alone.
            _cover(c, (x0 - 0.6, top + 0.2, x1 + 1.0, top + 8.6), page_h=P1_H)
            _text(c, x0, top, quote_number + text[len(TEMPLATE_QUOTE):], P1_SIZE, page_h=P1_H)
        if po_number:
            _cover(c, PO_CELL_COVER, page_h=P1_H)
            # Right-aligned to the cell's digit edge, shrunk only if a longer number would run past the rules.
            _text(c, PO_DIGITS_RIGHT, PO_DIGITS_TOP, po_number, PO_DIGITS_SIZE, align="right",
                  max_width=PO_DIGITS_RIGHT - PO_DIGITS_X + 2.0, page_h=P1_H)
        if quote_number:
            _cover(c, QUOTE_LINE_COVER, page_h=P1_H)
            _text(c, CRSD_LINE_X, QUOTE_LINE_TOP, quote_number, P1_SIZE, page_h=P1_H)
        _cover(c, CRSD_COVER, page_h=P1_H)
        _text(c, CRSD_LINE_X, CRSD_LINE_TOP, overlay_text, P1_SIZE, page_h=P1_H)
        if total is not None:
            _cover(c, TOTAL_CELL_COVER, page_h=P1_H)
            _draw_page1_total(c, f"{total:,.2f}")

    overlay = _render_overlay(P1_W, P1_H, draw)
    page.merge_page(overlay.pages[0])
    return page


def generate_networld_crsd_po(fields: dict, line_items: list[dict], column_order: list[str] | None = None) -> bytes:
    cols = _columns(column_order)
    path = Path(config.TEMPLATES_DIR) / SLUG / TEMPLATE_NAME
    if not path.is_file():
        raise FileNotFoundError(f"No CRSD template PDF found for distributor '{SLUG}' ({TEMPLATE_NAME})")
    crsd = crsd_text(fields.get("crsd"))
    if not crsd:
        raise ValueError("CRSD must be a valid date (YYYY-MM-DD).")

    rows = [_Row(i) for i in line_items if i and (i.get("part_number") or i.get("description"))]
    total = sum((r.line_total for r in rows), Decimal("0"))
    pages = _paginate(rows)
    template_bytes = path.read_bytes()

    writer = PdfWriter()
    # Page 1: the Japanese PO, with the CRSD notice replaced.
    first = _crsd_page(
        template_bytes, crsd, str(fields.get("quote_number") or "").strip(), str(fields.get("po_number") or "").strip(),
        str(fields.get("ship_to_block") or ""), str(fields.get("bill_to_block") or ""), total,
    )
    writer.add_page(first)

    # Page 2 onward: Details of PO#.
    for spec in pages:
        links: list = []
        grid_bottom = spec["cursor"]
        total_top = grid_bottom
        block_dy = round(total_top - TOTAL_TOP_TEMPLATE, 1) if spec["block"] else 0.0

        def draw(c, spec=spec, grid_bottom=grid_bottom, total_top=total_top, block_dy=block_dy) -> None:
            _draw_heading(c, fields)
            if not cols.default:
                base._draw_column_header(c, cols, BAND, BAND_FILL, HEAD_TOPS, page_h=P2_H, text=_text)
            for row, top in spec["rows"]:
                _draw_row(c, row, top, cols)
            y = ROW_TOP0
            for row, top in spec["rows"]:
                y = top + row.height
                _hrule(c, y)
            if spec["block"]:
                slot_y = y
                while spec["first"] and slot_y < grid_bottom - 0.01:
                    slot_y += ROW_PITCH
                    _hrule(c, slot_y)
                _vrules(c, ROW_TOP0 - 0.5, total_top, cols.rules)
                _draw_total_row(c, total_top, total, fields, cols)
                _vrules(c, total_top, total_top + TOTAL_ROW_HEIGHT, _total_row_vrules(cols))
                _draw_value_block(c, fields, block_dy, links)
            else:
                _vrules(c, ROW_TOP0 - 0.5, grid_bottom, cols.rules)
                _hrule(c, grid_bottom)

        pieces = [(0.0, HEAD_BOTTOM, 0.0)]
        if spec["block"]:
            pieces.append((BLOCK_TOP, P2_H, block_dy))
        overlay = _render_overlay(P2_W, P2_H, draw)
        writer.add_page(_compose_details_page(template_bytes, pieces, overlay.pages[0]))
        if links:
            base.add_links(writer, links, P2_H)

    output = io.BytesIO()
    writer.write(output)
    pdf_output = output.getvalue()

    po_number = (fields.get("po_number") or "PO").strip().replace("/", "-").replace(" ", "_") or "PO"
    out_dir = Path(config.GENERATED_DIR) / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{po_number}.pdf").write_bytes(pdf_output)
    return pdf_output
