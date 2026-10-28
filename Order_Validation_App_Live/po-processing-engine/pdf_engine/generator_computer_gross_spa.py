"""Regenerates Computer Gross spa purchase orders.

The template is a one-page, spreadsheet-style form: a ruled grid of label cells
(grey) and value cells (white), with a 12-row items table. This module treats
the template as three pieces cut out of that page -- the head (everything down
to the table's column header), the column-header band, and the tail (TOTAL,
Shipping, IOR block and the closing sentence) -- and builds each output page by
placing them around an items grid it draws itself, so the table can hold any
number of rows. Values are replaced by covering the old text with a white box
that stays inside its cell (so the grid lines survive) and redrawing the new
text.

Behaviors worth knowing:
  - The items table is dynamic. A PO with up to 12 lines prints exactly the
    template's 12-row table (unused rows stay blank). More lines grow the table
    in place for as long as the TOTAL/Shipping/IOR block still fits on the page;
    beyond that the table continues on extra pages that repeat the column
    header, and the TOTAL/Shipping/IOR block goes on the last page only. When a
    PO spans several pages each one is labelled "PO <number> - Page i of n".
  - The right-hand "Total" column prints "$0,00" on every blank row, as the
    sample does.
  - Clickable mailto links are rebuilt for underlined (blue) email text, so a
    link always points at the address that is printed -- the template's own
    links are dropped, since they would still open the original addresses.
  - A row's "terms" value goes in the TERM column; description text is clipped
    to its cell width, as the sample's own descriptions are.
  - Numbers print the way the sample does: price in EU style ("1294,8" is kept
    as typed; a row's line total is "$13.520,00"), and the TOTAL is recomputed
    from the rows.
  - Fields missing from the request keep the value that is already on the
    template.
  - Text is drawn in Helvetica at the template's size, not its embedded Tahoma.
"""

import io
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pypdf import PageObject, PdfReader, PdfWriter, Transformation
from pypdf.generic import DecodedStreamObject, NameObject
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

import config
from pdf_engine.common import add_links, clip_text, fit_size
from pdf_engine.extractor import find_template_path
from pdf_engine.generator import _fresh_page, _render_overlay
from pdf_engine.paginate import _to_decimal

SLUG = "Computer Gross spa"

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
# pdfplumber's `top` is the top of a box whose bottom sits one descent
# (0.207 em for Helvetica) below the baseline.
BASELINE_FACTOR = 0.793
MIN_FONT_SIZE = 3.0

WHITE = (1.0, 1.0, 1.0)
BLUE = (0.02, 0.388, 0.757)
BLACK = (0.0, 0.0, 0.0)
# Pad each cover inside its cell by this much, so it never reaches a border.
INSET = 0.8

# --- Single-value cells: key -> (text x, text top, cell left, cell right, cell top, cell bottom, size, bold, align, color)
# `align` "center" centers on the cell; the others anchor at text x.
_VALUE_CELLS = {
    "po_number": (123.5, 98.5, 122.7, 265.2, 95.1, 103.8, 5.04, True, "left", BLACK),
    "po_date": (123.5, 106.9, 122.7, 265.2, 104.1, 112.6, 5.04, True, "left", BLACK),
    "payment_terms": (123.4, 115.7, 122.7, 265.2, 112.8, 121.3, 5.04, False, "left", BLACK),
    "bill_to": (123.4, 123.2, 122.7, 265.2, 121.6, 130.1, 5.04, False, "left", BLACK),
    "license_email": (123.4, 132.0, 122.7, 265.2, 130.3, 138.9, 5.04, False, "left", BLACK),
    "quote_number": (0, 246.8, 122.7, 654.3, 244.0, 256.0, 8.04, True, "center", BLACK),
    "end_user_po": (0, 258.9, 122.7, 654.3, 256.1, 268.1, 8.04, True, "center", BLACK),
    "shipping_method": (0, 387.2, 122.7, 654.3, 382.5, 397.5, 6.96, False, "center", BLACK),
    "ior_name": (123.4, 406.1, 122.7, 654.3, 404.5, 411.4, 5.04, False, "left", BLACK),
    "ior_street": (123.4, 413.1, 122.7, 654.3, 411.7, 418.4, 5.04, False, "left", BLACK),
    "ior_city": (123.4, 420.1, 122.7, 654.3, 418.7, 425.4, 5.04, False, "left", BLACK),
    "ior_state": (123.4, 427.0, 122.7, 654.3, 425.6, 432.3, 5.04, False, "left", BLACK),
    "ior_zip": (123.4, 434.0, 122.7, 654.3, 432.6, 439.3, 5.04, False, "left", BLACK),
    "ior_country": (123.4, 440.9, 122.7, 654.3, 439.5, 446.3, 5.04, False, "left", BLACK),
    "ior_contact": (123.4, 447.6, 122.7, 654.3, 446.5, 453.2, 5.04, False, "left", BLUE),
    "vat_number": (123.4, 461.5, 122.7, 654.3, 453.5, 473.5, 5.04, False, "left", BLACK),
}

