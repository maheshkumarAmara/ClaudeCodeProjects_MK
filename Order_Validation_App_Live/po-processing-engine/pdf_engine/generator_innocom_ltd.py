"""Regenerates Innocom Ltd purchase orders.

The template is a portrait, 2-page printout from Innocom's ERP. Every page has
the same head -- a grey letterhead band with the logo, a white "To:" panel with
the order date, the title "Purchase Order <no> - Authorized" -- followed by a
ruled, alternately shaded items table; the last page ends with a totals box and a
free-text block. This module cuts the head out of template page 1 and draws
everything below it itself (the table's header row, rows, rules, the totals box
and the free-text block), so the table can hold any number of rows: pages are
added as needed, each one repeats the head and the column-header row, and the
totals box and the free-text block go on the last page only.

Behaviors worth knowing:
  - A row's Extended Price is qty x Unit Price (every row of the sample agrees,
    and the printed total is the sum of the rows). The row's printed amount is kept
    while its qty, unit price and TERM are untouched; otherwise it is recomputed.
    "% disc." reduces the unit price used for the amount. Total Price and TOTAL are
    always the sum of the rows; Tax comes from the "tax" field.
  - A row prints its Exchange Rate and TERM (M) on a second line and its
    description on up to two short lines. The source system truncates
    descriptions, so what is printed is what is kept: a long description is
    wrapped to two lines and cut, with nothing added to mark the cut.
  - The template's links (the website, and ERP deep links on every part number,
    the PO number, the vendor number and the sales order) are dropped; only the
    website is relinked, so no link points at the original ERP.
  - Contact email / website text is passed through sandbox_email.
  - Text is drawn in Helvetica at the template's point sizes, not its embedded
    Arial; the original text of the clipped-away part of the page stays in the
    PDF's hidden text layer.
"""

import io
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

import config
from pdf_engine.common import add_links, fit_size, money_2dp
from pdf_engine.extractor import find_template_path
from pdf_engine.generator import _render_overlay
from pdf_engine.paginate import _to_decimal
from sandbox_email import sandbox_text

SLUG = "Innocom Ltd"

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
BLACK = (0.0, 0.0, 0.0)
WHITE = (1.0, 1.0, 1.0)
GREY = (0.92157, 0.92941, 0.93333)
# Arial text sits 0.79 x its size below the character box's top edge.
BASELINE_FACTOR = 0.79
MIN_FONT_SIZE = 4.0

PAGE_W, PAGE_H = 595.0, 842.0
SIZE = 7.6
LINK_SIZE_PAD = 1.5

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")

# --- Template pieces (top-origin y) -----------------------------------------
# The head of template page 1: grey letterhead band with the logo, the white "To:"
# panel and the title. The table starts below it.
HEAD_BOTTOM = 161.5
# Where the old values sit inside the head (cover boxes: x0, top, x1, bottom).
ORDER_DATE_BOX = (411.0, 78.6, 584.0, 90.0)
TITLE_BOX = (111.0, 147.0, 480.0, 161.0)
TO_BOX = (11.0, 87.5, 300.0, 136.0)
WEBSITE_BOX = (440.0, 51.0, 592.0, 61.0)
TO_FIRST_TOP = 89.3
TO_PITCH = 9.3

# --- Items table -----------------------------------------------------------------
HEADER_TOP = 173.2  # top of the column-header row
HEADER_BOTTOM = 197.0
ROW_PITCH = 23.8
FIRST_ROW_TOP = HEADER_BOTTOM
BODY_BOTTOM = 792.0  # lowest a row's bottom rule may sit on a page
# Column edges (x), from the sample's vertical rules.
COL_EDGES = (11.0, 32.5, 111.0, 278.3, 323.1, 383.5, 498.0, 549.7, 583.4)
RULE = 0.58
DESC_ROOM = COL_EDGES[3] - COL_EDGES[2] - 7.0
DESC_LINES = 2
TEXT_TOP_OFFSET = 4.3  # first text line sits this far below the row's top rule
SECOND_LINE_OFFSET = 4.6  # exchange rate / term line, below the first line
DESC_LINE_PITCH = 9.3
HEADER_LABELS = (
    (0, "Line", None), (1, "Part Number", None), (2, "Part Description", None), (3, "Quantity", None),
    (4, "Unit Price", None), (5, "Extended Price", None), (6, "Exchange", "Rate"), (7, "TERM", "(M)"),
)

