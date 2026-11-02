"""Regenerates iValue InfoSolutions Limited purchase orders.

The template is a portrait, 2-page printout: a letterhead with the iValue logo, a boxed
header (Supplier, Purchase Order details, Bill To, Ship To), a ruled items table, a
totals box and a Terms and Conditions block. The second page of the sample repeats the
header and adds the Quote No., an "Additional Information" band (End Customer, Reseller,
Freight Forwarder) and the Authorized By line.

The letterhead, the title and the box borders come from the template. Everything else
is redrawn: the header values, the items table (rows grow with their wrapped text), the
totals, the terms and the closing block. Pages are added as needed; each items page
repeats the header and the table's column-header band. The template's own text under the
redrawn areas is covered with white boxes, and the app's strip pass removes it from the
file afterwards.

Behaviors worth knowing:
  - A row's Amount is qty x net unit price, always recomputed. The net unit price is the
    unit price less "pct_disc" percent, and it is the price printed, so each row adds up.
  - Total is the sum of the rows. Grand Total is Total - discount + CGST + SGST + IGST.
    Round off is printed as 0.00, as in the sample.
  - The amount in words is the grand total.
  - Descriptions are printed in full, wrapped to their column. A row that has a term gets
    it appended as "(36 Months)"; rows without one are printed as they are.
  - "Term (Mos)" prints the term_months field, or the first row's term when that is empty.
  - Emails are passed through sandbox_email.
"""

import io
import re
from decimal import ROUND_HALF_UP, Decimal

from pypdf import PdfReader, PdfWriter

from pdf_engine.common import fit_size, money_2dp, qty_text
from pdf_engine.extractor import find_template_path
from pdf_engine.generator import _render_overlay
from pdf_engine.paginate import _to_decimal, wrap_chars, wrap_text
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from sandbox_email import sandbox_text

SLUG = "iValue InfoSolutions Limited"

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
BLACK = (0.0, 0.0, 0.0)
WHITE = (1.0, 1.0, 1.0)
GREY = (0.753, 0.753, 0.753)

PAGE_W, PAGE_H = 612.0, 792.0
BASELINE = 0.8  # a line's baseline sits this share of its font size below the line's top
MIN_FONT_SIZE = 6.0
RULE = 0.6

# --- Template pieces (top-origin y) ---------------------------------------------------
# The header boxes keep their borders from the template. These are their interiors, which
# hold the values and are redrawn.
HEADER_BOXES = (
    (28.0, 131.5, 304.0, 229.5),  # Supplier
    (308.0, 131.5, 586.0, 229.5),  # PO details
    (28.0, 232.0, 304.0, 346.5),  # Bill To
    (308.0, 232.0, 586.0, 346.5),  # Ship To
)
# Everything from the items table down: table, totals, terms, closing block and footer.
LOWER_AREA = (20.0, 348.0, 592.0, 792.0)
FOOTER = "This is a computer generated document hence no signature required."

# --- Items table ----------------------------------------------------------------------
TABLE_TOP = 354.3  # top of the column-header band
TABLE_HEAD_H = 30.8
FIRST_ROW_TOP = 385.1
COL_EDGES = (25.2, 43.2, 116.9, 217.2, 349.5, 413.8, 497.8, 585.6)
HEAD_LABELS = (
    ("No.",),
    ("OEM", "Part No."),
    ("Item Type /", "HSN Code"),
    ("Description",),
    ("Quantity",),
    ("Unit Price", "[USD]"),
    ("USD", "Amount"),
)
HEAD_SIZE = 7.5
HEAD_PITCH = 9.5
TEXT_SIZE = 8.0
LINE_PITCH = 9.3
TEXT_TOP = 4.3  # the first text line sits this far below the row's top rule
ROW_PAD = 6.5
PART_X = COL_EDGES[1] + 2.9
PART_W = COL_EDGES[2] - COL_EDGES[1] - 5.8
TYPE_W = COL_EDGES[3] - COL_EDGES[2] - 6.0
DESC_X = COL_EDGES[3] + 2.8
DESC_W = COL_EDGES[4] - COL_EDGES[3] - 5.6
QTY_RIGHT = 389.5
UNIT_X = 393.0
PRICE_RIGHT = 495.0
AMOUNT_RIGHT = 583.0
CONTENT_BOTTOM = 772.0