# Invoice emails wrap onto two printed lines inside one tall cell.
_INVOICE_CELL = (123.4, 122.7, 265.2, 139.1, 152.5)
_INVOICE_TOPS = (140.7, 147.2)

# --- The four-column details block ---------------------------------------
# column key -> (cell left, cell right, alignment). The End User column's text
# is centered in the sample; the others are left-aligned.
_DETAIL_COLUMNS = {
    "distributor": (122.2, 265.0, "left"),
    "reseller": (265.9, 362.4, "left"),
    "end_user": (363.3, 460.0, "center"),
    "ship_to": (460.9, 554.4, "left"),
}
# row key -> (cell top, cell bottom, text top)
_DETAIL_ROWS = {
    "company": (184.5, 192.0, 187.0),
    "address": (192.4, 198.7, 193.5),
    "city": (199.0, 205.5, 200.2),
    "postal_code": (205.8, 212.2, 206.8),
    "contact": (212.5, 218.9, 213.5),
    "phone": (219.2, 225.7, 220.7),
    "email": (226.0, 233.3, 227.9),  # bottom edge is the table's heavier closing rule
}
_DETAIL_FONT_SIZE = 5.04
_DETAIL_PAD = 1.2

# --- Items table -----------------------------------------------------------
# The template prints 12 rows; a PO with fewer lines still gets 12 (the unused
# ones stay blank), a PO with more grows the table (see _paginate).
ITEM_ROWS = 12
# Top edges of the horizontal rules around each of the 12 rows (the 13th is the
# table's bottom border), read from the template. Rows are anchored to these
# instead of a fixed pitch: the pitch is not exactly uniform. Rows past the 12th
# continue at TEXT_PITCH.
ROW_RULE_TOPS = (285.7, 292.6, 299.3, 306.1, 312.8, 319.5, 326.2, 333.0, 339.7, 346.4, 353.1, 359.8, 367.5)
# Text top of row 0 and the pitch between rows' text, measured from the sample.
FIRST_TEXT_TOP = 287.5
TEXT_PITCH = 6.73

# --- Pieces cut out of the template page (all y values are top-origin) ----
# head: everything down to and including the column-header band's bottom rule.
HEAD_BOTTOM = 286.61
# band: the grey column-header row (repeated at the top of continuation pages).
BAND_CLIP_TOP = 278.4
BAND_RULE_TOP = 278.69  # top edge of the band's own top rule
# tail: from just above the table's closing rule to the page bottom (TOTAL cell,
# Shipping, IOR block, closing sentence). The 12th blank row's own text ends at
# 367.23, so clipping at 367.4 leaves it out.
TAIL_CLIP_TOP = 367.4
TAIL_RULE_TOP = ROW_RULE_TOPS[ITEM_ROWS]
TAIL_HEIGHT = 540.5 - TAIL_RULE_TOP  # closing rule down to the closing sentence's bottom
# Lowest y a table may reach on a page with no tail, and lowest the tail may reach.
BODY_BOTTOM = 580.0
TAIL_LIMIT = 585.0
# Where a continuation page's column-header band starts.
CONT_BAND_TOP = 60.0
# Vertical rules: (x, width). The outer borders are heavier than the inner ones.
_VRULES = (
    (28.32, 0.96), (121.94, 0.48), (265.49, 0.48), (334.73, 0.48), (362.93, 0.48),
    (406.27, 0.48), (460.51, 0.48), (554.86, 0.48), (654.34, 0.96),
)
_HRULE_LEFT, _HRULE_RIGHT = 29.3, 654.3
_HRULE_THIN, _HRULE_HEAVY = 0.48, 0.96
# Cell edges (left, right) from the sample's vertical rules.
_COL_EDGES = {
    "part_number": (28.9, 121.7),
    "description": (121.9, 265.2),
    "qty": (265.5, 334.5),
    "term": (334.7, 362.7),
    "asset_serial": (362.9, 406.0),
    "start_date": (406.3, 460.3),
    "price": (460.5, 554.6),
    "total": (554.9, 654.3),
}
_TEXT_SIZE = 5.04
_DESCRIPTION_SIZE = 3.96  # descriptions print smaller than the other columns
_TEXT_PAD = 1.4

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")