# Right-hand text edges measured from the sample.
QTY_X = 281.2
UNIT_PRICE_RIGHT = 381.2
AMOUNT_RIGHT = 495.6
RATE_RIGHT = 547.4
TERM_RIGHT = 581.1

# --- Totals box (top-origin; the box's top is placed under the last row) --------
TOTALS_X0, TOTALS_MID, TOTALS_X1 = 355.6, 469.5, 584.0
TOTALS_ROW_H = 14.55
TOTALS_LABELS = ("Total Price", "Tax", "TOTAL")
TOTALS_HEIGHT = TOTALS_ROW_H * 3

# Free-text block, placed relative to the totals box's top. The offsets are the
# sample's own (measured from its totals box): the block starts BESIDE the box (12.6
# below its top), then a gap, then the end user / customer / quote / ship-to /
# contact lines, and the signature block at the bottom right.
TAIL_LEFT = 11.0
SIGNATURE_X = 441.0
TAIL_OFFSETS = {
    "barcode": 12.6, "payment": 21.9, "project": 31.2, "vendor": 40.5, "sales_order": 49.8, "version": 59.1,
    "end_user": 118.4, "end_user_address": 127.7, "customer_po": 137.0, "reseller": 146.3,
    "quote": 164.9, "ship_to": 174.2, "ship_with": 183.4, "incoterms": 192.7,
    "contact": 211.3, "phone": 229.9, "email": 248.5, "website": 257.8,
    "signer": 268.3, "signer_company": 277.6,
}
TAIL_HEIGHT = 277.6 + SIZE  # from the box's top to the bottom of the signature's last line
TOTALS_GAP = 3.0  # the box's top sits this far below the table's last rule
TAIL_MARGIN = 10.0  # keep this much below the signature block


def _fit(text: str, font: str, size: float, max_width: float) -> float:
    return fit_size(text, font, size, max_width, MIN_FONT_SIZE)


def _text(
    c: canvas.Canvas,
    x: float,
    top: float,
    text: str,
    size: float = SIZE,
    *,
    bold: bool = False,
    align: str = "left",
    max_width: float | None = None,
    links: list | None = None,
    link_url: str | None = None,
) -> None:
    """Draws text with its character box's top at `top`. `links` collects a link
    rectangle for the drawn text: a mailto for each email address in it, or
    `link_url` for the whole string."""
    if not text:
        return
    text = text.replace(";", ";")  # Helvetica has no glyph for the source's Greek question mark
    font = FONT_BOLD if bold else FONT
    if max_width is not None:
        size = _fit(text, font, size, max_width)
    width = stringWidth(text, font, size)
    left = x - width if align == "right" else x
    c.saveState()
    c.setFont(font, size)
    c.setFillColorRGB(*BLACK)
    c.drawString(left, PAGE_H - top - size * BASELINE_FACTOR, text)
    c.restoreState()
    if links is not None:
        if link_url:
            links.append((left, top, left + width, top + size + LINK_SIZE_PAD, link_url))
        for match in _EMAIL_RE.finditer(text):
            start = left + stringWidth(text[: match.start()], font, size)
            end = start + stringWidth(match.group(0), font, size)
            links.append((start, top, end, top + size + LINK_SIZE_PAD, f"mailto:{match.group(0)}"))


def _rect(c: canvas.Canvas, x0: float, top: float, x1: float, bottom: float, fill) -> None:
    c.saveState()
    c.setFillColorRGB(*fill)
    c.rect(x0, PAGE_H - bottom, x1 - x0, bottom - top, fill=1, stroke=0)
    c.restoreState()


def _hrule(c: canvas.Canvas, x0: float, x1: float, top: float) -> None:
    _rect(c, x0, top, x1, top + RULE, BLACK)


