"""Regenerates Networld Corporation purchase-order detail sheets.

The template is a single landscape page: a heading ("Details of PO# <number>" on a
green band, "Quote #: <quote>", and a NETWORLD logo made of three stacked image
slices), a ruled items grid (Product Code | Product Description | Qty | Term | Net
Total Price) with a Total row, then label / value lines (Incoterms, Payment Terms,
notification and billing emails, End User Name / PO#, forwarder details, ship-to
address, mail address).

This module treats the template as pieces cut out of the page -- the head (logo,
heading, grid header), the label / value block -- and draws the items grid itself,
so the table can hold any number of rows. Values are replaced by covering the old
text with a white box and redrawing the new text.

Behaviors worth knowing:
  - The grid is dynamic. A PO of up to 8 rows prints the template's own grid (the
    8th row blank, the Total row below it). More rows grow the grid on the same page
    while the label / value block still fits under it; beyond that the grid
    continues on extra pages that repeat the heading, the logo and the column
    header, and the Total row and the label / value block go on the last page only.
  - Net Price is recomputed: qty x unit_cost, where unit_cost is the whole-term
    price per unit (the parser derives it as printed Net Price / qty). "terms" is a
    display value and does not enter the maths. An unedited loaded row reprints its
    original printed "amount" exactly (see "amount_basis"); editing its qty, unit
    cost or terms recomputes it. The Total is always the sum of the rows. A row's
    "% disc." (if any) reduces its Net Price.
  - Values print as "$1,234.56".
  - Blue values (emails, end user, PO#) are underlined like the template's, and
    email addresses are rebuilt as mailto links (the template has none). The
    template text is Arial; this module draws Helvetica. The Japanese comma
    (U+3001, in the End User PO# list) is not in Helvetica, so a character the
    standard font cannot draw is taken from a system CJK-capable TTF when one is
    installed; if none is, that character is dropped.
  - The original text of covered or clipped-away pieces stays in the PDF's hidden
    text layer.
"""

import io
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pypdf import PageObject, PdfReader, PdfWriter, Transformation
from pypdf.generic import DecodedStreamObject, NameObject
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

import config
from pdf_engine.common import add_links
from pdf_engine.extractor import find_template_path
from pdf_engine.generator import _render_overlay
from pdf_engine.paginate import _to_decimal, wrap_text
from sandbox_email import sandbox_text

SLUG = "Networld Corporation"

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
BLACK = (0.0, 0.0, 0.0)
WHITE = (1.0, 1.0, 1.0)
BLUE = (0.02, 0.388, 0.757)
RED = (1.0, 0.0, 0.0)
MIN_FONT_SIZE = 4.0
TEXT_SIZE = 9.35
# Arial's baseline sits 0.789 x its size below the character box's top edge
# (measured from the template: 7.38pt at 9.35pt). The blue value lines were YuGothic,
# whose box is offset differently (0.698 x size); their tops below carry the +0.65pt
# that puts Helvetica on the same baseline.
BASELINE_FACTOR = 0.789

PAGE_W, PAGE_H = 842.0, 595.22

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")

# --- Template geometry (top-origin y) ------------------------------------------
GRID_LEFT, GRID_RIGHT = 23.5, 730.7
# Vertical rules inside the grid: (x, width). The outer borders are the first/last.
_VRULES = (
    (22.7, 0.8), (178.4, 0.9), (547.2, 0.8), (590.9, 0.8), (642.4, 0.8), (729.8, 0.9),
)
HEAD_BOTTOM = 146.0  # logo, heading, teal column-header band (bottom rule included)
CONT_HEAD_BOTTOM = HEAD_BOTTOM
# The template's item rows are bounded by horizontal rules 11.52pt apart, the first
# at y=145.2 (the header band's bottom rule), each 0.83pt thick; the 8th row's bottom
# rule is the Total row's top rule at 237.4 (145.2 + 8 x 11.52 = 237.36).
RULE_ORIGIN = 145.2
ROW_PITCH = 11.52
ROW_TOP0 = RULE_ORIGIN  # top of the first item row = the rule above it
ROW_TEXT_OFFSET = 2.2  # item text top below its row's top rule (147.4 - 145.2)
TEMPLATE_ROWS = 8
RULE_THIN = 0.83
# The Total row: rule to rule, 237.4 -> 260.5 in the template.
TOTAL_ROW_HEIGHT = 260.5 - 237.4
TOTAL_TEXT_OFFSET = 8.1  # total text top below the Total row's top rule (245.5 - 237.4)
# Gap between the Total row's bottom rule (260.5) and the label / value block (clipped
# from BLOCK_TOP = 280.0) in the template. A PO the size of the sample therefore gets
# a block offset of exactly 0 (ROW_TOP0 + 8 x ROW_PITCH is the Total row's top rule).
BLOCK_GAP = 280.0 - 260.5
TEMPLATE_TOTAL_TOP = 237.4  # the template's own Total row top rule