# TOTAL cell (below the table, right column).
_TOTAL_CELL = (555.6, 654.3, 368.5, 375.4)
_TOTAL_TEXT_TOP = 369.4


def _fit(text: str, font: str, size: float, max_width: float) -> float:
    return fit_size(text, font, size, max_width, MIN_FONT_SIZE)


def _clip(text: str, font: str, size: float, max_width: float) -> str:
    return clip_text(text, font, size, max_width)


def _cover(c: canvas.Canvas, page_height: float, left: float, top: float, right: float, bottom: float, fill=WHITE) -> None:
    c.saveState()
    c.setFillColorRGB(*fill)
    c.rect(left, page_height - bottom, right - left, bottom - top, fill=1, stroke=0)
    c.restoreState()


def _draw_text(
    c: canvas.Canvas,
    page_height: float,
    text: str,
    x: float,
    top: float,
    size: float,
    *,
    bold: bool = False,
    align: str = "left",
    color=BLACK,
    underline: bool = False,
    links: list | None = None,
) -> None:
    """`links`, when given, collects a (x0, top, x1, bottom, "mailto:...") entry
    (top-origin page coordinates) for every email address in the drawn text."""
    if not text:
        return
    font = FONT_BOLD if bold else FONT
    c.saveState()
    c.setFont(font, size)
    c.setFillColorRGB(*color)
    baseline = page_height - top - size * BASELINE_FACTOR
    if align == "right":
        c.drawRightString(x, baseline, text)
        width = stringWidth(text, font, size)
        underline_x = x - width
    elif align == "center":
        c.drawCentredString(x, baseline, text)
        width = stringWidth(text, font, size)
        underline_x = x - width / 2
    else:
        c.drawString(x, baseline, text)
        width = stringWidth(text, font, size)
        underline_x = x
    if underline:
        c.setStrokeColorRGB(*color)
        c.setLineWidth(0.3)
        c.line(underline_x, baseline - 0.5, underline_x + width, baseline - 0.5)
    c.restoreState()
    if links is not None:
        for match in _EMAIL_RE.finditer(text):
            left = underline_x + stringWidth(text[: match.start()], font, size)
            right = left + stringWidth(match.group(0), font, size)
            links.append((left, top, right, top + size, f"mailto:{match.group(0)}"))


def _replace_cell(
    c: canvas.Canvas,
    page_height: float,
    text: str,
    *,
    x: float,
    top: float,
    cell: tuple[float, float, float, float],
    size: float,
    bold: bool = False,
    align: str = "left",
    color=BLACK,
    links: list | None = None,
) -> None:
    """Covers a cell's old value (inside its borders) and draws the new one,
    shrinking the text to the cell width rather than letting it cross a border.

    The cover extends to the bottom border (not just inside the text row)
    because linked cells carry a separate blue underline rectangle that sits
    below the text and would otherwise show through as a stray mark."""
    left, right, cell_top, cell_bottom = cell
    _cover(c, page_height, left + INSET, cell_top + INSET, right - INSET, cell_bottom)
    font = FONT_BOLD if bold else FONT
    room = right - left - 2 * _TEXT_PAD
    drawn_size = _fit(text, font, size, room)
    text = _clip(text, font, drawn_size, room)
    anchor = (left + right) / 2 if align == "center" else x
    _draw_text(
        c,
        page_height,
        text,
        anchor,
        top,
        drawn_size,
        bold=bold,
        align=align,
        color=color,
        underline=color == BLUE,
        links=links,
    )


