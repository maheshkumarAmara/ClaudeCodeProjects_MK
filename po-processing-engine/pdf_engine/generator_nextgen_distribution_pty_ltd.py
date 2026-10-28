"""Regenerates NextGen Distribution Pty Ltd purchase orders.

The template is a flowing, landscape document: page 1 carries the header values,
the delivery and invoice address blocks and the first items; middle pages repeat
the items table; the last page carries the partner / payment / shipping / quote
footer and the "Order Total" bar. Rows have no rules between them and their
height depends on how many lines their part number or description wraps to, so
this module keeps the template's artwork, clears the body of each page, and
redraws the header values, the items (paginating them itself) and the footer.

Behaviors worth knowing:
  - Items are grouped under their `section` heading ("Expansion Quote",
    "Renewal Quote"). A row with no section stays in the previous row's section,
    and rows with no section at all (e.g. pulled from a Quote) print no headings.
    A heading is not repeated when a section continues on the next page, as in
    the sample.
  - The Term Qty / Term / Start / End columns come from the row's `terms` text
    ("18 Months (2/01/2026 - 30/06/2027)", "N/A", or a bare "12", which means
    months), so editing `terms` in the form changes what prints. The structured
    `term_qty` / `term_unit` / `start_date` / `end_date` values are only used
    when `terms` is empty.
  - A row keeps its printed `amount` only while its qty, unit price and terms
    are untouched (`amount_basis` says what the amount was printed for).
    Otherwise it is recomputed as qty x unit price x term months -- the sample's
    own amounts are consistent with that to within rounding of the unit price.
  - The Order Total is always recomputed from the rows; only its currency code
    is taken from the `total` field. (The sample's printed total differs from
    the sum of its own rows by 4.07.)
  - Part numbers wrap mid-token and descriptions wrap by words at the same
    widths the sample uses, so it reproduces the sample's own line breaks.
  - If the footer does not fit under the last row it moves onto a page of its
    own; "Page No. N of M" is renumbered on every page.
  - Fields missing from the request leave that value blank (the form always
    sends them all).
  - Text is drawn in Helvetica, not the template's embedded Arial subset, which
    can't be reused for new characters.
"""

import io
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from pypdf import PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

import config
from pdf_engine.extractor import find_template_path
from pdf_engine.generator import _fresh_page, _render_overlay
from pdf_engine.paginate import wrap_chars, wrap_text

SLUG = "NextGen Distribution Pty Ltd"

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
# pdfplumber's `top` is the top of a box whose bottom sits one descent
# (0.207 em for Helvetica) below the baseline.
BASELINE_FACTOR = 0.793
MIN_FONT_SIZE = 4.0

WHITE = (1.0, 1.0, 1.0)
BLACK = (0.0, 0.0, 0.0)
GREY = (0.753, 0.753, 0.753)

# Template page indexes in the NextGen sample.
TEMPLATE_FIRST = 0  # header values, address blocks, first items
TEMPLATE_CONT = 1  # continuation items page
TEMPLATE_LAST = 2  # last items page, with the footer area and the Order Total bar

# --- Header values (one row under the labels) -----------------------------------
# key -> (x the value is centered on, left edge of its cell, right edge of its cell).
# Values print centered under their labels, not under the cell's middle.
HEADER_TEXT_SIZE = 8.1
HEADER_TEXT_TOP = 191.1
HEADER_COVER = (188.7, 198.3)  # top, bottom of the value row's inside
HEADER_VALUES = {
    "supplier_no": (104.6, 22.9, 182.9),
    "supplier_contact": (264.9, 182.9, 345.9),
    "buyer": (420.2, 345.9, 494.4),
    "po_date": (577.1, 494.4, 651.1),
    "po_number": (730.1, 651.1, 805.3),
}
CELL_INSET = 0.8

# --- Delivery (left) and invoice (right) address blocks ---------------------------
BLOCK_TEXT_SIZE = 8.1
BLOCK_LINE_PITCH = 11.25
DELIVERY_BOX = (23.5, 213.5, 415.9, 288.4)  # left, top, right, bottom (clear of the rules)
DELIVERY_X = 38.4
DELIVERY_FIRST_TOP = 216.9
INVOICE_BOX = (417.0, 213.5, 804.6, 288.4)
INVOICE_X = 440.4
INVOICE_VALUE_X = {"Email:": 476.4, "Phone:": 477.3}
INVOICE_FIRST_TOP = 219.9
BLOCK_TEXT_PAD = 12.0  # keep text this far from the box's right edge