# Columns.
CODE_X = 24.8
DESC_X = 180.0
QTY_CENTER = (547.2 + 590.9) / 2
TERM_CENTER = (590.9 + 642.4) / 2
AMOUNT_RIGHT = 725.6
# The 7th sample description (the longest) is 330pt in Arial; Helvetica runs a touch
# wider, so leave the column's whole width (less a small pad) rather than wrapping a
# line the template prints on one.
DESC_ROOM = 547.2 - DESC_X - 1.5
CODE_ROOM = 178.4 - CODE_X - 3.0

# --- Label / value block ---------------------------------------------------------
BLOCK_TOP = 280.0  # clip: everything from here down is the label / value block
VALUE_X = 180.0
LABEL_X = 24.8
BLOCK_BOTTOM_PAD = 24.0  # keep the block this far above the page's bottom edge
LAST_BLOCK_LINE_BOTTOM = 534.0  # the template's lowest block line ("mail address") ends here
# Each line: (key, text top in the template, color, underline, bold-label?). Tops are
# measured; the value is covered from x=178 to the page's right text edge.
_VALUE_LINES = {
    "incoterms": (288.8, BLACK, False),
    "payment_terms": (302.3, BLACK, False),
    # The blue lines were YuGothic, whose character box sits 0.65pt lower than Arial's
    # on the same baseline (316.6 vs 315.9); these tops are Arial-equivalent, i.e. the
    # label's top on the same line, so Helvetica lands on the template's baseline.
    "order_notification_email": (315.9, BLUE, True),
    "billing_email": (329.5, BLUE, True),
    "end_user_name": (343.1, BLUE, True),
    "end_user_po": (356.7, BLUE, True),
    "forwarder_company": (397.6, BLACK, False),
    "forwarder_phone": (409.1, BLACK, False),
    "forwarder_fax": (420.7, BLACK, False),
    "forwarder_contact_1": (432.2, BLACK, False),
    "forwarder_contact_2": (443.7, BLACK, False),
    "ship_to_mail": (524.6, BLACK, False),
}
SHIP_TO_FIRST_TOP = 466.7
SHIP_TO_PITCH = 11.55
SHIP_TO_LINES = 5  # the template's ship-to block has 5 lines (466.7 .. 513.2)
VALUE_COVER_RIGHT = 760.0
BLOCK_HEIGHT = 535.0 - BLOCK_TOP  # clip height of the block (to the last text line)
BLOCK_CLIP_BOTTOM = PAGE_H  # the template has nothing below the block

# --- Heading -------------------------------------------------------------------
PO_NUMBER_BOX = (179.5, 67.0, 546.5, 85.5)  # inside the green band
PO_NUMBER_RIGHT = 545.2
PO_NUMBER_TOP = 72.2
GREEN = (0.886, 0.937, 0.855)
QUOTE_BOX = (179.0, 91.0, 420.0, 104.0)
QUOTE_X = 180.6
QUOTE_TOP = 92.6

# --- Fonts -----------------------------------------------------------------------
_CJK_CANDIDATES = (
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
)
_CJK_NAME = "NetworldCJK"
_cjk_ready: bool | None = None


def _cjk_font() -> str | None:
    """Registers (once) a system TTF that has CJK punctuation; None if there is none."""
    global _cjk_ready
    if _cjk_ready is None:
        _cjk_ready = False
        for candidate in _CJK_CANDIDATES:
            if Path(candidate).is_file():
                try:
                    pdfmetrics.registerFont(TTFont(_CJK_NAME, candidate))
                    _cjk_ready = True
                    break
                except Exception:  # an unreadable font just means no CJK fallback
                    continue
    return _CJK_NAME if _cjk_ready else None


def _is_latin1(ch: str) -> bool:
    try:
        ch.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def _runs(text: str, font: str) -> list[tuple[str, str]]:
    """Splits text into (font, run) pieces: Helvetica for what it can draw, the CJK
    TTF for the rest (or nothing, when no CJK font is installed)."""
    out: list[tuple[str, str]] = []
    cjk = _cjk_font()
    for ch in text:
        use = font if _is_latin1(ch) else cjk
        if use is None:
            continue
        if out and out[-1][0] == use:
            out[-1] = (use, out[-1][1] + ch)
        else:
            out.append((use, ch))
    return out