# --- Totals box -----------------------------------------------------------------------
TOTALS_X0, TOTALS_X1 = 354.7, 585.4
TOTALS_ROW_H = 18.0
TOTALS_LABELS = ("Total", "Discount", "CGST", "SGST", "IGST", "Round off", "Grand Total USD")
TOTALS_H = TOTALS_ROW_H * len(TOTALS_LABELS)
WORDS_H = 2 * TOTALS_ROW_H  # the amount-in-words cell at the foot of the box
LABEL_RIGHT = 440.0
VALUE_RIGHT = 582.0

# --- Terms, closing block -------------------------------------------------------------
LEFT, RIGHT = 25.2, 585.6
TERMS_PAD = 6.0
TERMS_SIZE = 9.0
TERMS_PITCH = 10.2
HEADING_PITCH = 12.0
TERMS_W = RIGHT - LEFT - 12.0
CLOSING_GAP = 8.0
QUOTE_H = 22.0
INFO_X = (30.0, 217.0, 404.0)
INFO_W = 172.0
INFO_SIZE = 8.5
INFO_PITCH = 10.6
INFO_HEAD_H = 17.0
INFO_PAD = 6.0
AUTH_GAP = 22.0
AUTH_H = AUTH_GAP + 14.0

NOTES = (
    "1.Partial shipment is not allowed, not withstanding the issuance of separate Purchase Orders (POs) under the same deal.",
    "2.The license and /or support documentation, along with the tax invoice, must be submitted to procurement@ivalue.co.in",
    "3. Invoices for Professional Services (PS) and other related services shall be raised only upon obtaining the applicable customer sign-off.",
    "4. When hardware and software/support components are part of the same project, software and/or support invoicing shall be undertaken only after the hardware has been invoiced.",
)

_ONES = (
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
    "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen",
)
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")
_SCALES = ((1_000_000_000, "Billion"), (1_000_000, "Million"), (1_000, "Thousand"))


# --- Text helpers ---------------------------------------------------------------------
def _split(text) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _text(
    c: canvas.Canvas,
    x: float,
    top: float,
    text: str,
    size: float = 9.0,
    *,
    bold: bool = False,
    align: str = "left",
    max_width: float | None = None,
) -> None:
    """Draws one line with its box's top at `top`. Shrinks the font to fit max_width."""
    if not text:
        return
    font = FONT_BOLD if bold else FONT
    if max_width is not None:
        size = fit_size(text, font, size, max_width, MIN_FONT_SIZE)
    width = stringWidth(text, font, size)
    left = {"left": x, "right": x - width, "center": x - width / 2}[align]
    c.saveState()
    c.setFont(font, size)
    c.setFillColorRGB(*BLACK)
    c.drawString(left, PAGE_H - top - size * BASELINE, text)
    c.restoreState()


def _lines_at(c, x: float, top: float, lines: list[str], align: str = "left") -> None:
    for i, line in enumerate(lines):
        _text(c, x, top + i * LINE_PITCH, line, TEXT_SIZE, align=align)


def _block(c, x: float, top: float, text, *, max_width: float, size: float = 10.0, pitch: float = 11.5) -> float:
    """Draws the lines of `text` one per pitch, the first in bold. A line wider than the box
    wraps onto the next pitch (as the sample's long addresses do) instead of shrinking.
    Returns the top of the line after the last one."""
    for i, line in enumerate(_split(text)):
        # wrap_text measures in regular weight, so a long bold first line can still be a
        # touch wide; _text's max_width shrinks it the last bit.
        for part in wrap_text(line, max_width, size):
            _text(c, x, top, part, size, bold=i == 0, max_width=max_width)
            top += pitch
    return top