# --- Items table -----------------------------------------------------------------
ITEM_SIZE = 7.2
LINE_HEIGHT = 10.5  # pitch of wrapped lines inside a row (and of one-line rows)
HEADING_ADVANCE = 15.2  # from the cursor to the first row under a section heading
HEADING_OFFSET = 0.7  # a heading sits this far below the cursor
FIRST_ROW_TOP = 335.3  # cursor at the start of page 1's items area
CONT_ROW_TOP = 50.2  # cursor at the start of the other pages' items area
BODY_BOTTOM = 559.3  # the items box's bottom rule is at about 559.9
FOOTER_GAP = 1.8  # from the last row's end to the "Partner:" line
BAR_TOP = 543.0

# Body areas to clear on each template page: left, top, right, bottom (inside the box rules).
CLEAR_LEFT, CLEAR_RIGHT = 23.5, 804.6
CLEAR_TOP_FIRST = 333.6
CLEAR_TOP_CONT = 48.4

X_PART = 26.4
X_DESCRIPTION = 98.4
X_START = 314.4
X_END = 362.4
R_QTY = 462.1
R_TERM_QTY = 494.3
X_TERM_UNIT = 500.4
X_BILLING = 554.4
R_UNIT_PRICE = 717.8
R_TOTAL = 800.0

PART_WIDTH = 63.6  # "RS-BT-NDA-PE-PP" (63.2) fits on one line; "RA-PS-CON-RMOT" (64.0) wraps
DESCRIPTION_WIDTH = 187.0  # longest line the sample keeps whole is 185.7; shortest it wraps is 188.9
DATE_WIDTH = 46.0
TERM_UNIT_WIDTH = 50.0
BILLING_WIDTH = 120.0
DEFAULT_BILLING_TERM = "Pay in Full in Advance"

# Footer lines: key -> (offset from the "Partner:" line, text builder). Offsets are
# measured from the sample; the gaps between lines are blank lines in the original.
FOOTER_LINES = (
    ("partner", 0.0),
    ("payment_terms", 21.0),
    ("end_user", 32.3),
    ("end_user_po", 53.3),
    ("shipping_terms", 74.3),
    ("quote_number", 95.3),
    ("acceptance", 105.5),
)
FOOTER_HEIGHT = 105.5 + ITEM_SIZE

# --- Order Total bar (last page) ---------------------------------------------------
BAR_FRAME = (23.1, 542.9, 520.6)  # left, top, right of the grey label cell
BAR_LABEL_RIGHT = 518.6
BAR_LABEL_WIDTH = 103.0  # the sample's label is set in a narrow face
BAR_TEXT_TOP = 547.5
BAR_TEXT_SIZE = 8.9
NARROW = 0.82  # horizontal scale for the narrow faces (Page No., USD, total)
BAR_CURRENCY_X = 534.5
BAR_TOTAL_RIGHT = 800.5
BAR_VALUE_COVER = (521.5, 543.8, 804.5, 558.7)  # left, top, right, bottom

PAGE_NUMBER_CENTER = 415.3
PAGE_NUMBER_TOP = 565.8
PAGE_NUMBER_SIZE = 7.9
PAGE_NUMBER_COVER = (375.0, 565.0, 456.0, 575.5)


def _num(value) -> Decimal:
    """Plain numbers as the form holds them; thousands commas are ignored (the
    sample prints US-style numbers: "2,380.0000", "5,000")."""
    text = str(value if value is not None else "").replace(",", "").strip()
    try:
        return Decimal(text) if text else Decimal("0")
    except InvalidOperation:
        return Decimal("0")


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def _unit_price_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP):,.4f}"


def _qty_text(value: Decimal) -> str:
    return f"{int(value):,}" if value == value.to_integral_value() else f"{value.normalize():,f}"


@dataclass
class _Term:
    qty: str = ""
    unit: str = ""
    start: str = ""
    end: str = ""

    @property
    def months(self) -> Decimal:
        return _num(self.qty) if self.unit.strip().lower().startswith("month") else Decimal("1")


