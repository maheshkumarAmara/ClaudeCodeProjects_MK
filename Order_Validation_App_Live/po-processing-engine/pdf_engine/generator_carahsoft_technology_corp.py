"""Regenerates Carahsoft Technology Corp purchase orders.

Behind Preview PDF, Generate & download PDF and Convert & Download: main._build_po_pdf
calls generate_carahsoft_technology_corp_po(fields, line_items), then sandboxes emails and strips the
text that is hidden under white boxes. Convert reuses the same PDF.

How it works: keep the sample PDF as the artwork, and per output page
  1. whiteout the old items area (and any header value being replaced),
  2. draw the new header values, the line items and the totals on top.
Rows are paginated here: a row that would pass BLOCK_BOTTOM starts a continuation page.

Rules every generator in this engine follows:
  - Coordinates are pdfplumber's top-down points (see scripts/inspect_pdf.py); drawing
    converts them (baseline = page_height - top - size * BASELINE_FACTOR).
  - A field missing from `fields` is left exactly as printed on the template; only
    keys that are present are replaced. A half-filled form never blanks the PDF.
  - Totals are recomputed from the rows; the printed total of the sample is not reused.
  - Text is Helvetica, not the sample's embedded font (a known, accepted limit).

Carahsoft specifics:
  - Two template pages: page 0 ends with the "Continued on next page..." box (used for every
    output page but the last), page 1 ends with the Comments / Total purchase order box (used
    for the last page). The header (PO number, date, "Page N", Ship To, info strip) repeats on
    both, so each header value is replaced on every page.
  - The ruled items table is whited out and its column rules redrawn.
  - After the last item the description column carries a notes block (Quote #, Support Term,
    shipping terms, END USER INFO, EU PO #) built from the form's fields; it moves to a new
    page when it does not fit under the last row.
  - A line's term prints inside the description ("Term: 36 Months"); it is appended when the
    row has a term and the description does not already say so.
"""

import io
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pypdf import PdfWriter
from reportlab.pdfgen import canvas

import config
from pdf_engine.common import FONT, FONT_BOLD, WHITE, column_boxes, fit_size, money_2dp, order_columns, untouched_order
from pdf_engine.extractor import find_template_path
from pdf_engine.generator import _fresh_page, _render_overlay
from pdf_engine.paginate import _to_decimal, wrap_text

SLUG = "Carahsoft Technology Corp"  # must equal the Distributor slug in distributors.py (validate() checks it)

FONT_SIZE = 8.0
# pdfplumber's `top` is the top of a box whose bottom sits one descent (0.207 em for
# Helvetica) below the baseline, so the baseline is this fraction of the size below `top`.
BASELINE_FACTOR = 0.793

# Which template page to start each output page from.
TEMPLATE_FIRST = 0
TEMPLATE_CONT = 0
TEMPLATE_LAST = 1  # page 2 of the sample: the totals / signature box

# Items area, top-down. A row is drawn from FIRST_TOP / CONT_TOP and must end above its
# page's bottom. ITEMS_AREA is whited out on each template page before rows are drawn.
# Measured: the table header rule is at top 319.6, the frame's bottom edge at 644.1, and the
# first row's text top is 324.8 on both pages.
FIRST_TOP = 324.8
CONT_TOP = 324.8
BLOCK_BOTTOM = 641.0
LINE_HEIGHT = 10.5
ROW_PADDING = 0.5
_AREA = (37.3, 320.4, 583.0, 643.6)
ITEMS_AREA = {
    TEMPLATE_FIRST: _AREA,
    TEMPLATE_CONT: _AREA,
    TEMPLATE_LAST: _AREA,
}

# Item columns: left edges for text, right edges for numbers. Keep a right edge about 2pt
# inside the column rule (RULES_X) so a number never touches the line.
# Measured from the sample: rules at 143.0 / 169.9 / 388.6 / 454.9 / 512.8; numbers end at
# 168.0 (line), 452.8 (qty), 510.8 (unit price) and 580.0 (extended price).
R_LINE_NO = 168.0
X_PART_NUMBER = 39.0
X_DESCRIPTION = 174.0
R_UNIT_PRICE = 510.8
R_QTY = 452.8
R_AMOUNT = 580.0
PART_NUMBER_WIDTH = 143.0 - X_PART_NUMBER - 3
# Text widths should come from the cell, not a guess: the part-number and description cells run
# up to the next column rule (or the next column's text), less a small margin. The defaults
# below are conservative and make long text wrap early (NOX's description cell is 260pt wide
# but the default gives 226pt), which makes rows taller and can add pages.
DESCRIPTION_WIDTH = 388.6 - X_DESCRIPTION - 4  # the cell runs to the rule at 388.6