def _format_price(value: Decimal) -> str:
    """Up to two decimals, no grouping, with a decimal comma: "1294,8", "52,00"."""
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = f"{quantized:.2f}".replace(".", ",")
    return text


def _format_money(value: Decimal) -> str:
    """"$13.520,00": dollar sign, "." for thousands, "," for the decimal."""
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole, _, fraction = f"{abs(quantized):.2f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    sign = "-" if quantized < 0 else ""
    return f"{sign}${grouped},{fraction}"


def _draw_header_values(
    c: canvas.Canvas,
    page_height: float,
    fields: dict,
    keys: set | None = None,
    links: list | None = None,
    dy: float = 0.0,
) -> None:
    """Draws the single-value cells. `keys` limits which ones (head vs tail);
    `dy` moves them down the page (the tail block sits under a table whose
    length varies)."""
    for key, (x, top, left, right, cell_top, cell_bottom, size, bold, align, color) in _VALUE_CELLS.items():
        if key not in fields or (keys is not None and key not in keys):
            continue
        _replace_cell(
            c,
            page_height,
            str(fields[key] or ""),
            x=x,
            top=top + dy,
            cell=(left, right, cell_top + dy, cell_bottom + dy),
            size=size,
            bold=bold,
            align=align,
            color=color,
            links=links,
        )

    if "invoice_email" in fields and (keys is None or "invoice_email" in keys):
        x, left, right, cell_top, cell_bottom = _INVOICE_CELL
        text = str(fields["invoice_email"] or "")
        # Cover down to the bottom rule: the original's descenders ("g" in
        # "rubriklog") reach below the text row and would peek out otherwise.
        _cover(c, page_height, left + INSET, cell_top + INSET, right - INSET, cell_bottom)
        # Split at the first " + " so the two printed lines keep the sample's shape.
        first, plus, rest = text.partition(" + ")
        lines = [f"{first} +", rest] if plus else [first]
        for line, top in zip(lines, _INVOICE_TOPS):
            size = _fit(line, FONT, 5.04, right - left - 2 * _TEXT_PAD)
            _draw_text(c, page_height, line, x, top, size, links=links)


def _draw_details(c: canvas.Canvas, page_height: float, fields: dict, links: list | None = None) -> None:
    for column, (left, right, align) in _DETAIL_COLUMNS.items():
        for row, (cell_top, cell_bottom, text_top) in _DETAIL_ROWS.items():
            key = f"{column}_{row}"
            if key not in fields:
                continue
            is_email = row == "email"
            _replace_cell(
                c,
                page_height,
                str(fields[key] or ""),
                x=left + _DETAIL_PAD,
                top=text_top,
                cell=(left, right, cell_top, cell_bottom),
                size=_DETAIL_FONT_SIZE,
                align=align,
                color=BLUE if is_email else BLACK,
                links=links,
            )


_HEAD_KEYS = {"po_number", "po_date", "payment_terms", "bill_to", "license_email", "quote_number", "end_user_po"}
_TAIL_KEYS = {
    "shipping_method", "ior_name", "ior_street", "ior_city", "ior_state", "ior_zip",
    "ior_country", "ior_contact", "vat_number",
}


# --- Items grid ----------------------------------------------------------------
def _row_geometry(slot: int, y0: float) -> tuple[float, float, float]:
    """(top rule y, bottom rule y, text top) of the table's slot-th row on a page
    whose first row's top rule is at y0. The first 12 rows follow the template's
    own (slightly uneven) rule positions; later rows use the plain pitch."""
    shift = y0 - ROW_RULE_TOPS[0]
    text_top = FIRST_TEXT_TOP + TEXT_PITCH * slot + shift
    if slot < ITEM_ROWS:
        return ROW_RULE_TOPS[slot] + shift, ROW_RULE_TOPS[slot + 1] + shift, text_top
    top = ROW_RULE_TOPS[ITEM_ROWS] + shift + TEXT_PITCH * (slot - ITEM_ROWS)
    return top, top + TEXT_PITCH, text_top


