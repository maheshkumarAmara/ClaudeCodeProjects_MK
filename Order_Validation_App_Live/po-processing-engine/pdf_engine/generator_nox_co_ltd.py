"""Regenerates NOX Co.,LTD. purchase orders.

The template is a one-page "ORDER SHEET": a label/value block (reference,
shipment, payment, end user, quote no, the two notification emails) whose
values carry a drawn underline, a bill-to block, a boxed items table with 8
fixed rows, the total, the freight forwarder lines and a footer. Nothing
flows, so there is nothing to paginate: this module keeps the template page,
covers each value with a white box that stays clear of the surrounding rules,
and redraws the new text. The items table is redrawn row by row.

Behaviors worth knowing:
  - The table has 8 printed rows. More rows than that are rejected with a clear
    error rather than silently dropped or drawn over the TOTAL line.
  - A row's description shrinks to fit its cell, as the sample's own long
    descriptions do (items 5 and 6 print at 3.6-4.1pt).
  - Amounts print the way the sample does ("$20,306.52"): the line amount is
    quantity x unit price, and the TOTAL is recomputed from the rows.
  - Fields missing from the request keep the value that is already on the
    template.
  - Text is drawn in Helvetica, not the template's embedded CID font, which
    can't be reused for new characters.
"""

import io
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pypdf import PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

import config
from pdf_engine.common import clip_text, fit_size
from pdf_engine.extractor import find_template_path
from pdf_engine.generator import _fresh_page, _render_overlay
from pdf_engine.paginate import _to_decimal

SLUG = "NOX Co.,LTD."

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"
# pdfplumber's `top` is the top of a box whose bottom sits one descent
# (0.207 em for Helvetica) below the baseline.
BASELINE_FACTOR = 0.793
MIN_FONT_SIZE = 3.0

WHITE = (1.0, 1.0, 1.0)
BLACK = (0.0, 0.0, 0.0)
UNDERLINE_WIDTH = 0.6

# --- Single-line text fields -------------------------------------------------
# key -> (text x, text top, cover left, cover top, cover right, cover bottom, size, align)
# Covers stop short of the surrounding rules and of neighboring text.
_TEXT_FIELDS = {
    # Header block, top right.
    "po_number": (505.9, 13.1, 503.0, 12.6, 578.0, 23.4, 10.0, "left"),
    # Footer.
    "end_user_po": (95.6, 576.4, 92.0, 575.8, 300.0, 587.6, 10.0, "left"),
    # Freight forwarder block.
    "forwarder": (16.9, 480.6, 14.0, 480.0, 300.0, 486.4, 6.0, "left"),
    "forwarder_contact": (25.9, 486.6, 14.0, 486.5, 300.0, 493.0, 6.0, "left"),
    # Signature block.
    "signatory": (493.4, 626.0, 490.0, 625.5, 580.0, 632.5, 6.0, "left"),
    "signatory_title": (493.7, 637.7, 490.0, 637.2, 580.0, 644.2, 6.0, "left"),
}

# Bill To & Ship To block (company is larger text, the rest is 6pt).
_BILL_TO_X = 99.1
_BILL_TO_COVER = (97.0, 249.0, 300.0, 290.0)  # left, top, right, bottom
_BILL_TO_COMPANY_TOP = 250.2
_BILL_TO_ADDRESS_TOPS = (261.8, 268.2)
_BILL_TO_TEL_FAX_TOP = 274.4
_BILL_TO_MAIL_TOP = 280.6

# --- Label / value block, whose values carry a drawn underline -------------
# key -> (value top, row top for the cover, row bottom for the cover, underline y top)
_UNDERLINED_X = 99.1
_UNDERLINED_RIGHT = 195.0  # the widest underline in the template ends at 190.0
_UNDERLINED_FIELDS = {
    "reference": (137.7, 137.0, 145.0, 145.0),
    "shipment": (146.2, 145.8, 153.4, 153.5),
    "payment_terms": (172.9, 172.2, 180.0, 180.2),
    "end_user": (182.1, 181.5, 189.2, 189.4),
    "quote_number": (199.2, 198.6, 206.2, 206.5),
    # The two email values sit directly under their "Please Send ..." labels,
    # which run right to x=170 -- past the cover's left edge -- so each cover
    # starts below its label's text (bottom at 215.1 / 231.9), not above it.
    "order_ack_email": (216.0, 215.5, 222.9, 223.3),
    "shipping_notice_email": (231.6, 232.0, 238.5, 238.9),
}
_UNDERLINE_TEXT_SIZE = 7.9