# Header values to replace: (field key, centre x of the printed value, text top, size,
# cover box (x0, top, x1, bottom)). The key must match a key the parser returns. Every value
# prints centred in its cell, so a replacement is centred on the same x. The cover is a white
# box drawn first (the sample's background is white).
HEADER_VALUES = [
    ("po_number", 515.25, 89.6, 11.0, (458.0, 87.5, 566.5, 99.4)),  # box top right
    ("po_number", 89.1, 270.6, 8.0, (38.0, 270.2, 142.0, 280.2)),  # info strip
    ("po_date", 485.5, 65.3, 8.0, (458.0, 63.8, 522.4, 75.6)),
    ("vendor_number", 179.4, 270.6, 8.0, (144.5, 270.2, 215.5, 280.2)),
    ("payment_terms", 253.0, 270.6, 8.0, (217.5, 270.2, 289.2, 280.2)),
    ("reference", 537.7, 270.6, 8.0, (504.0, 270.2, 582.5, 280.2)),
]
COVER_FILL = WHITE

# Ship To block: left x, first line top, line pitch, cover box (x0, top, x1, bottom), max lines.
SHIP_TO = (339.9, 162.7, 11.1, (335.0, 158.0, 583.0, 231.5), 6)
SHIP_TO_KEY = "ship_to_block"

# "Page N" cell: the number is centred in the cell right of the "Date" cell.
PAGE_NO_CENTRE = 545.6
PAGE_NO_TOP = 65.3
PAGE_NO_COVER = (524.2, 63.8, 567.4, 75.6)

# Notes block under the last item, in the description column.
NOTES_GAP = 21.0
NOTES_PITCH = 10.5

# Totals: where the grand total prints on the last page, as a right edge and `top`,
# with the box to white out first (x0, top, x1, bottom). Set HAS_TOTAL = False below if
# the sample prints no total.
# Measured: the bold total ends at 580.0, top 651.6, inside the cell 513-583 x 644.6-667.6.
TOTAL_RIGHT = 580.0
TOTAL_TOP = 651.6
TOTAL_COVER = (514.0, 648.0, 582.4, 666.8)
TOTAL_PREFIX = ""
HAS_TOTAL = True
# True: the sample prints the total on every sheet, so each page shows the recomputed grand
# total. False: it prints it once (on the last page), so the earlier pages must have the
# sample's old total whited out or they keep a stale one after an edit.
TOTAL_ON_EVERY_PAGE = False

# Vertical rules of a ruled items table, as (x, top, bottom, line width). Whiting out the items
# area erases the rules that cross it, so they are redrawn after the whiteout. Read them with
# inspect_pdf.py --lines. Leave empty for a table with no column rules.
RULES_X: list[float] = [143.0, 169.9, 388.6, 454.9, 512.8]
RULE_WIDTH = 1.0

# The sample's "Page N of M" label, if it prints one: (right edge x, text top, size, cover box
# (x0, top, x1, bottom), cover colour). Use a cover colour that matches a shaded band behind it
# (inspect_pdf.py --sample X Y gives the rendered colour). Set to None when there is no label.
# Carahsoft prints only the page number, centred (PAGE_NO_* above), so it is drawn there.
PAGE_LABEL: tuple[float, float, float, tuple[float, float, float, float], tuple[float, float, float]] | None = None
PAGE_LABEL_TEXT = "{n}/{total}"  # "Page {n} of {total}", "{n}/{total}", ...


# --- Column order -----------------------------------------------------------------------
# The table's columns in the sample's order, keyed like the form's `column_order` (the form's
# unit_cost / total are this table's unit_price / amount). The form's terms and pct_disc have no
# column here (a term prints inside the description), so they are ignored.
COLUMNS = ("part_number", "line", "description", "qty", "unit_price", "amount")
FORM_KEYS = {"sno": "line", "part_number": "part_number", "description": "description", "qty": "qty",
             "unit_cost": "unit_price", "total": "amount"}