def _width(text: str, font: str, size: float) -> float:
    return sum(stringWidth(run, f, size) for f, run in _runs(text, font))


# --- Drawing helpers ---------------------------------------------------------------
def _cover(c: canvas.Canvas, box: tuple[float, float, float, float], dy: float = 0.0, fill=WHITE) -> None:
    left, top, right, bottom = box
    c.saveState()
    c.setFillColorRGB(*fill)
    c.rect(left, PAGE_H - bottom - dy, right - left, bottom - top, fill=1, stroke=0)
    c.restoreState()


def _fit(text: str, font: str, size: float, max_width: float) -> float:
    while size > MIN_FONT_SIZE and _width(text, font, size) > max_width:
        size -= 0.1
    return size


def _text(
    c: canvas.Canvas,
    x: float,
    top: float,
    text: str,
    size: float = TEXT_SIZE,
    *,
    bold: bool = False,
    align: str = "left",
    color=BLACK,
    underline: bool = False,
    max_width: float | None = None,
    links: list | None = None,
) -> None:
    if not text:
        return
    font = FONT_BOLD if bold else FONT
    if max_width is not None:
        size = _fit(text, font, size, max_width)
    baseline = PAGE_H - top - size * BASELINE_FACTOR
    width = _width(text, font, size)
    if align == "right":
        left = x - width
    elif align == "center":
        left = x - width / 2
    else:
        left = x
    c.saveState()
    c.setFillColorRGB(*color)
    cursor = left
    for run_font, run in _runs(text, font):
        c.setFont(run_font, size)
        c.drawString(cursor, baseline, run)
        cursor += stringWidth(run, run_font, size)
    if underline:
        c.setStrokeColorRGB(*color)
        # The template's underline rects sit ~1.0pt below the baseline (0.5pt thick), but
        # Helvetica's descenders (g, p, y) reach lower than YuGothic's and would be cut by
        # a line that close, so sit a little lower.
        c.setLineWidth(0.5)
        c.line(left, baseline - 1.6, left + width, baseline - 1.6)
    c.restoreState()
    if links is not None:
        for match in _EMAIL_RE.finditer(text):
            start = left + _width(text[: match.start()], font, size)
            end = start + _width(match.group(0), font, size)
            links.append((start, top, end, top + size, f"mailto:{match.group(0)}"))


def _money(value: Decimal) -> str:
    return "$" + f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def _qty_text(value: Decimal) -> str:
    return f"{int(value)}" if value == value.to_integral_value() else f"{value.normalize():f}"