def _parse_term(item: dict) -> _Term:
    """Reads the Term columns from the row's `terms` text."""
    terms = str(item.get("terms") or "").strip()
    if not terms:
        return _Term(
            str(item.get("term_qty") or ""),
            str(item.get("term_unit") or ""),
            str(item.get("start_date") or ""),
            str(item.get("end_date") or ""),
        )
    match = re.match(r"^(?P<body>[^()]*?)\s*(?:\((?P<dates>[^()]*)\))?\s*$", terms)
    body = (match.group("body") if match else terms).strip()
    dates = (match.group("dates") or "") if match else ""
    start, end = "", ""
    if dates:
        parts = re.split(r"\s+-\s+", dates.strip(), maxsplit=1)
        start = parts[0].strip()
        end = parts[1].strip() if len(parts) > 1 else ""

    first, _, rest = body.partition(" ")
    if re.fullmatch(r"\d+(?:\.\d+)?", first):
        return _Term(first, rest.strip() or "Months", start, end)  # a bare "12" is 12 months
    if body.upper() == "N/A":
        return _Term(str(item.get("term_qty") or "1"), "N/A", start, end)
    return _Term(str(item.get("term_qty") or ""), body, start, end)


def _amount_basis(item: dict) -> str:
    return f"{item.get('qty', '')}|{item.get('unit_cost', '')}|{item.get('terms', '')}"


@dataclass
class _Row:
    item: dict
    section: str
    term: _Term
    part_lines: list[str]
    description_lines: list[str]
    qty: Decimal
    unit_price: Decimal
    amount: Decimal
    heading: str | None = None  # set when a section heading is printed above this row

    @property
    def lines(self) -> int:
        return max(len(self.part_lines), len(self.description_lines), 1)

    @property
    def height(self) -> float:
        return self.lines * LINE_HEIGHT


@dataclass
class _PageSpec:
    rows: list[_Row] = field(default_factory=list)
    tops: list[float] = field(default_factory=list)  # each row's top (numeric cells)
    heading_tops: dict[int, float] = field(default_factory=dict)  # row index -> heading top
    footer_top: float | None = None  # set on the last page
    cursor: float = 0.0


def _build_rows(line_items: list[dict]) -> list[_Row]:
    rows: list[_Row] = []
    section = ""
    for item in line_items:
        if not item or not (item.get("part_number") or item.get("description")):
            continue
        section = str(item.get("section") or "").strip() or section
        term = _parse_term(item)
        qty = _num(item.get("qty"))
        unit_price = _num(item.get("unit_cost"))
        if item.get("amount") not in (None, "") and item.get("amount_basis") == _amount_basis(item):
            amount = _num(item["amount"])
        else:
            amount = qty * unit_price * term.months
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rows.append(
            _Row(
                item=item,
                section=section,
                term=term,
                part_lines=wrap_chars(str(item.get("part_number") or ""), PART_WIDTH, ITEM_SIZE),
                description_lines=wrap_text(str(item.get("description") or ""), DESCRIPTION_WIDTH, ITEM_SIZE),
                qty=qty,
                unit_price=unit_price,
                amount=amount,
            )
        )
    return rows


def _paginate(rows: list[_Row]) -> list[_PageSpec]:
    pages = [_PageSpec(cursor=FIRST_ROW_TOP)]
    printed_section = ""
    for row in rows:
        page = pages[-1]
        heading = row.section if row.section and row.section != printed_section else None
        need = row.height + (HEADING_ADVANCE if heading else 0.0)
        if page.rows and page.cursor + need > BODY_BOTTOM:
            page = _PageSpec(cursor=CONT_ROW_TOP)
            pages.append(page)
        if page.cursor + need > BODY_BOTTOM:
            raise ValueError(
                f"Line item '{row.item.get('part_number') or row.item.get('description')}' is too tall to fit on a page."
            )
        index = len(page.rows)
        if heading:
            page.heading_tops[index] = page.cursor + HEADING_OFFSET
            page.cursor += HEADING_ADVANCE
            printed_section = row.section
            row.heading = heading
        page.rows.append(row)
        page.tops.append(page.cursor)
        page.cursor += row.height

    last = pages[-1]
    if last.cursor + FOOTER_GAP + FOOTER_HEIGHT > BAR_TOP - 0.5:
        last = _PageSpec(cursor=CONT_ROW_TOP)  # the footer gets a page of its own
        pages.append(last)
    last.footer_top = last.cursor + FOOTER_GAP
    return pages