TABLE_X0, TABLE_X1 = 36.8, 583.5
COL_EDGES = (TABLE_X0, 143.0, 169.9, 388.6, 454.9, 512.8, TABLE_X1)  # the sample's vertical rules
# A column keeps this width wherever it moves, so the wrap widths above stay valid.
COL_WIDTHS = {key: COL_EDGES[i + 1] - COL_EDGES[i] for i, key in enumerate(COLUMNS)}
# How far inside its column a value sits: from the left edge (part number, description) or from
# the right edge (the numbers), as measured from the sample.
PART_PAD = X_PART_NUMBER - COL_EDGES[0]
DESC_PAD = X_DESCRIPTION - COL_EDGES[2]
LINE_PAD_RIGHT = COL_EDGES[2] - R_LINE_NO
QTY_PAD_RIGHT = COL_EDGES[4] - R_QTY
UNIT_PAD_RIGHT = COL_EDGES[5] - R_UNIT_PRICE
AMOUNT_PAD_RIGHT = COL_EDGES[6] - R_AMOUNT
# The column headings are template artwork. They are only redrawn when the columns have moved:
# the band is whited out inside the table frame, then each heading is centred in its column.
HEADINGS = {"part_number": "Item Number", "line": "Line", "description": "Description",
            "qty": "Qty", "unit_price": "Unit Price", "amount": "Extended Price"}
HEAD_BAND = (37.3, 297.6, 583.0, 319.1)
HEAD_TOP = 304.8
HEAD_RULES_TOP = 297.1  # the column rules start here, above the heading band


class _Columns:
    """Where each column sits for one PO. The default order is the sample's own layout (`is_default`),
    in which case nothing about the template's heading row or rules is touched."""

    def __init__(self, column_order: list[str] | None) -> None:
        requested = [FORM_KEYS[k] for k in (untouched_order(column_order) or []) if k in FORM_KEYS]
        self.order = order_columns(requested, COLUMNS)
        self.is_default = self.order == list(COLUMNS)
        self.boxes = column_boxes(TABLE_X0, COL_WIDTHS, self.order)
        # Interior rules only: the table's outer frame is template artwork and doesn't move.
        self.rules = [self.boxes[key][1] for key in self.order[:-1]]
        if self.is_default:
            self.x = {"part_number": X_PART_NUMBER, "line": R_LINE_NO, "description": X_DESCRIPTION,
                      "qty": R_QTY, "unit_price": R_UNIT_PRICE, "amount": R_AMOUNT}
        else:
            box = self.boxes
            self.x = {"part_number": box["part_number"][0] + PART_PAD, "line": box["line"][1] - LINE_PAD_RIGHT,
                      "description": box["description"][0] + DESC_PAD, "qty": box["qty"][1] - QTY_PAD_RIGHT,
                      "unit_price": box["unit_price"][1] - UNIT_PAD_RIGHT, "amount": box["amount"][1] - AMOUNT_PAD_RIGHT}


@dataclass
class _Row:
    line_no: str
    part_lines: list[str]
    description_lines: list[str]
    terms: str
    qty: str
    unit_price: str
    amount: Decimal
    height: float