# --- Order date, "Order Date:Dec 03 2025" (label stays; only the date is replaced)
_ORDER_DATE = (505.5, 23.1, 503.0, 22.6, 578.0, 33.4, 10.0)  # text x, top, cover l/t/r/b, size

# --- Items table ---------------------------------------------------------------
ITEM_ROWS = 8
# Top and bottom of each row's box, read from the template's row rectangles.
ROW_EDGES = (
    (347.4, 361.0),
    (361.6, 375.1),
    (375.3, 388.9),
    (389.9, 403.4),
    (404.0, 417.6),
    (418.3, 431.9),
    (432.5, 446.0),
    (446.6, 460.2),
)
# Text top of row 0 and the pitch between rows, from the sample.
FIRST_TEXT_TOP = 351.12
TEXT_PITCH = 14.18
# Vertical column edges (left, right) and how each column aligns.
_COLS = {
    "pos": (14.3, 28.3),
    "part_number": (28.3, 172.8),
    "description": (172.8, 433.1),
    "term": (433.1, 485.5),
    "unit_price": (433.1, 485.5),
    "qty": (485.5, 522.8),
    "amount": (522.8, 580.7),
}
# The Term column sits between the Description and Unit Price columns. Its
# left rule is at x=412.3 (measured from the rendered template; it is not among
# the extracted line edges), so covers must stay right of it.
_TERM_COL = (412.3, 433.1)
_UNIT_PRICE_COL = (433.1, 485.5)
_QTY_COL = (485.5, 522.8)
_ITEM_SIZE = 7.0
_PAD = 1.6
_COVER_INSET = 0.9  # keep covers clear of the 0.5pt column rules

# TOTAL.
_TOTAL_TEXT_RIGHT = 576.5
_TOTAL_TOP = 460.8
_TOTAL_COVER = (521.0, 461.0, 580.0, 471.5)
# Shipping term, "Shipping Term: FCA Origin" in italic; label stays.
_SHIPPING_TERM = (92.2, 462.0, 91.0, 461.3, 300.0, 470.5, 7.9)


def _fit(text: str, font: str, size: float, max_width: float) -> float:
    return fit_size(text, font, size, max_width, MIN_FONT_SIZE)


def _clip(text: str, font: str, size: float, max_width: float) -> str:
    return clip_text(text, font, size, max_width)


def _cover(c: canvas.Canvas, page_height: float, left: float, top: float, right: float, bottom: float) -> None:
    c.saveState()
    c.setFillColorRGB(*WHITE)
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
    font: str = FONT,
    align: str = "left",
) -> None:
    if not text:
        return
    c.saveState()
    c.setFont(font, size)
    c.setFillColorRGB(*BLACK)
    baseline = page_height - top - size * BASELINE_FACTOR
    if align == "right":
        c.drawRightString(x, baseline, text)
    elif align == "center":
        c.drawCentredString(x, baseline, text)
    else:
        c.drawString(x, baseline, text)
    c.restoreState()


def _replace_text(
    c: canvas.Canvas,
    page_height: float,
    text: str,
    spec: tuple[float, float, float, float, float, float, float, str],
) -> None:
    """Covers a value and draws its replacement, shrinking the text to the
    cover's width so it never runs into a neighboring element."""
    x, top, cover_left, cover_top, cover_right, cover_bottom, size, align = spec
    _cover(c, page_height, cover_left, cover_top, cover_right, cover_bottom)
    room = cover_right - x - 1.0
    drawn_size = _fit(text, FONT, size, room)
    _draw_text(c, page_height, _clip(text, FONT, drawn_size, room), x, top, drawn_size, align=align)