def _vrule(c: canvas.Canvas, x: float, top: float, bottom: float) -> None:
    _rect(c, x, top, x + RULE, bottom, BLACK)


# --- Number formatting ---------------------------------------------------------------
def _money(value: Decimal) -> str:
    return money_2dp(value)


def _price_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP):,.3f}"


def _rate_text(value) -> str:
    return f"{_to_decimal(value).quantize(Decimal('0.00001'), rounding=ROUND_HALF_UP):.5f}" if str(value or "").strip() else ""


def _term_text(value) -> str:
    return f"{_to_decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}" if str(value or "").strip() else ""


# --- Rows ---------------------------------------------------------------------------
def _wrap(text: str, max_width: float, size: float, max_lines: int) -> list[str]:
    """Words onto at most max_lines lines, cutting what doesn't fit (the source
    system truncates descriptions, and nothing is added to mark the cut)."""
    lines: list[str] = []
    current = ""
    for word in str(text or "").split():
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, FONT, size) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                return lines
    if current:
        lines.append(current)
    return lines[:max_lines]


PART_MIN_SIZE = 6.0  # below this a part number wraps instead of shrinking


def _wrap_chars(text: str, max_width: float, size: float) -> list[str]:
    """Text onto lines by raw character width (a part number is one token)."""
    lines: list[str] = []
    current = ""
    for ch in text:
        if stringWidth(current + ch, FONT, size) <= max_width or not current:
            current += ch
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


class _Row:
    def __init__(self, number: int, item: dict) -> None:
        self.number = number
        self.part_number = str(item.get("part_number") or "")
        self.qty = _to_decimal(item.get("qty"))
        self.unit_price = _to_decimal(item.get("unit_cost"))
        pct = _to_decimal(item.get("pct_disc"))
        basis = f"{item.get('qty', '')}|{item.get('unit_cost', '')}|{item.get('terms', '')}"
        if item.get("amount") not in (None, "") and item.get("amount_basis") == basis and not pct:
            amount = _to_decimal(item["amount"])
        else:
            amount = self.qty * self.unit_price * (Decimal("1") - pct / Decimal("100"))
        self.amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.unit = str(item.get("unit") or "ea")
        self.currency = str(item.get("currency") or "USD")
        self.exchange_rate = _rate_text(item.get("exchange_rate"))
        self.term = _term_text(item.get("terms"))
        description = str(item.get("description") or "")
        printed = item.get("description_lines")
        if printed and item.get("description_basis") == description:
            # Untouched since loaded: redraw the lines as the source printed them.
            self.description_lines = [str(line) for line in printed][:DESC_LINES]
        else:
            self.description_lines = _wrap(description, DESC_ROOM, SIZE, DESC_LINES)


def _draw_header_row(c: canvas.Canvas, top: float) -> None:
    x0, x1 = COL_EDGES[0], COL_EDGES[-1]
    _rect(c, x0, top, x1, top + HEADER_BOTTOM - HEADER_TOP, GREY)
    _hrule(c, x0, x1, top)
    bottom = top + HEADER_BOTTOM - HEADER_TOP
    for x in COL_EDGES:
        _vrule(c, x, top, bottom + RULE)
    for index, first, second in HEADER_LABELS:
        left, right = COL_EDGES[index], COL_EDGES[index + 1]
        centre = (left + right) / 2
        if second:
            _text(c, centre - stringWidth(first, FONT_BOLD, SIZE) / 2, top + 4.4, first, bold=True)
            _text(c, centre - stringWidth(second, FONT_BOLD, SIZE) / 2, top + 13.7, second, bold=True)
        else:
            _text(c, centre - stringWidth(first, FONT_BOLD, SIZE) / 2, top + 9.1, first, bold=True)