@dataclass
class _PageSpec:
    template: int
    rows: list[_Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _whiteout(c: canvas.Canvas, page_height: float, x0: float, top: float, x1: float, bottom: float, fill=WHITE) -> None:
    c.saveState()
    c.setFillColorRGB(*fill)
    c.rect(x0, page_height - bottom, x1 - x0, bottom - top, fill=1, stroke=0)
    c.restoreState()


def _text(c, page_height, x, top, text, size=FONT_SIZE, bold=False, align="left") -> None:
    if not text:
        return
    c.saveState()
    c.setFont(FONT_BOLD if bold else FONT, size)
    c.setFillColorRGB(0, 0, 0)
    baseline = page_height - top - size * BASELINE_FACTOR
    if align == "right":
        c.drawRightString(x, baseline, text)
    else:
        c.drawString(x, baseline, text)
    c.restoreState()


def _replace_value(c, page_height, text, centre, top, size, cover) -> None:
    """Covers a printed value, then draws its replacement centred on the given x, shrinking
    the text if it would not fit the cover."""
    x0, cover_top, x1, cover_bottom = cover
    _whiteout(c, page_height, x0, cover_top, x1, cover_bottom, COVER_FILL)
    if not text:
        return
    size = fit_size(text, FONT, size, x1 - x0 - 2, 4.0)
    c.saveState()
    c.setFont(FONT, size)
    c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(centre, page_height - top - size * BASELINE_FACTOR, text)
    c.restoreState()


def _replace_ship_to(c, page_height, text: str) -> None:
    x, first_top, pitch, cover, max_lines = SHIP_TO
    _whiteout(c, page_height, *cover, COVER_FILL)
    lines = [line.strip() for line in text.splitlines() if line.strip()][:max_lines]
    for i, line in enumerate(lines):
        size = fit_size(line, FONT, FONT_SIZE, cover[2] - x - 2, 5.0)
        _text(c, page_height, x, first_top + pitch * i, line, size)


_TERM_RE = re.compile(r"Term:\s*\d+\s*Months?", re.IGNORECASE)


def _money(value: Decimal) -> str:
    return money_2dp(value)


def _notes_lines(fields: dict) -> list[str]:
    """The block printed under the last item: quote, support term, shipping terms and the
    END USER INFO lines. A field that is empty or absent prints no line."""

    def value(key: str) -> str:
        return str(fields.get(key) or "").strip()

    lines: list[str] = []
    if value("quote_number"):
        lines.append(f"Quote #: {value('quote_number')}")
    if value("support_term"):
        lines.append(f"Support Term: {value('support_term')}")
        if value("shipping_terms"):
            lines.append(value("shipping_terms"))
        lines.append("-")
    end_user = [value("end_user_name"), value("end_user_email"), value("end_user_phone")]
    if any(end_user) or value("end_user_po"):
        lines.append("**END USER INFO**")
        lines.extend(x for x in end_user if x)
        if value("end_user_po"):
            lines.append(f"EU PO # {value('end_user_po')}")
    return lines


def _build_rows(line_items: list[dict]) -> list[_Row]:
    rows: list[_Row] = []
    for item in line_items:
        if not (item.get("part_number") or item.get("description")):
            continue  # a blank row the user added and left empty
        qty = _to_decimal(item.get("qty"))
        unit_price = _to_decimal(item.get("unit_cost")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # The sample's extended price is qty x unit price (no discount or term multiplier).
        amount = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        part_lines = wrap_text(str(item.get("part_number") or "").strip(), PART_NUMBER_WIDTH, FONT_SIZE)
        description = str(item.get("description") or "").strip()
        term = str(item.get("terms") or "").strip()
        if term and not _TERM_RE.search(description):
            description = f"{description} Term: {term} Months".strip()
        description_lines = wrap_text(description, DESCRIPTION_WIDTH, FONT_SIZE)
        line_count = max(len(part_lines), len(description_lines))
        rows.append(
            _Row(
                line_no=str(len(rows) + 1),  # renumbered 1, 2, 3 in row order
                part_lines=part_lines,
                description_lines=description_lines,
                terms=term,
                qty=_money(qty),
                unit_price=_money(unit_price),
                amount=amount,
                height=ROW_PADDING + LINE_HEIGHT * line_count,
            )
        )
    return rows


def _paginate(rows: list[_Row], notes: list[str]) -> list[_PageSpec]:
    pages = [_PageSpec(TEMPLATE_FIRST)]
    y = FIRST_TOP
    for row in rows:
        if pages[-1].rows and y + row.height > BLOCK_BOTTOM:
            pages.append(_PageSpec(TEMPLATE_CONT))
            y = CONT_TOP
        pages[-1].rows.append(row)
        y += row.height
    if notes:
        needed = NOTES_GAP + NOTES_PITCH * len(notes)
        if pages[-1].rows and y + needed > BLOCK_BOTTOM:
            pages.append(_PageSpec(TEMPLATE_CONT))
        pages[-1].notes = notes
    # The last page carries the totals / signature box; every earlier page ends "Continued...".
    pages[-1].template = TEMPLATE_LAST
    return pages


def _draw_row(c: canvas.Canvas, page_height: float, row: _Row, top: float, cols: _Columns) -> None:
    x = cols.x
    _text(c, page_height, x["line"], top, row.line_no, align="right")
    for i, line in enumerate(row.part_lines):
        size = fit_size(line, FONT, FONT_SIZE, PART_NUMBER_WIDTH, 5.0)
        _text(c, page_height, x["part_number"], top + LINE_HEIGHT * i, line, size)
    for i, line in enumerate(row.description_lines):
        _text(c, page_height, x["description"], top + LINE_HEIGHT * i, line)
    _text(c, page_height, x["unit_price"], top, row.unit_price, align="right")
    _text(c, page_height, x["qty"], top, row.qty, align="right")
    _text(c, page_height, x["amount"], top, _money(row.amount), align="right")


def _draw_headings(c: canvas.Canvas, page_height: float, cols: _Columns) -> None:
    """Redraws the heading row in the columns' current order (the template's own headings sit
    in the default order, so they are whited out first)."""
    x0, top, x1, bottom = HEAD_BAND
    _whiteout(c, page_height, x0, top, x1, bottom)
    for key in cols.order:
        left, right = cols.boxes[key]
        text = HEADINGS[key]
        size = fit_size(text, FONT_BOLD, FONT_SIZE, right - left - 4, 5.0)
        c.saveState()
        c.setFont(FONT_BOLD, size)
        c.setFillColorRGB(0, 0, 0)
        c.drawCentredString((left + right) / 2, page_height - HEAD_TOP - size * BASELINE_FACTOR, text)
        c.restoreState()


def _draw_page(c, page_height, spec: _PageSpec, number: int, total_pages: int, fields: dict, grand_total: Decimal, cols: _Columns) -> None:
    x0, top, x1, bottom = ITEMS_AREA[spec.template]
    _whiteout(c, page_height, x0, top, x1, bottom)
    if not cols.is_default:
        _draw_headings(c, page_height, cols)

    # Every output page is a copy of a template page, and both template pages print the same
    # header, so each value is replaced on every page or the sample's old value stays.
    for key, centre, text_top, size, cover in HEADER_VALUES:
        if key in fields:
            _replace_value(c, page_height, str(fields[key] or ""), centre, text_top, size, cover)
    if SHIP_TO_KEY in fields:
        _replace_ship_to(c, page_height, str(fields[SHIP_TO_KEY] or ""))

    # The page number is centred in its cell; it always reflects the real position.
    _whiteout(c, page_height, *PAGE_NO_COVER, COVER_FILL)
    c.saveState()
    c.setFont(FONT, FONT_SIZE)
    c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(PAGE_NO_CENTRE, page_height - PAGE_NO_TOP - FONT_SIZE * BASELINE_FACTOR, str(number))
    c.restoreState()

    y = FIRST_TOP if number == 1 else CONT_TOP
    for row in spec.rows:
        _draw_row(c, page_height, row, y, cols)
        y += row.height
    if spec.notes:
        y += NOTES_GAP - ROW_PADDING
        for line in spec.notes:
            _text(c, page_height, cols.x["description"] + 1.0, y, line)
            y += NOTES_PITCH

    # The whiteout above erased any column rules inside the items area; put them back.
    c.saveState()
    c.setLineWidth(RULE_WIDTH)
    c.setStrokeColorRGB(0, 0, 0)
    if cols.is_default:
        for rule_x in RULES_X:
            c.line(rule_x, page_height - top, rule_x, page_height - bottom)
    else:
        # The heading band was whited out too, so the rules start above it. The template's old
        # rules are covered by the whiteouts; the table's frame (outside them) is untouched.
        for rule_x in cols.rules:
            c.line(rule_x, page_height - HEAD_RULES_TOP, rule_x, page_height - bottom)
    c.restoreState()

    if HAS_TOTAL and spec.template == TEMPLATE_LAST:
        _whiteout(c, page_height, *TOTAL_COVER)
        _text(c, page_height, TOTAL_RIGHT, TOTAL_TOP, f"{TOTAL_PREFIX}{_money(grand_total)}", bold=True, align="right")


def generate_carahsoft_technology_corp_po(fields: dict, line_items: list[dict], column_order: list[str] | None = None) -> bytes:
    cols = _Columns(column_order)
    path = find_template_path(SLUG)
    if path is None:
        raise FileNotFoundError(f"No template PDF found for distributor '{SLUG}'")
    pdf_bytes = path.read_bytes()

    rows = _build_rows(line_items)
    grand_total = sum((r.amount for r in rows), Decimal("0"))
    pages = _paginate(rows, _notes_lines(fields))

    writer = PdfWriter()
    for number, spec in enumerate(pages, start=1):
        page = _fresh_page(pdf_bytes, spec.template)
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        overlay = _render_overlay(
            width,
            height,
            lambda c, s=spec, n=number, h=height: _draw_page(c, h, s, n, len(pages), fields, grand_total, cols),
        )
        page.merge_page(overlay.pages[0])
        writer.add_page(page)

    output = io.BytesIO()
    writer.write(output)
    pdf_output = output.getvalue()

    # Keep a copy under data/generated/<slug>/ (git-ignored), named after the PO number.
    po_number = (fields.get("po_number") or "PO").strip().replace("/", "-").replace(" ", "_") or "PO"
    out_dir = Path(config.GENERATED_DIR) / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{po_number}.pdf").write_bytes(pdf_output)

    return pdf_output