# --- Shapes ---------------------------------------------------------------------------
def _rect(c: canvas.Canvas, x0: float, top: float, x1: float, bottom: float, fill) -> None:
    c.saveState()
    c.setFillColorRGB(*fill)
    c.rect(x0, PAGE_H - bottom, x1 - x0, bottom - top, fill=1, stroke=0)
    c.restoreState()


def _hline(c, x0: float, x1: float, top: float) -> None:
    _rect(c, x0, top, x1, top + RULE, BLACK)


def _vline(c, x: float, top: float, bottom: float) -> None:
    _rect(c, x, top, x + RULE, bottom, BLACK)


def _frame(c, x0: float, top: float, x1: float, bottom: float) -> None:
    _hline(c, x0, x1, top)
    _hline(c, x0, x1, bottom)
    _vline(c, x0, top, bottom)
    _vline(c, x1, top, bottom)


# --- Numbers --------------------------------------------------------------------------
def _number_words(n: int) -> str:
    """1234 -> "One Thousand Two Hundred Thirty Four"."""
    if n == 0:
        return "Zero"
    words: list[str] = []
    for size, name in _SCALES:
        count, n = divmod(n, size)
        if count:
            words += _under_thousand(count) + [name]
    if n:
        words += _under_thousand(n)
    return " ".join(words)


def _under_thousand(n: int) -> list[str]:
    words: list[str] = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        words += [_ONES[hundreds], "Hundred"]
    if rest < 20:
        if rest:
            words.append(_ONES[rest])
    else:
        tens, ones = divmod(rest, 10)
        words.append(_TENS[tens])
        if ones:
            words.append(_ONES[ones])
    return words