def _draw_hrule(c: canvas.Canvas, page_height: float, y_top: float, thickness: float) -> None:
    c.saveState()
    c.setFillColorRGB(*BLACK)
    c.rect(_HRULE_LEFT, page_height - y_top - thickness, _HRULE_RIGHT - _HRULE_LEFT, thickness, fill=1, stroke=0)
    c.restoreState()


def _draw_vrules(c: canvas.Canvas, page_height: float, y_top: float, y_bottom: float) -> None:
    c.saveState()
    c.setFillColorRGB(*BLACK)
    for x, width in _VRULES:
        c.rect(x, page_height - y_bottom, width, y_bottom - y_top, fill=1, stroke=0)
    c.restoreState()


def _draw_item_row(c: canvas.Canvas, page_height: float, item: dict | None, text_top: float) -> None:
    if item is None:
        # Blank rows still print a zero in the Total column.
        _draw_text(
            c, page_height, _format_money(Decimal("0")), _COL_EDGES["total"][1] - _TEXT_PAD, text_top, _TEXT_SIZE, align="right"
        )
        return

    qty = _to_decimal(item.get("qty"))
    unit_price = _to_decimal(item.get("unit_cost"))
    amount = _line_amount(item)

    # A part number is an identifier, so shrink it to fit rather than clip
    # characters off the end (descriptions are free text and do clip, as
    # the sample's own do).
    part_left, part_right = _COL_EDGES["part_number"]
    part = str(item.get("part_number") or "")
    part_room = part_right - part_left - 2 * _TEXT_PAD
    part_size = _fit(part, FONT, _TEXT_SIZE, part_room)
    part = _clip(part, FONT, part_size, part_room)
    _draw_text(c, page_height, part, part_left + _TEXT_PAD, text_top, part_size)

    desc_left, desc_right = _COL_EDGES["description"]
    desc = _clip(str(item.get("description") or ""), FONT, _DESCRIPTION_SIZE, desc_right - desc_left - 2 * _TEXT_PAD)
    _draw_text(c, page_height, desc, desc_left + _TEXT_PAD, text_top + 0.6, _DESCRIPTION_SIZE)

    qty_left, qty_right = _COL_EDGES["qty"]
    _draw_text(c, page_height, f"{qty.normalize():f}", (qty_left + qty_right) / 2, text_top, _TEXT_SIZE, align="center")

    term_left, term_right = _COL_EDGES["term"]
    terms = str(item.get("terms") or "").strip()
    _draw_text(c, page_height, terms, (term_left + term_right) / 2, text_top, _TEXT_SIZE, align="center")

    price_left, price_right = _COL_EDGES["price"]
    # The first row prints its price with a currency sign in the sample;
    # keep every row plain so the column reads consistently.
    _draw_text(
        c, page_height, _format_price(unit_price), (price_left + price_right) / 2, text_top, _TEXT_SIZE, align="center"
    )

    _draw_text(c, page_height, _format_money(amount), _COL_EDGES["total"][1] - _TEXT_PAD, text_top, _TEXT_SIZE, align="right")