def _draw_row(c: canvas.Canvas, row: _Row, top: float, shaded: bool) -> None:
    """One table row: its fill, rules and text lines."""
    bottom = top + ROW_PITCH
    x0, x1 = COL_EDGES[0], COL_EDGES[-1]
    _rect(c, x0, top, x1, bottom, GREY if shaded else WHITE)
    _hrule(c, x0, x1, top)
    for x in COL_EDGES:
        _vrule(c, x, top, bottom + RULE)
    first = top + TEXT_TOP_OFFSET
    edge = COL_EDGES
    _text(c, edge[0] + 3.0, first, str(row.number))
    part_room = edge[2] - edge[1] - 5.0
    if _fit(row.part_number, FONT, SIZE, part_room) >= PART_MIN_SIZE:
        _text(c, edge[1] + 3.0, first, row.part_number, max_width=part_room)
    else:
        # Too long to read when shrunk to one line: wrap mid-token over the row's two lines.
        for i, piece in enumerate(_wrap_chars(row.part_number, part_room, PART_MIN_SIZE)[:2]):
            _text(c, edge[1] + 3.0, first + DESC_LINE_PITCH * i, piece, PART_MIN_SIZE, max_width=part_room)
    for i, line in enumerate(row.description_lines):
        _text(c, edge[2] + 3.0, first + DESC_LINE_PITCH * i, line)
    _text(c, QTY_X, first, f"{_money(row.qty)} {row.unit}", max_width=edge[4] - QTY_X - 2.0)
    _text(c, UNIT_PRICE_RIGHT, first, f"{row.currency} {_price_text(row.unit_price)}", align="right", max_width=edge[5] - edge[4] - 4.0)
    _text(c, AMOUNT_RIGHT, first, _money(row.amount), align="right", max_width=edge[6] - edge[5] - 6.0)
    _text(c, RATE_RIGHT, first + SECOND_LINE_OFFSET, row.exchange_rate, align="right")
    _text(c, TERM_RIGHT, first + SECOND_LINE_OFFSET, row.term, align="right")


# --- Head (page 1 of the template, drawn on every page) ---------------------------------
def _cover(c: canvas.Canvas, box: tuple[float, float, float, float], fill=WHITE) -> None:
    _rect(c, box[0], box[1], box[2], box[3], fill)


def _draw_head(c: canvas.Canvas, fields: dict, links: list) -> None:
    _cover(c, ORDER_DATE_BOX)
    _text(c, 413.0, 80.0, f"Order Date: {fields.get('order_date') or ''}", bold=True)

    _cover(c, TO_BOX)
    lines = [ln for ln in str(fields.get("to_block") or "").split("\n")]
    for i, line in enumerate(lines):
        _text(c, 11.0, TO_FIRST_TOP + TO_PITCH * i, sandbox_text(line), bold=True, links=links)

    po = str(fields.get("po_number") or "")
    status = str(fields.get("po_status") or "Authorized")
    title = f"Purchase Order {po} - {status}"
    _cover(c, TITLE_BOX)
    width = stringWidth(title, FONT, 10.5)
    left = (PAGE_W - width) / 2 - 1.0
    _text(c, left, 149.8, title, 10.5)
    c.saveState()
    c.setStrokeColorRGB(*BLACK)
    c.setLineWidth(0.5)
    c.line(left, PAGE_H - 160.0, left + width, PAGE_H - 160.0)
    c.restoreState()

    _cover(c, WEBSITE_BOX, GREY)
    _text(c, 588.0, 51.6, "https://www.innocom.co.il", bold=True, align="right", links=links, link_url="https://www.innocom.co.il")


# --- Tail (last page) -------------------------------------------------------------------
def _draw_totals(c: canvas.Canvas, top: float, total_price: Decimal, tax: Decimal, total: Decimal, currency: str) -> None:
    values = (_money(total_price), _money(tax), f"{currency} {_money(total)}")
    for i, (label, value) in enumerate(zip(TOTALS_LABELS, values)):
        row_top = top + TOTALS_ROW_H * i
        _rect(c, TOTALS_X0, row_top, TOTALS_X1, row_top + TOTALS_ROW_H, WHITE)
        _hrule(c, TOTALS_X0, TOTALS_X1, row_top)
        _vrule(c, TOTALS_X0, row_top, row_top + TOTALS_ROW_H + RULE)
        _vrule(c, TOTALS_MID, row_top, row_top + TOTALS_ROW_H + RULE)
        _vrule(c, TOTALS_X1 - RULE, row_top, row_top + TOTALS_ROW_H + RULE)
        _text(c, TOTALS_X0 + 3.0, row_top + 3.7, label, bold=True)
        _text(c, TOTALS_X1 - 3.0, row_top + 3.7, value, bold=True, align="right", max_width=TOTALS_X1 - TOTALS_MID - 8.0)
    _hrule(c, TOTALS_X0, TOTALS_X1, top + TOTALS_HEIGHT)