def _cover(c: canvas.Canvas, page_height: float, left: float, top: float, right: float, bottom: float) -> None:
    c.saveState()
    c.setFillColorRGB(*WHITE)
    c.rect(left, page_height - bottom, right - left, bottom - top, fill=1, stroke=0)
    c.restoreState()


def _fit(text: str, font: str, size: float, max_width: float) -> float:
    while size > MIN_FONT_SIZE and stringWidth(text, font, size) > max_width:
        size -= 0.1
    return size


def _text(
    c: canvas.Canvas,
    page_height: float,
    x: float,
    top: float,
    text: str,
    size: float = ITEM_SIZE,
    *,
    font: str = FONT,
    align: str = "left",
    scale: float = 1.0,
) -> None:
    if not text:
        return
    width = stringWidth(text, font, size) * scale
    if align == "right":
        x -= width
    elif align == "center":
        x -= width / 2
    c.saveState()
    c.setFont(font, size)
    c.setFillColorRGB(*BLACK)
    c.translate(x, page_height - top - size * BASELINE_FACTOR)
    c.scale(scale, 1.0)
    c.drawString(0, 0, text)
    c.restoreState()


def _fitted_text(
    c: canvas.Canvas, page_height: float, x: float, top: float, text: str, size: float, max_width: float, **kwargs
) -> None:
    _text(c, page_height, x, top, text, _fit(text, kwargs.get("font", FONT), size, max_width), **kwargs)