def _amount_words(amount: Decimal) -> str:
    cents = int((abs(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    whole, fraction = divmod(cents, 100)
    text = _number_words(whole)
    if fraction:
        text += f" And {_number_words(fraction)} Cents"
    text += " Only"
    return f"Minus {text}" if amount < 0 else text


# --- Items ----------------------------------------------------------------------------
def _wrap_part(text: str, max_width: float, size: float) -> list[str]:
    """A part number wraps after a hyphen where it can ("RA-PS-INST-" / "RMOT"), and only
    inside a piece that is too wide on its own."""
    pieces = re.findall(r"[^-]*-|[^-]+$", text) or [""]
    lines: list[str] = []
    current = ""
    for piece in pieces:
        candidate = current + piece
        if stringWidth(candidate, FONT, size) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = piece
    if current:
        lines.append(current)
    return [part for line in lines for part in wrap_chars(line, max_width, size)] or [""]


def _description_with_term(description: str, terms) -> str:
    """Appends the line's term to its description as "(36 Months)", the way the sample
    prints subscription and support lines. Lines with no term (hardware, services) are
    left alone, and so is a description that already ends with its term."""
    description = description.strip()
    term = str(terms or "").strip()
    if not term:
        return description
    suffix = f"({term} Months)" if term.isdigit() else term
    if suffix.lower() in description.lower():
        return description
    return f"{description} {suffix}".strip()


class _Row:
    def __init__(self, number: int, item: dict) -> None:
        self.number = number
        qty = _to_decimal(item.get("qty"))
        net_price = _to_decimal(item.get("unit_cost")) * (1 - _to_decimal(item.get("pct_disc")) / 100)
        self.amount = (qty * net_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.qty = qty_text(qty)
        self.price_text = money_2dp(net_price)
        self.amount_text = money_2dp(self.amount)
        self.unit = str(item.get("unit") or "NOS")
        self.part_lines = _wrap_part(str(item.get("part_number") or ""), PART_W, TEXT_SIZE)
        self.type_lines = wrap_text(str(item.get("item_type") or ""), TYPE_W, TEXT_SIZE)
        description = _description_with_term(str(item.get("description") or ""), item.get("terms"))
        self.desc_lines = wrap_text(description, DESC_W, TEXT_SIZE)
        lines = max(len(self.part_lines), len(self.type_lines), len(self.desc_lines), 1)
        self.height = lines * LINE_PITCH + ROW_PAD


def _totals(rows: list[_Row], fields: dict) -> tuple[list[str], Decimal]:
    subtotal = sum((row.amount for row in rows), Decimal("0"))
    discount = _to_decimal(fields.get("discount"))
    cgst, sgst, igst = (_to_decimal(fields.get(key)) for key in ("cgst", "sgst", "igst"))
    grand = subtotal - discount + cgst + sgst + igst
    values = [money_2dp(v) for v in (subtotal, discount, cgst, sgst, igst)] + ["0.00", money_2dp(grand)]
    return values, grand


def _terms_lines(fields: dict) -> list[tuple[str, bool]]:
    lines: list[tuple[str, bool]] = [("Terms and Conditions", True)]
    if fields.get("term_months"):
        lines.append((f"Term (Mos): {fields['term_months']}", False))
    if fields.get("customer_po"):
        lines.append((f"Customer PO no: {fields['customer_po']}", False))
    lines += [("", False), ("Standard Note:", False)]
    for note in NOTES:
        lines += [(part, False) for part in wrap_text(sandbox_text(note), TERMS_W, TERMS_SIZE)]
    return lines


def _terms_height(lines: list[tuple[str, bool]]) -> float:
    return 2 * TERMS_PAD + sum(HEADING_PITCH if bold else TERMS_PITCH for _, bold in lines)


def _closing(fields: dict) -> dict:
    columns = []
    for title, key in (
        ("End Customer Details", "end_customer"),
        ("Reseller Details", "reseller"),
        ("Freight Forwarder Details", "freight_forwarder"),
    ):
        lines: list[tuple[str, bool]] = [(title, True)]
        for i, line in enumerate(_split(fields.get(key))):
            lines += [(part, i == 0) for part in wrap_text(line, INFO_W, INFO_SIZE)]
        columns.append(lines)
    box_height = INFO_HEAD_H + max(len(col) for col in columns) * INFO_PITCH + INFO_PAD
    return {"columns": columns, "box_height": box_height, "height": QUOTE_H + box_height + AUTH_H}


# --- Page planning --------------------------------------------------------------------
def _plan(rows: list[_Row], terms: list[tuple[str, bool]], closing: dict) -> list[list[tuple]]:
    """Places every block on pages, in order: the items (the table head repeats on each
    page), then the totals and terms, then the closing block. A block that does not fit
    in what is left of a page starts a new one."""
    pages: list[list[tuple]] = [[("table", TABLE_TOP)]]
    cursor = FIRST_ROW_TOP
    for row in rows:
        if cursor + row.height > CONTENT_BOTTOM:
            pages.append([("table", TABLE_TOP)])
            cursor = FIRST_ROW_TOP
        pages[-1].append(("row", row, cursor))
        cursor += row.height

    # The totals box sits under the last row if it fits (as in the sample); the terms
    # go under it, or on the next page if they don't fit.
    if cursor + TOTALS_H > CONTENT_BOTTOM:
        pages.append([])
        cursor = TABLE_TOP
    pages[-1].append(("totals", cursor))
    cursor += TOTALS_H + CLOSING_GAP
    if cursor + _terms_height(terms) > CONTENT_BOTTOM:
        pages.append([])
        cursor = TABLE_TOP
    pages[-1].append(("terms", cursor, terms))
    cursor += _terms_height(terms) + CLOSING_GAP

    if cursor + closing["height"] > CONTENT_BOTTOM:
        pages.append([])
        cursor = TABLE_TOP
    pages[-1].append(("closing", cursor, closing))
    return pages


# --- Drawing --------------------------------------------------------------------------
def _draw_header(c: canvas.Canvas, fields: dict) -> None:
    _text(c, 29.8, 132.8, "Supplier :", 10, bold=True)
    _block(c, 29.8, 147.6, fields.get("supplier"), max_width=268)

    labels = (
        ("Purchase Order :", "po_number", 135.6),
        ("PO Date :", "po_date", 151.1),
        ("Delivery Date :", "delivery_date", 166.6),
        ("Shipping Terms :", "shipping_terms", 182.1),
        ("Port of Destination:", "port_of_destination", 197.5),
        ("Term of Payment :", "payment_terms", 213.0),
    )
    for label, key, top in labels:
        _text(c, 309.0, top, label, 10, bold=True)
        _text(c, 408.2, top, str(fields.get(key) or ""), 10, max_width=176)

    _text(c, 29.8, 233.3, "Bill To :", 10, bold=True)
    _block(c, 29.8, 247.6, fields.get("bill_to"), max_width=268)
    if fields.get("gst_number"):
        _text(c, 29.8, 329.1, "GST No :", 10)
        _text(c, 97.0, 329.1, str(fields["gst_number"]), 10, max_width=190)

    _text(c, 309.0, 233.3, "Ship To :", 10, bold=True)
    top = _block(c, 309.0, 247.6, fields.get("ship_to"), max_width=274)
    for label, key in (
        ("Contact Person:", "contact_name"),
        ("Contact No:", "contact_phone"),
        ("Email id:", "contact_email"),
    ):
        if fields.get(key):
            _text(c, 309.0, top, f"{label} {fields[key]}", 10, max_width=274)
            top += 11.5


def _draw_table_head(c: canvas.Canvas, top: float) -> None:
    _rect(c, COL_EDGES[0], top, COL_EDGES[-1], top + TABLE_HEAD_H, GREY)
    _hline(c, COL_EDGES[0], COL_EDGES[-1], top)
    _hline(c, COL_EDGES[0], COL_EDGES[-1], top + TABLE_HEAD_H)
    for edge in COL_EDGES:
        _vline(c, edge, top, top + TABLE_HEAD_H)
    for (x0, x1), label in zip(zip(COL_EDGES, COL_EDGES[1:]), HEAD_LABELS):
        first = top + (TABLE_HEAD_H - len(label) * HEAD_PITCH) / 2
        for i, text in enumerate(label):
            _text(c, (x0 + x1) / 2, first + i * HEAD_PITCH, text, HEAD_SIZE, bold=True, align="center")


def _draw_row(c: canvas.Canvas, row: _Row, top: float) -> None:
    bottom = top + row.height
    _hline(c, COL_EDGES[0], COL_EDGES[-1], top)
    _hline(c, COL_EDGES[0], COL_EDGES[-1], bottom)
    for edge in COL_EDGES:
        _vline(c, edge, top, bottom)
    y = top + TEXT_TOP
    _text(c, (COL_EDGES[0] + COL_EDGES[1]) / 2, y, str(row.number), TEXT_SIZE, align="center")
    _lines_at(c, PART_X, y, row.part_lines)
    _lines_at(c, (COL_EDGES[2] + COL_EDGES[3]) / 2, y, row.type_lines, align="center")
    _lines_at(c, DESC_X, y, row.desc_lines)
    _text(c, QTY_RIGHT, y, row.qty, TEXT_SIZE, align="right")
    _text(c, UNIT_X, y, row.unit, TEXT_SIZE)
    _text(c, PRICE_RIGHT, y, row.price_text, TEXT_SIZE, align="right")
    _text(c, AMOUNT_RIGHT, y, row.amount_text, TEXT_SIZE, align="right")


def _draw_totals(c: canvas.Canvas, top: float, values: list[str], words: str) -> None:
    bottom = top + TOTALS_H
    words_top = bottom - WORDS_H
    boundaries = len(TOTALS_LABELS) + 1
    for i in range(boundaries):
        y = top + i * TOTALS_ROW_H
        # The left-hand side is open above the amount-in-words cell, which runs across the
        # bottom two rows. Rules across the left side only at the top of that cell and at the bottom.
        full_width = i in (boundaries - 3, boundaries - 1)
        _hline(c, COL_EDGES[0] if full_width else TOTALS_X0, TOTALS_X1, y)
    for i, (label, value) in enumerate(zip(TOTALS_LABELS, values)):
        bold = i in (0, len(TOTALS_LABELS) - 1)
        y = top + i * TOTALS_ROW_H + 4.5
        _text(c, LABEL_RIGHT, y, label, 9, bold=bold, align="right")
        _text(c, VALUE_RIGHT, y, value, 9, bold=bold, align="right")
    _vline(c, COL_EDGES[0], top, bottom)
    _vline(c, TOTALS_X0, top, bottom)
    _vline(c, TOTALS_X1, top, bottom)
    _text(c, COL_EDGES[0] + 5, words_top + (WORDS_H - 8) / 2, words, 8, bold=True, max_width=TOTALS_X0 - COL_EDGES[0] - 10)


def _draw_terms(c: canvas.Canvas, top: float, lines: list[tuple[str, bool]]) -> None:
    bottom = top + _terms_height(lines)
    _frame(c, LEFT, top, RIGHT, bottom)
    y = top + TERMS_PAD
    for text, bold in lines:
        _text(c, LEFT + 3, y, text, 10.0 if bold else TERMS_SIZE, bold=bold, max_width=TERMS_W)
        y += HEADING_PITCH if bold else TERMS_PITCH


def _draw_closing(c: canvas.Canvas, top: float, fields: dict, closing: dict) -> None:
    _text(c, 41.0, top, "Quote No.:", 9, bold=True)
    _text(c, 119.0, top, str(fields.get("quote_number") or ""), 9, max_width=200)

    box = top + QUOTE_H
    box_bottom = box + closing["box_height"]
    _frame(c, LEFT, box, RIGHT, box_bottom)
    _text(c, LEFT + 5, box + 5, "Additional Information", 8.5, bold=True)
    for x, lines in zip(INFO_X, closing["columns"]):
        y = box + INFO_HEAD_H
        for text, bold in lines:
            _text(c, x, y, text, INFO_SIZE, bold=bold)
            y += INFO_PITCH

    line_top = box_bottom + AUTH_GAP
    _hline(c, 420.0, RIGHT, line_top)
    _text(c, RIGHT, line_top + 3.5, "Authorized By", 8, align="right")


def _draw_page(c, fields, ops, page_no, page_count, totals, words) -> None:
    for x0, top, x1, bottom in HEADER_BOXES:
        _rect(c, x0, top, x1, bottom, WHITE)
    _rect(c, *LOWER_AREA, WHITE)
    _draw_header(c, fields)

    for op in ops:
        kind = op[0]
        if kind == "table":
            _draw_table_head(c, op[1])
        elif kind == "row":
            _draw_row(c, op[1], op[2])
        elif kind == "totals":
            _draw_totals(c, op[1], totals, words)
        elif kind == "terms":
            _draw_terms(c, op[1], op[2])
        elif kind == "closing":
            _draw_closing(c, op[1], fields, op[2])

    _text(c, (PAGE_W) / 2, 781.6, FOOTER, 9, align="center")
    _text(c, RIGHT, 782.1, f"Page {page_no} of {page_count}", 8, align="right")


def generate_ivalue_infosolutions_limited_po(fields: dict, line_items: list[dict]) -> bytes:
    path = find_template_path(SLUG)
    if path is None:
        raise FileNotFoundError(f"No template PDF found for distributor '{SLUG}'")
    pdf_bytes = path.read_bytes()

    rows = [_Row(number, item) for number, item in enumerate(line_items, start=1)]
    totals, grand = _totals(rows, fields)
    currency = str(fields.get("currency") or "USD")
    words = f"[{currency}] {_amount_words(grand)}"

    term = fields.get("term_months") or next(
        (str(item.get("terms")) for item in line_items if str(item.get("terms") or "").strip()), ""
    )
    terms = _terms_lines({**fields, "term_months": term})
    closing = _closing(fields)
    pages = _plan(rows, terms, closing)

    writer = PdfWriter()
    for page_no, ops in enumerate(pages, start=1):
        page = PdfReader(io.BytesIO(pdf_bytes)).pages[0]
        overlay = _render_overlay(
            PAGE_W,
            PAGE_H,
            lambda c, ops=ops, page_no=page_no: _draw_page(c, fields, ops, page_no, len(pages), totals, words),
        )
        page.merge_page(overlay.pages[0])
        writer.add_page(page)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