def _draw_tail(c: canvas.Canvas, fields: dict, box_top: float, links: list) -> None:
    """The free-text block, each line at its sample offset from the totals box's top.
    A line is (text, bold label) -- the label prints bold, the value regular."""
    f = {k: str(v if v is not None else "") for k, v in fields.items()}
    website = f.get("contact_website", "")
    lines = {
        "barcode": ("Bar Code of Doc No.: ", f"*{f.get('po_number', '')}*"),
        "payment": ("Payment Terms: ", f.get("payment_terms", "")),
        "project": ("Project: ", f.get("project", "")),
        "vendor": ("Vendor Number: ", f.get("vendor_number", "")),
        "sales_order": ("Sales Order: ", f.get("sales_order", "")),
        "version": ("Current Version: ", f.get("current_version", "")),
        "end_user": ("End User: ", f.get("end_user", "")),
        "end_user_address": ("End User: ", f.get("end_user_address", "")),
        "customer_po": ("Customer PO: ", f.get("customer_po", "")),
        "reseller": ("Reseller Name: ", f.get("reseller_name", "")),
        "quote": ("Quote : ", f.get("quote_number", "")),
        "ship_to": ("", f.get("ship_to_instruction", "")),
        "ship_with": ("", f.get("ship_with_instruction", "")),
        "incoterms": ("", f.get("incoterms", "")),
        "contact": ("", f.get("contact_name", "")),
        "phone": ("Phone: ", f.get("contact_phone", "")),
        "email": ("Email: ", sandbox_text(f.get("contact_email", ""))),
        "website": ("", sandbox_text(website)),
    }
    # Only these labels are bold in the sample; the free-text lines above are regular.
    bold_labels = {"end_user", "end_user_address", "customer_po", "reseller", "quote"}
    for key, (label, value) in lines.items():
        top = box_top + TAIL_OFFSETS[key]
        if key == "reseller":
            _text(c, TAIL_LEFT, top, f"{label}{value}", bold=True)
            continue
        label_width = stringWidth(label, FONT_BOLD if key in bold_labels else FONT, SIZE)
        _text(c, TAIL_LEFT, top, label, bold=key in bold_labels)
        # Lines beside the totals box (the first six) must stop short of it.
        room = (TOTALS_X0 - 6.0 - TAIL_LEFT - label_width) if TAIL_OFFSETS[key] < TOTALS_HEIGHT + 12.0 else None
        _text(
            c,
            TAIL_LEFT + label_width,
            top,
            value,
            max_width=room,
            links=links if key in ("email", "website") else None,
            link_url=f"https://{website}" if key == "website" and website else None,
        )
    _text(c, SIGNATURE_X, box_top + TAIL_OFFSETS["signer"], f.get("signer_name", ""))
    _text(c, SIGNATURE_X, box_top + TAIL_OFFSETS["signer_company"], f.get("signer_company", ""))


# --- Page frame (the grey outline around the white content panel) -----------------------
def _draw_frame(c: canvas.Canvas) -> None:
    """Below the head the page is a grey frame around a white content panel (the
    head, cut from template page 1, carries its own top part)."""
    _rect(c, 0.0, HEAD_BOTTOM, PAGE_W, PAGE_H, WHITE)
    _rect(c, 0.6, HEAD_BOTTOM, 594.4, PAGE_H, GREY)
    _rect(c, 6.4, HEAD_BOTTOM, 588.6, PAGE_H, GREY)
    _rect(c, 7.0, HEAD_BOTTOM, 588.0, PAGE_H, WHITE)
    _rect(c, 10.5, HEAD_BOTTOM, 584.5, PAGE_H, WHITE)