def _line_amount(item: dict) -> Decimal:
    return (_to_decimal(item.get("qty")) * _to_decimal(item.get("unit_cost"))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _draw_items_grid(c: canvas.Canvas, page_height: float, page_items: list[dict], y0: float, slots: int) -> None:
    """Draws `slots` rows (a real item, or a blank row past the end of page_items)
    with the first row's top rule at y0: each row's text, the rules between rows,
    and the vertical column rules. The rule closing the table is not drawn here --
    the template's own comes with the tail block, and _draw_closing_rule covers
    pages that continue."""
    for slot in range(slots):
        _, bottom_rule, text_top = _row_geometry(slot, y0)
        _draw_item_row(c, page_height, page_items[slot] if slot < len(page_items) else None, text_top)
        if slot < slots - 1:
            _draw_hrule(c, page_height, bottom_rule, _HRULE_THIN)
    _draw_vrules(c, page_height, y0 + _HRULE_HEAVY, _row_geometry(slots - 1, y0)[1])


# --- Tail pieces ---------------------------------------------------------------
def _draw_total_cell(c: canvas.Canvas, page_height: float, grand_total: Decimal, dy: float) -> None:
    left, right, top, bottom = _TOTAL_CELL
    _cover(c, page_height, left + INSET, top + INSET + dy, right - INSET, bottom - INSET + dy)
    _draw_text(
        c, page_height, _format_money(grand_total), right - _TEXT_PAD, _TOTAL_TEXT_TOP + dy, 6.0, bold=True, align="right"
    )


# The closing sentence ("... ACCEPTS ALL ADDITIONAL TERMS ON RUBRIK QUOTE <quote>
# DATED <date>") under the IOR block. It repeats the quote number and date, so it
# is rebuilt from those two fields. Measured from the sample: 11pt Tahoma, text
# from x=92 to 622 at top 528.85, centered on the page body.
_FOOTER_TEXT_TOP = 528.85
_FOOTER_COVER = (88.0, 526.0, 654.3, 543.0)  # left, top, right, bottom
_FOOTER_SIZE = 11.0
_FOOTER_CENTER_X = (92.05 + 622.3) / 2


def _draw_footer_sentence(c: canvas.Canvas, page_height: float, fields: dict, dy: float) -> None:
    if "quote_number" not in fields and "quote_date" not in fields:
        return
    quote_number = str(fields.get("quote_number") or "").strip()
    quote_date = str(fields.get("quote_date") or "").strip()
    distributor = str(fields.get("distributor_company") or "COMPUTER GROSS SPA").strip().upper()
    text = f"{distributor} ACCEPTS ALL ADDITIONAL TERMS ON RUBRIK QUOTE {quote_number} DATED {quote_date}".upper()
    left, top, right, bottom = _FOOTER_COVER
    _cover(c, page_height, left, top + dy, right, bottom + dy)
    size = _fit(text, FONT, _FOOTER_SIZE, right - left - 2 * _TEXT_PAD)
    _draw_text(c, page_height, text, _FOOTER_CENTER_X, _FOOTER_TEXT_TOP + dy, size, align="center")


def _page_label(c: canvas.Canvas, page_height: float, fields: dict, number: int, total: int) -> None:
    po_number = str(fields.get("po_number") or "").strip()
    text = f"PO {po_number} - Page {number} of {total}".replace("PO  -", "PO -")
    _draw_text(c, page_height, text, _HRULE_RIGHT, 28.0, 6.5, align="right")


# --- Cutting pieces out of the template page -----------------------------------
def _clip_piece(template_bytes: bytes, top: float, bottom: float, height: float) -> PageObject:
    """A fresh copy of the template page whose visible area is limited to the
    horizontal band top..bottom (top-origin), with the template's own link
    annotations removed (they would still open the original addresses)."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(template_bytes)))
    page = writer.pages[0]
    width = float(page.mediabox.width)
    data = page.get_contents().get_data()
    stream = DecodedStreamObject()
    stream.set_data(f"q 0 {height - bottom:.3f} {width:.3f} {bottom - top:.3f} re W n\n".encode() + data + b"\nQ")
    page[NameObject("/Contents")] = writer._add_object(stream)
    if "/Annots" in page:
        del page["/Annots"]
    return page


def _compose_page(
    template_bytes: bytes, width: float, height: float, pieces: list[tuple[float, float, float]], overlay_page
) -> PageObject:
    """A blank page with each (clip top, clip bottom, dy-down) piece of the
    template placed on it, then the drawn overlay on top."""
    page = PageObject.create_blank_page(width=width, height=height)
    for clip_top, clip_bottom, dy_down in pieces:
        piece = _clip_piece(template_bytes, clip_top, clip_bottom, height)
        page.merge_transformed_page(piece, Transformation().translate(0, -dy_down))
    page.merge_page(overlay_page)
    return page


def _add_links(writer: PdfWriter, links: list, height: float) -> None:
    add_links(writer, links, height)


# --- Pagination ----------------------------------------------------------------
def _paginate(count: int) -> list[dict]:
    """Splits `count` items into page specs: {"first", "last", "rows", "tail", "y0"}.

    "rows" is how many row slots the page draws (page 1 always shows at least the
    template's 12, blank rows included), "tail" says whether the TOTAL/Shipping/
    IOR block sits under the table on this page, "y0" is the first row's top rule.
    A page that continues leaves at least 2 rows for the next one, so the last
    page never carries the tail under an empty table."""
    cont_y0 = CONT_BAND_TOP + (ROW_RULE_TOPS[0] - BAND_CLIP_TOP)

    def rows_fit(y0: float, limit: float) -> int:
        n = 0
        while _row_geometry(n, y0)[1] <= limit:
            n += 1
        return n

    pages: list[dict] = []
    start, y0 = 0, ROW_RULE_TOPS[0]
    while True:
        remaining = count - start
        if remaining <= rows_fit(y0, TAIL_LIMIT - TAIL_HEIGHT):
            rows = remaining if pages else max(remaining, ITEM_ROWS)
            pages.append({"first": start, "last": count, "rows": rows, "tail": True, "y0": y0})
            return pages
        take = max(1, min(rows_fit(y0, BODY_BOTTOM), remaining - 2))
        pages.append({"first": start, "last": start + take, "rows": take, "tail": False, "y0": y0})
        start += take
        y0 = cont_y0


def generate_computer_gross_spa_po(fields: dict, line_items: list[dict]) -> bytes:
    path = find_template_path(SLUG)
    if path is None:
        raise FileNotFoundError(f"No template PDF found for distributor '{SLUG}'")

    items = [i for i in line_items if i and (i.get("part_number") or i.get("description"))]
    specs = _paginate(len(items))
    grand_total = sum((_line_amount(i) for i in items), Decimal("0"))

    template_bytes = path.read_bytes()
    template_page = PdfReader(io.BytesIO(template_bytes)).pages[0]
    width, height = float(template_page.mediabox.width), float(template_page.mediabox.height)

    writer = PdfWriter()
    total_pages = len(specs)
    for number, spec in enumerate(specs, start=1):
        links: list = []
        is_first = number == 1
        y0 = spec["y0"]
        closing = _row_geometry(spec["rows"] - 1, y0)[1]
        tail_dy = closing - TAIL_RULE_TOP

        def draw(c: canvas.Canvas, spec=spec, is_first=is_first, y0=y0, closing=closing, tail_dy=tail_dy, number=number) -> None:
            if is_first:
                _draw_header_values(c, height, fields, _HEAD_KEYS, links)
                _draw_details(c, height, fields, links)
            _draw_items_grid(c, height, items[spec["first"] : spec["last"]], y0, spec["rows"])
            if spec["tail"]:
                _draw_header_values(c, height, fields, _TAIL_KEYS, links, dy=tail_dy)
                _draw_total_cell(c, height, grand_total, tail_dy)
                _draw_footer_sentence(c, height, fields, tail_dy)
            else:
                _draw_hrule(c, height, closing, _HRULE_HEAVY)
            if total_pages > 1:
                _page_label(c, height, fields, number, total_pages)

        pieces: list[tuple[float, float, float]] = []
        if is_first:
            pieces.append((0.0, HEAD_BOTTOM, 0.0))
        else:
            pieces.append((BAND_CLIP_TOP, HEAD_BOTTOM, CONT_BAND_TOP - BAND_CLIP_TOP))
        if spec["tail"]:
            pieces.append((TAIL_CLIP_TOP, height, tail_dy))

        overlay = _render_overlay(width, height, draw)
        writer.add_page(_compose_page(template_bytes, width, height, pieces, overlay.pages[0]))
        _add_links(writer, links, height)

    output = io.BytesIO()
    writer.write(output)
    pdf_output = output.getvalue()

    po_number = (fields.get("po_number") or "PO").strip().replace("/", "-").replace(" ", "_") or "PO"
    out_dir = Path(config.GENERATED_DIR) / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{po_number}.pdf").write_bytes(pdf_output)

    return pdf_output