def _draw_underlined(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    """Reference / shipment / payment / end user / quote no / emails: each value
    sits on a drawn underline whose length matches the old value, so the old
    underline is covered and a new one is drawn under the new text."""
    for key, (top, cover_top, cover_bottom, underline_top) in _UNDERLINED_FIELDS.items():
        if key not in fields:
            continue
        text = str(fields[key] or "")
        _cover(c, page_height, _UNDERLINED_X - 1.0, cover_top, _UNDERLINED_RIGHT + 1.0, cover_bottom + 0.9)
        room = _UNDERLINED_RIGHT - _UNDERLINED_X
        size = _fit(text, FONT, _UNDERLINE_TEXT_SIZE, room)
        text = _clip(text, FONT, size, room)
        _draw_text(c, page_height, text, _UNDERLINED_X, top, size)
        if text:
            width = stringWidth(text, FONT, size)
            y = page_height - underline_top
            c.saveState()
            c.setStrokeColorRGB(*BLACK)
            c.setLineWidth(UNDERLINE_WIDTH)
            c.line(_UNDERLINED_X, y, _UNDERLINED_X + width, y)
            c.restoreState()


def _draw_bill_to(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    keys = ("bill_to_company", "bill_to_address", "bill_to_tel_fax", "bill_to_mail", "bill_to_contact")
    if not any(k in fields for k in keys):
        return
    left, top, right, bottom = _BILL_TO_COVER
    _cover(c, page_height, left, top, right, bottom)
    room = right - _BILL_TO_X - 1.0

    company = str(fields.get("bill_to_company") or "")
    size = _fit(company, FONT_BOLD, 12.0, room)
    _draw_text(c, page_height, company, _BILL_TO_X, _BILL_TO_COMPANY_TOP, size, font=FONT_BOLD)

    # The address prints on up to two lines, split at the first comma-free
    # break nearest the middle, matching the sample's "street" / "postcode country".
    address = str(fields.get("bill_to_address") or "")
    first, second = _split_address(address, room)
    for line, line_top in zip((first, second), _BILL_TO_ADDRESS_TOPS):
        line_size = _fit(line, FONT, 6.0, room)
        _draw_text(c, page_height, line, _BILL_TO_X, line_top, line_size)

    tel_fax = str(fields.get("bill_to_tel_fax") or "")
    _draw_text(c, page_height, tel_fax, _BILL_TO_X, _BILL_TO_TEL_FAX_TOP, _fit(tel_fax, FONT, 6.0, room))

    mail = str(fields.get("bill_to_mail") or "")
    contact = str(fields.get("bill_to_contact") or "")
    mail_line = f"Mail: {mail}   Contact: {contact}".rstrip()
    _draw_text(c, page_height, mail_line, _BILL_TO_X, _BILL_TO_MAIL_TOP, _fit(mail_line, FONT, 6.0, room))


def _split_address(address: str, max_width: float) -> tuple[str, str]:
    """Splits an address over two printed lines, breaking at a word boundary so
    the first line is as full as fits."""
    words = address.split()
    first = ""
    for index, word in enumerate(words):
        candidate = f"{first} {word}".strip()
        if stringWidth(candidate, FONT, 6.0) > max_width:
            return first, " ".join(words[index:])
        first = candidate
    return first, ""


def _format_money(value: Decimal) -> str:
    """"$20,306.52": dollar sign, "," for thousands, "." for the decimal."""
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole, _, fraction = f"{abs(quantized):.2f}".partition(".")
    sign = "-" if quantized < 0 else ""
    return f"{sign}${int(whole):,}.{fraction}"


def _draw_items(c: canvas.Canvas, page_height: float, items: list[dict]) -> Decimal:
    grand_total = Decimal("0")
    for index in range(ITEM_ROWS):
        row_top, row_bottom = ROW_EDGES[index]
        # Clear each cell's text, staying clear of the column rules.
        for name, (left, right) in (
            ("pos", _COLS["pos"]),
            ("part", _COLS["part_number"]),
            ("desc", _COLS["description"]),
            ("term", _TERM_COL),
            ("price", _UNIT_PRICE_COL),
            ("qty", _QTY_COL),
            ("amount", _COLS["amount"]),
        ):
            # The description cell also holds the term column's left part;
            # clamp so the term cell isn't covered twice by neighbors.
            cover_right = _TERM_COL[0] if name == "desc" else right
            _cover(
                c,
                page_height,
                left + _COVER_INSET,
                row_top + _COVER_INSET * 0.5,
                cover_right - _COVER_INSET,
                row_bottom - _COVER_INSET * 0.5,
            )
        if index >= len(items):
            # Blank rows keep their printed position number, as the form has
            # eight numbered rows even when fewer are filled.
            pos_left, pos_right = _COLS["pos"]
            _draw_text(
                c, page_height, str(index + 1), (pos_left + pos_right) / 2, FIRST_TEXT_TOP + TEXT_PITCH * index, _ITEM_SIZE, align="center"
            )
            continue

        item = items[index]
        text_top = FIRST_TEXT_TOP + TEXT_PITCH * index
        qty = _to_decimal(item.get("qty"))
        unit_price = _to_decimal(item.get("unit_cost"))
        amount = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        grand_total += amount

        # Position number, centered in its narrow column.
        pos_left, pos_right = _COLS["pos"]
        _draw_text(c, page_height, str(index + 1), (pos_left + pos_right) / 2, text_top, _ITEM_SIZE, align="center")

        part_left, part_right = _COLS["part_number"]
        part = str(item.get("part_number") or "")
        part_room = part_right - part_left - 2 * _PAD
        part_size = _fit(part, FONT, _ITEM_SIZE, part_room)
        _draw_text(
            c, page_height, _clip(part, FONT, part_size, part_room), part_left + _PAD + 0.5, text_top, part_size
        )

        # Description: shrink to fit the cell, like the sample's own long ones.
        desc_left, _ = _COLS["description"]
        desc_right = _TERM_COL[0] - _PAD
        desc = str(item.get("description") or "")
        desc_room = desc_right - desc_left - _PAD
        desc_size = _fit(desc, FONT, _ITEM_SIZE, desc_room)
        desc_top = text_top + (_ITEM_SIZE - desc_size) * 0.45  # keep small text vertically centered
        _draw_text(
            c, page_height, _clip(desc, FONT, desc_size, desc_room), desc_left + _PAD + 0.9, desc_top, desc_size
        )

        terms = str(item.get("terms") or "").strip()
        _draw_text(c, page_height, terms, (_TERM_COL[0] + _TERM_COL[1]) / 2, text_top - 1.4, _ITEM_SIZE, align="center")

        _draw_text(c, page_height, _format_money(unit_price), _UNIT_PRICE_COL[1] - 0.6, text_top, _ITEM_SIZE, align="right")
        _draw_text(c, page_height, f"{qty.normalize():f}", _QTY_COL[1] - 1.0, text_top, _ITEM_SIZE, align="right")
        _draw_text(c, page_height, _format_money(amount), _COLS["amount"][1] - 0.8, text_top, _ITEM_SIZE, align="right")
    return grand_total


def _draw_total(c: canvas.Canvas, page_height: float, grand_total: Decimal) -> None:
    left, top, right, bottom = _TOTAL_COVER
    _cover(c, page_height, left, top, right, bottom)
    _draw_text(c, page_height, _format_money(grand_total), _TOTAL_TEXT_RIGHT, _TOTAL_TOP, 10.0, align="right")


def _draw_shipping_term(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    if "shipping_term" not in fields:
        return
    x, top, cover_left, cover_top, cover_right, cover_bottom, size = _SHIPPING_TERM
    text = str(fields["shipping_term"] or "")
    _cover(c, page_height, cover_left, cover_top, cover_right, cover_bottom)
    room = cover_right - x - 1.0
    drawn_size = _fit(text, FONT_ITALIC, size, room)
    _draw_text(c, page_height, _clip(text, FONT_ITALIC, drawn_size, room), x, top, drawn_size, font=FONT_ITALIC)


def _draw_order_date(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    if "po_date" not in fields:
        return
    x, top, cover_left, cover_top, cover_right, cover_bottom, size = _ORDER_DATE
    _cover(c, page_height, cover_left, cover_top, cover_right, cover_bottom)
    text = str(fields["po_date"] or "")
    _draw_text(c, page_height, text, x, top, _fit(text, FONT, size, cover_right - x - 1.0))


def _draw(c: canvas.Canvas, page_height: float, fields: dict, items: list[dict]) -> None:
    for key, spec in _TEXT_FIELDS.items():
        if key in fields:
            _replace_text(c, page_height, str(fields[key] or ""), spec)
    _draw_order_date(c, page_height, fields)
    _draw_underlined(c, page_height, fields)
    _draw_bill_to(c, page_height, fields)
    _draw_shipping_term(c, page_height, fields)
    grand_total = _draw_items(c, page_height, items)
    _draw_total(c, page_height, grand_total)


def generate_nox_co_ltd_po(fields: dict, line_items: list[dict]) -> bytes:
    path = find_template_path(SLUG)
    if path is None:
        raise FileNotFoundError(f"No template PDF found for distributor '{SLUG}'")

    items = [i for i in line_items if i and (i.get("part_number") or i.get("description"))]
    if len(items) > ITEM_ROWS:
        raise ValueError(
            f"NOX's order sheet holds {ITEM_ROWS} line items; this PO has {len(items)}. "
            "Remove some rows or split the order."
        )

    pdf_bytes = path.read_bytes()
    page = _fresh_page(pdf_bytes, 0)
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    overlay = _render_overlay(width, height, lambda c: _draw(c, height, fields, items))
    page.merge_page(overlay.pages[0])

    writer = PdfWriter()
    writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    pdf_output = output.getvalue()

    po_number = (fields.get("po_number") or "PO").strip().replace("/", "-").replace(" ", "_") or "PO"
    out_dir = Path(config.GENERATED_DIR) / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{po_number}.pdf").write_bytes(pdf_output)

    return pdf_output