# --- Cutting pieces out of the template -------------------------------------------
def _clip_piece(template_bytes: bytes, top: float, bottom: float) -> PageObject:
    """A fresh copy of the template page limited to the horizontal band top..bottom
    (top-origin), with the template's own link annotations removed."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(template_bytes)))
    page = writer.pages[0]
    data = page.get_contents().get_data()
    stream = DecodedStreamObject()
    stream.set_data(f"q 0 {PAGE_H - bottom:.3f} {PAGE_W:.3f} {bottom - top:.3f} re W n\n".encode() + data + b"\nQ")
    page[NameObject("/Contents")] = writer._add_object(stream)
    if "/Annots" in page:
        del page["/Annots"]
    return page


def _compose_page(template_bytes: bytes, pieces: list[tuple[float, float, float]], overlay_page) -> PageObject:
    """A blank page with each (clip top, clip bottom, dy-down) piece of the template
    placed on it, then the drawn overlay on top."""
    page = PageObject.create_blank_page(width=PAGE_W, height=PAGE_H)
    for top, bottom, dy_down in pieces:
        piece = _clip_piece(template_bytes, top, bottom)
        page.merge_transformed_page(piece, Transformation().translate(0, -dy_down))
    page.merge_page(overlay_page)
    return page


def _add_links(writer: PdfWriter, links: list) -> None:
    add_links(writer, links, PAGE_H)


# --- Rows ---------------------------------------------------------------------------
class _Row:
    def __init__(self, item: dict) -> None:
        self.item = item
        self.code = str(item.get("part_number") or "")
        self.description = str(item.get("description") or "")
        self.qty = _to_decimal(item.get("qty"))
        self.unit_cost = _to_decimal(item.get("unit_cost"))
        self.terms = str(item.get("terms") or "").strip()
        pct = _to_decimal(item.get("pct_disc"))
        basis = f"{item.get('qty', '')}|{item.get('unit_cost', '')}|{item.get('terms', '')}"
        if item.get("amount") not in (None, "") and item.get("amount_basis") == basis and not pct:
            amount = _to_decimal(item["amount"])  # untouched loaded row: reprint its own figure
        else:
            amount = self.qty * self.unit_cost * (Decimal("1") - pct / Decimal("100"))
        self.amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.desc_lines = wrap_text(self.description, DESC_ROOM, TEXT_SIZE) if self.description else [""]

    @property
    def height(self) -> float:
        return ROW_PITCH * max(1, len(self.desc_lines))


def _draw_row(c: canvas.Canvas, row: _Row, top: float) -> None:
    text_top = top + ROW_TEXT_OFFSET
    _text(c, CODE_X, text_top, row.code, TEXT_SIZE, max_width=CODE_ROOM)
    for i, line in enumerate(row.desc_lines):
        _text(c, DESC_X, text_top + ROW_PITCH * i, line, TEXT_SIZE)
    _text(c, QTY_CENTER, text_top, _qty_text(row.qty), TEXT_SIZE, align="center")
    _text(c, TERM_CENTER, text_top, row.terms, TEXT_SIZE, align="center")
    _text(c, AMOUNT_RIGHT, text_top, _money(row.amount), TEXT_SIZE, align="right")


def _draw_hrule(c: canvas.Canvas, y_top: float, thickness: float = RULE_THIN) -> None:
    c.saveState()
    c.setFillColorRGB(*BLACK)
    c.rect(GRID_LEFT, PAGE_H - y_top - thickness, GRID_RIGHT - GRID_LEFT, thickness, fill=1, stroke=0)
    c.restoreState()


def _draw_vrules(c: canvas.Canvas, y_top: float, y_bottom: float, columns: tuple[int, ...] | None = None) -> None:
    c.saveState()
    c.setFillColorRGB(*BLACK)
    for i, (x, width) in enumerate(_VRULES):
        c.rect(x, PAGE_H - y_bottom, width, y_bottom - y_top, fill=1, stroke=0)
    c.restoreState()


# --- Pagination ---------------------------------------------------------------------
PAGE_BOTTOM = 560.0  # lowest a page's content may reach


def _paginate(rows: list[_Row]) -> list[dict]:
    """Page specs: {"rows": [(row, top)], "first": bool, "cursor": y after the last
    row, "block": bool (Total row + label/value block on this page)}.

    Page 1 keeps the template's 8 row slots (blank rows included). The Total row and
    the label / value block (about 270pt together) go under the last row if they fit
    above PAGE_BOTTOM; otherwise a last row moves to a final page with them, so they
    never sit under an empty grid."""
    # Height from the Total row's top rule to the label / value block's last text line
    # (the template's "mail address" line ends at 534.0), plus the page's bottom margin.
    tail = (LAST_BLOCK_LINE_BOTTOM - TEMPLATE_TOTAL_TOP) + BLOCK_BOTTOM_PAD
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

    # Pad page 1 to the template's 8 slots only when it is the last page.
    min_end = ROW_TOP0 + ROW_PITCH * TEMPLATE_ROWS if page["first"] else page["cursor"]
    end = max(page["cursor"], min_end)
    if end + tail <= PAGE_H or (not rows and page["first"]):
        page["block"] = True
        page["cursor"] = end
        return pages

    last = new_page(False)
    if len(page["rows"]) > 1:
        moved, _ = page["rows"].pop()
        page["cursor"] -= moved.height
        last["rows"].append((moved, last["cursor"]))
        last["cursor"] += moved.height
    last["block"] = True
    return pages


# --- Page drawing ---------------------------------------------------------------------
def _draw_heading(c: canvas.Canvas, fields: dict) -> None:
    _cover(c, PO_NUMBER_BOX, fill=GREEN)
    _text(c, PO_NUMBER_RIGHT, PO_NUMBER_TOP, str(fields.get("po_number") or ""), TEXT_SIZE, align="right")
    _cover(c, QUOTE_BOX)
    _text(c, QUOTE_X, QUOTE_TOP, str(fields.get("quote_number") or ""), TEXT_SIZE)


def _draw_value_block(c: canvas.Canvas, fields: dict, dy: float, links: list) -> None:
    for key, (top, color, underline) in _VALUE_LINES.items():
        _cover(c, (VALUE_X - 2.0, top - 0.6, VALUE_COVER_RIGHT, top + 12.0), dy)
        _text(
            c, VALUE_X, top + dy, str(fields.get(key) or ""), TEXT_SIZE,
            color=color, underline=underline, max_width=VALUE_COVER_RIGHT - VALUE_X - 6.0, links=links,
        )
    # Ship-to block: free-length lines (up to the template's 5), then the mail address below it.
    _cover(c, (VALUE_X - 2.0, SHIP_TO_FIRST_TOP - 0.6, VALUE_COVER_RIGHT, SHIP_TO_FIRST_TOP + SHIP_TO_LINES * SHIP_TO_PITCH), dy)
    for i, line in enumerate(str(fields.get("ship_to_block") or "").split("\n")[:SHIP_TO_LINES]):
        _text(c, VALUE_X, SHIP_TO_FIRST_TOP + SHIP_TO_PITCH * i + dy, line, TEXT_SIZE, max_width=VALUE_COVER_RIGHT - VALUE_X - 6.0)


def _draw_total_row(c: canvas.Canvas, top: float, total: Decimal) -> None:
    """The Total row: a taller row closing the grid. top = its top rule's y."""
    bottom = top + TOTAL_ROW_HEIGHT
    _draw_hrule(c, top)
    _draw_hrule(c, bottom)
    _text(c, 640.0, top + TOTAL_TEXT_OFFSET, "Total", TEXT_SIZE, bold=True, align="right")
    _text(c, AMOUNT_RIGHT, top + TOTAL_TEXT_OFFSET, _money(total), TEXT_SIZE, bold=True, align="right")