def _draw_header_values(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    cover_top, cover_bottom = HEADER_COVER
    for key, (center, left, right) in HEADER_VALUES.items():
        _cover(c, page_height, left + CELL_INSET, cover_top, right - CELL_INSET, cover_bottom)
        text = str(fields.get(key) or "")
        room = right - left - 2 * CELL_INSET - 4.0
        size = _fit(text, FONT, HEADER_TEXT_SIZE, room)
        _text(c, page_height, center, HEADER_TEXT_TOP, text, size, align="center")


def _address_lines(value, max_width: float) -> list[str]:
    """One printed line per line of the value, word-wrapped to the box."""
    lines: list[str] = []
    for part in str(value or "").replace("\r", "").split("\n"):
        part = part.strip()
        if part:
            lines.extend(wrap_text(part, max_width, BLOCK_TEXT_SIZE))
    return lines


def _block_pitch(count: int, first_top: float, box_bottom: float) -> float:
    """Line pitch that keeps `count` lines inside the box (the sample's own pitch if they fit)."""
    if count <= 1:
        return BLOCK_LINE_PITCH
    room = box_bottom - 1.0 - BLOCK_TEXT_SIZE - first_top
    return min(BLOCK_LINE_PITCH, room / (count - 1))


def _draw_delivery_block(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    left, top, right, bottom = DELIVERY_BOX
    _cover(c, page_height, left, top, right, bottom)
    room = right - DELIVERY_X - BLOCK_TEXT_PAD
    lines = [str(fields.get("delivery_name") or "").strip()]
    lines += _address_lines(fields.get("delivery_address"), room)
    lines.append(str(fields.get("delivery_locality") or "").strip())
    contact = str(fields.get("delivery_contact") or "").strip()
    email = str(fields.get("delivery_email") or "").strip()
    if contact:
        lines.append(f"Contact: {contact}")
    if email:
        lines.append(f"Email: {email}")
    lines = [line for line in lines if line]
    pitch = _block_pitch(len(lines), DELIVERY_FIRST_TOP, bottom)
    for index, line in enumerate(lines):
        _fitted_text(c, page_height, DELIVERY_X, DELIVERY_FIRST_TOP + index * pitch, line, BLOCK_TEXT_SIZE, room)


def _draw_invoice_block(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    left, top, right, bottom = INVOICE_BOX
    _cover(c, page_height, left, top, right, bottom)
    room = right - INVOICE_X - BLOCK_TEXT_PAD
    lines: list[tuple[str, str]] = [("", str(fields.get("invoice_name") or "").strip())]
    lines += [("", line) for line in _address_lines(fields.get("invoice_address"), room)]
    for label, key in (("Email:", "invoice_email"), ("Phone:", "invoice_phone")):
        value = str(fields.get(key) or "").strip()
        if value:
            lines.append((label, value))
    lines = [(label, value) for label, value in lines if value]
    pitch = _block_pitch(len(lines), INVOICE_FIRST_TOP, bottom)
    for index, (label, value) in enumerate(lines):
        line_top = INVOICE_FIRST_TOP + index * pitch
        if label:
            _text(c, page_height, INVOICE_X, line_top, label, BLOCK_TEXT_SIZE)
            value_x = INVOICE_VALUE_X[label]
            _fitted_text(c, page_height, value_x, line_top, value, BLOCK_TEXT_SIZE, right - value_x - BLOCK_TEXT_PAD)
        else:
            _fitted_text(c, page_height, INVOICE_X, line_top, value, BLOCK_TEXT_SIZE, room)


def _draw_row(c: canvas.Canvas, page_height: float, row: _Row, top: float) -> None:
    for index, line in enumerate(row.part_lines):
        _text(c, page_height, X_PART, top + 0.5 + index * LINE_HEIGHT, line)
    for index, line in enumerate(row.description_lines):
        _text(c, page_height, X_DESCRIPTION, top + 1.0 + index * LINE_HEIGHT, line)

    term = row.term
    _fitted_text(c, page_height, X_START, top, term.start, ITEM_SIZE, DATE_WIDTH)
    _fitted_text(c, page_height, X_END, top, term.end, ITEM_SIZE, DATE_WIDTH)
    _text(c, page_height, R_QTY, top, _qty_text(row.qty), align="right")
    _text(c, page_height, R_TERM_QTY, top, term.qty, align="right")
    _fitted_text(c, page_height, X_TERM_UNIT, top, term.unit, ITEM_SIZE, TERM_UNIT_WIDTH)
    billing = str(row.item.get("billing_term") or DEFAULT_BILLING_TERM)
    _fitted_text(c, page_height, X_BILLING, top, billing, ITEM_SIZE, BILLING_WIDTH)
    _text(c, page_height, R_UNIT_PRICE, top, _unit_price_text(row.unit_price), align="right")
    _text(c, page_height, R_TOTAL, top, _money(row.amount), align="right")


def _footer_texts(fields: dict) -> dict[str, str]:
    def value(key: str) -> str:
        return str(fields.get(key) or "").strip()

    texts = {
        "partner": f"Partner:  {value('partner')}" if value("partner") else "",
        "payment_terms": f"Payment Terms: {value('payment_terms')}" if value("payment_terms") else "",
        "end_user": f"EU: {value('end_user')}" if value("end_user") else "",
        "end_user_po": f"EU PO# {value('end_user_po')}" if value("end_user_po") else "",
        "shipping_terms": f"Shipping Terms: {value('shipping_terms')}" if value("shipping_terms") else "",
        "quote_number": f"Rubrik Quote:  {value('quote_number')}" if value("quote_number") else "",
        "acceptance": "",
    }
    if value("quote_number"):
        dated = f" dated {value('quote_date')}" if value("quote_date") else ""
        texts["acceptance"] = (
            f"Nextgen accepts all additional terms and payment schedule mentioned on {value('quote_number')}{dated}"
        )
    return texts


def _draw_footer(c: canvas.Canvas, page_height: float, fields: dict, top: float) -> None:
    texts = _footer_texts(fields)
    for key, offset in FOOTER_LINES:
        _text(c, page_height, 25.4, top + offset, texts[key])


def _currency(fields: dict) -> str:
    match = re.match(r"\s*([A-Za-z]{3})\b", str(fields.get("total") or ""))
    return match.group(1).upper() if match else "USD"


def _draw_total_bar(c: canvas.Canvas, page_height: float, fields: dict, total: Decimal, draw_frame: bool) -> None:
    """The Order Total bar. Template page 3 already has the grey label cell and
    its rules; any other last page needs the whole bar drawn."""
    if draw_frame:
        left, top, right = BAR_FRAME
        bottom = 559.6  # up to the items box's bottom rule on page 1
        c.saveState()
        c.setFillColorRGB(*GREY)
        c.rect(left, page_height - bottom, right - left, bottom - top, fill=1, stroke=0)
        c.setStrokeColorRGB(*BLACK)
        c.setLineWidth(0.5)
        c.line(22.6, page_height - 543.2, 804.9, page_height - 543.2)
        c.line(520.9, page_height - 543.4, 520.9, page_height - 559.9)
        c.restoreState()
        label = "Order Total (GST Exclusive)"
        scale = BAR_LABEL_WIDTH / stringWidth(label, FONT_BOLD, BAR_TEXT_SIZE)
        _text(c, page_height, BAR_LABEL_RIGHT, BAR_TEXT_TOP, label, BAR_TEXT_SIZE, font=FONT_BOLD, align="right", scale=scale)
    else:
        _cover(c, page_height, *BAR_VALUE_COVER)
    _text(c, page_height, BAR_CURRENCY_X, BAR_TEXT_TOP, _currency(fields), BAR_TEXT_SIZE, font=FONT_BOLD, scale=NARROW)
    _text(
        c, page_height, BAR_TOTAL_RIGHT, BAR_TEXT_TOP, _money(total), BAR_TEXT_SIZE, font=FONT_BOLD, align="right", scale=NARROW
    )


def _draw_page_number(c: canvas.Canvas, page_height: float, number: int, total_pages: int) -> None:
    _cover(c, page_height, *PAGE_NUMBER_COVER)
    _text(
        c,
        page_height,
        PAGE_NUMBER_CENTER,
        PAGE_NUMBER_TOP,
        f"Page No. {number} of {total_pages}",
        PAGE_NUMBER_SIZE,
        align="center",
        scale=NARROW,
    )


def _draw_page(
    c: canvas.Canvas,
    page_height: float,
    spec: _PageSpec,
    number: int,
    total_pages: int,
    fields: dict,
    grand_total: Decimal,
) -> None:
    is_first = number == 1
    is_last = number == total_pages

    if is_first:
        _draw_header_values(c, page_height, fields)
        _draw_delivery_block(c, page_height, fields)
        _draw_invoice_block(c, page_height, fields)

    clear_top = CLEAR_TOP_FIRST if is_first else CLEAR_TOP_CONT
    clear_bottom = BAR_TOP - 0.5 if is_last and not is_first else BODY_BOTTOM
    if is_last and is_first:
        clear_bottom = BAR_TOP - 0.5
    _cover(c, page_height, CLEAR_LEFT, clear_top, CLEAR_RIGHT, clear_bottom)

    for index, (row, top) in enumerate(zip(spec.rows, spec.tops)):
        if index in spec.heading_tops:
            _text(c, page_height, 25.4, spec.heading_tops[index], row.heading or "")
        _draw_row(c, page_height, row, top)

    if is_last:
        _draw_footer(c, page_height, fields, spec.footer_top)
        _draw_total_bar(c, page_height, fields, grand_total, draw_frame=is_first)
    _draw_page_number(c, page_height, number, total_pages)


def generate_nextgen_distribution_pty_ltd_po(fields: dict, line_items: list[dict]) -> bytes:
    path = find_template_path(SLUG)
    if path is None:
        raise FileNotFoundError(f"No template PDF found for distributor '{SLUG}'")

    rows = _build_rows(line_items)
    grand_total = sum((row.amount for row in rows), Decimal("0"))
    pages = _paginate(rows)

    pdf_bytes = path.read_bytes()
    writer = PdfWriter()
    for number, spec in enumerate(pages, start=1):
        if number == 1:
            template = TEMPLATE_FIRST
        elif number == len(pages):
            template = TEMPLATE_LAST
        else:
            template = TEMPLATE_CONT
        page = _fresh_page(pdf_bytes, template)
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        overlay = _render_overlay(
            width,
            height,
            lambda c, s=spec, n=number, h=height: _draw_page(c, h, s, n, len(pages), fields, grand_total),
        )
        page.merge_page(overlay.pages[0])
        writer.add_page(page)

    output = io.BytesIO()
    writer.write(output)
    pdf_output = output.getvalue()

    po_number = (fields.get("po_number") or "PO").strip().replace("/", "-").replace(" ", "_") or "PO"
    out_dir = Path(config.GENERATED_DIR) / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{po_number}.pdf").write_bytes(pdf_output)

    return pdf_output