# --- Pagination ---------------------------------------------------------------------------
def _paginate(count: int) -> list[dict]:
    """Page specs: {"first", "last", "totals": bool}. The table's rows run from
    FIRST_ROW_TOP; the totals box (placed TOTALS_GAP under the last row) and the
    free-text block need TAIL_HEIGHT below that, so they go on the last page only. A
    page that continues leaves at least one row for the next one, so the totals never
    sit under an empty table."""
    rows_per_page = int((BODY_BOTTOM - FIRST_ROW_TOP) / ROW_PITCH + 1e-6)
    rows_with_tail = int((PAGE_H - TAIL_MARGIN - TAIL_HEIGHT - TOTALS_GAP - FIRST_ROW_TOP) / ROW_PITCH + 1e-6)
    pages: list[dict] = []
    start = 0
    while True:
        remaining = count - start
        if remaining <= rows_with_tail:
            pages.append({"first": start, "last": count, "totals": True})
            return pages
        take = min(rows_per_page, remaining - 1)
        pages.append({"first": start, "last": start + take, "totals": False})
        start += take


# --- Template head ---------------------------------------------------------------------------
def _clip_head(template_bytes: bytes) -> PageObject:
    """Template page 1 limited to the head (y 0..HEAD_BOTTOM), with its link
    annotations removed so none points at the original addresses."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(template_bytes)))
    page = writer.pages[0]
    data = page.get_contents().get_data()
    stream = DecodedStreamObject()
    stream.set_data(f"q 0 {PAGE_H - HEAD_BOTTOM:.3f} {PAGE_W:.3f} {HEAD_BOTTOM:.3f} re W n\n".encode() + data + b"\nQ")
    page[NameObject("/Contents")] = writer._add_object(stream)
    if "/Annots" in page:
        del page["/Annots"]
    return page


def _add_links(writer: PdfWriter, links: list) -> None:
    add_links(writer, links, PAGE_H)


def generate_innocom_ltd_po(fields: dict, line_items: list[dict]) -> bytes:
    path = find_template_path(SLUG)
    if path is None:
        raise FileNotFoundError(f"No template PDF found for distributor '{SLUG}'")

    rows = [
        _Row(0, item)
        for item in line_items
        if item and (item.get("part_number") or item.get("description"))
    ]
    for number, row in enumerate(rows, start=1):
        row.number = number
    total_price = sum((r.amount for r in rows), Decimal("0"))
    tax = _to_decimal(fields.get("tax")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = total_price + tax
    currency = str(fields.get("currency") or (rows[0].currency if rows else "USD") or "USD")
    pages = _paginate(len(rows))

    template_bytes = path.read_bytes()
    writer = PdfWriter()
    for page_spec in pages:
        links: list = []
        page_rows = rows[page_spec["first"] : page_spec["last"]]

        def draw(c: canvas.Canvas, spec=page_spec, page_rows=page_rows) -> None:
            _draw_head(c, fields, links)
            _draw_frame(c)
            _draw_header_row(c, HEADER_TOP)
            top = FIRST_ROW_TOP
            for i, row in enumerate(page_rows):
                _draw_row(c, row, top, shaded=(row.number % 2 == 0))
                top += ROW_PITCH
            _hrule(c, COL_EDGES[0], COL_EDGES[-1], top)
            if spec["totals"]:
                box_top = top + TOTALS_GAP
                _draw_totals(c, box_top, total_price, tax, total, currency)
                _draw_tail(c, fields, box_top, links)

        overlay = _render_overlay(PAGE_W, PAGE_H, draw)
        page = PageObject.create_blank_page(width=PAGE_W, height=PAGE_H)
        page.merge_page(_clip_head(template_bytes))
        page.merge_page(overlay.pages[0])
        writer.add_page(page)
        _add_links(writer, links)

    output = io.BytesIO()
    writer.write(output)
    pdf_output = output.getvalue()

    po_number = (fields.get("po_number") or "PO").strip().replace("/", "-").replace(" ", "_") or "PO"
    out_dir = Path(config.GENERATED_DIR) / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{po_number}.pdf").write_bytes(pdf_output)

    return pdf_output