def generate_networld_corporation_po(fields: dict, line_items: list[dict]) -> bytes:
    path = find_template_path(SLUG)
    if path is None:
        raise FileNotFoundError(f"No template PDF found for distributor '{SLUG}'")

    rows = [_Row(i) for i in line_items if i and (i.get("part_number") or i.get("description"))]
    total = sum((r.amount for r in rows), Decimal("0"))
    pages = _paginate(rows)

    template_bytes = path.read_bytes()
    writer = PdfWriter()
    for number, spec in enumerate(pages, start=1):
        links: list = []
        grid_top = ROW_TOP0
        grid_bottom = spec["cursor"]
        total_top = grid_bottom
        # The block keeps its template distance below the Total row, so it moves by
        # however far the Total row sits from the template's own (237.4). A PO the size
        # of the sample gets dy == 0 (rounded, to absorb 8 x 11.52 = 237.36).
        block_dy = round(total_top - TEMPLATE_TOTAL_TOP, 1) if spec["block"] else 0.0

        def draw(c: canvas.Canvas, spec=spec, number=number, grid_bottom=grid_bottom, total_top=total_top, block_dy=block_dy) -> None:
            if spec["first"]:
                _draw_heading(c, fields)
            for row, top in spec["rows"]:
                _draw_row(c, row, top)
            # Row separators and the grid's closing rule.
            y = ROW_TOP0
            for row, top in spec["rows"]:
                y = top + row.height
                _draw_hrule(c, y)
            if spec["block"]:
                # Fill out the template's 8 slots with blank rows on a first page.
                slot_y = y
                while spec["first"] and slot_y < grid_bottom - 0.01:
                    slot_y += ROW_PITCH
                    _draw_hrule(c, slot_y)
                _draw_vrules(c, ROW_TOP0 - 0.5, total_top)
                _draw_total_row(c, total_top, total)
                _draw_vrules(c, total_top, total_top + TOTAL_ROW_HEIGHT)
                _draw_value_block(c, fields, block_dy, links)
            else:
                _draw_vrules(c, ROW_TOP0 - 0.5, grid_bottom)
                _draw_hrule(c, grid_bottom)

        pieces: list[tuple[float, float, float]] = [(0.0, HEAD_BOTTOM, 0.0)]
        if spec["block"]:
            pieces.append((BLOCK_TOP, PAGE_H, block_dy))

        overlay = _render_overlay(PAGE_W, PAGE_H, draw)
        writer.add_page(_compose_page(template_bytes, pieces, overlay.pages[0]))
        _add_links(writer, links)

    output = io.BytesIO()
    writer.write(output)
    pdf_output = output.getvalue()

    po_number = (fields.get("po_number") or "PO").strip().replace("/", "-").replace(" ", "_") or "PO"
    out_dir = Path(config.GENERATED_DIR) / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{po_number}.pdf").write_bytes(pdf_output)

    return pdf_output
