"""Regenerates Exclusive Networks (Norway) purchase orders.

The template is a portrait, 2-page, flowing document: a letterhead and header on
page 1, then an items table with no ruling (item rows sit in white space under a
grey column-header band), a totals block on the last page, and a footer strip on
every page. This module treats the template as pieces cut out of its pages --
the page-1 head (letterhead, header cells, address blocks, down to the items
header band), the continuation head (letterhead + repeated header band, from
page 2), the totals block, and the footer strip -- and builds each output page
by placing the pieces it needs around items it draws itself, so the table can
hold any number of rows. Values are replaced by covering the old text with a
white box and redrawing the new text.

Behaviors worth knowing:
  - Rows flow across pages. Page 1 has room from y=387 to the footer; later pages
    repeat the column-header band. The totals block goes under the last row if it
    fits on that page, otherwise on a page of its own.
  - Every number is recomputed: a row's Net Amount is qty x Disc. U.P (Disc. U.P
    is U.P less any "% disc.", and equals U.P when there is none), the subtotal is
    the sum of the rows, tax is the Net total x the "tax_rate" field, and the
    total is subtotal + tax. The printed subtotal/tax/total form fields are not
    used. (The sample's own amounts are qty x U.P; terms are not multiplied in.)
  - A row's Quote ID is its own "quote_id" when present, else the quote number
    found in the "comment" field, else blank (rows pulled from Salesforce carry
    no Quote ID).
  - A row that carries "serial_number" / "contract_start_date" /
    "contract_end_date" prints the three-line "Supported S/N" block above it, as
    the sample does; rows without them print no block.
  - The static "Email:" footer line is redrawn as an @sandbox.com address (see
    sandbox_email.py), and the template's own mailto: links are replaced by links
    that match the printed address blocks.
  - Text is drawn in Helvetica at the template's point sizes, not its embedded
    Noto Sans, and shrunk to fit its box. The original text of covered or
    clipped-away pieces stays in the PDF's hidden text layer.
"""

import io
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pypdf import PageObject, PdfReader, PdfWriter, Transformation
from pypdf.annotations import Link
from pypdf.generic import DecodedStreamObject, NameObject
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

import config
from pdf_engine.extractor import find_template_path
from pdf_engine.generator import _render_overlay
from pdf_engine.paginate import _to_decimal, wrap_chars, wrap_text
from sandbox_email import sandbox_text

SLUG = "Exclusive Networks (Norway)"

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
BLACK = (0.0, 0.0, 0.0)
WHITE = (1.0, 1.0, 1.0)
MIN_FONT_SIZE = 4.0
# Noto Sans text sits 0.708 x its size below the character box's top edge.
BASELINE_FACTOR = 0.708
COVER_PAD = 1.0

PAGE_W, PAGE_H = 595.0, 841.0
LEFT = 26.4
BODY_RIGHT = 573.4

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_QUOTE_RE = re.compile(r"\bQ-\d+\b")

# --- Template pieces (top-origin y) -----------------------------------------
HEAD1_BOTTOM = 383.0  # page-1 head: letterhead .. items header band's bottom edge
CONT_HEAD_TOP, CONT_HEAD_BOTTOM = 0.0, 144.5  # page-2 head: letterhead + header band
CONT_ITEMS_TOP = 157.0  # where page 2's first row starts in the template
TOTALS_TOP, TOTALS_BOTTOM = 591.0, 658.0  # totals block (tax table, Total box, payment terms)
FOOTER_TOP = 764.0  # footer rule + static Phone/Email/VAT + page number

# --- Item rows ---------------------------------------------------------------
PAGE1_ITEMS_TOP = 386.8
ITEMS_BOTTOM = 745.0  # lowest an item's last line may sit on a page
ITEM_TEXT = 9.0
# Vertical rhythm inside an item (tops, relative to the main row's top).
DESC_OFFSET = 12.3
DESC_PITCH = 12.3  # extra description lines
TERMS_GAP = 18.0  # from the last description line to the Terms line
ITEM_GAP = 21.8  # from the Terms line to the next item's top
# The optional serial/contract block above a row: line offsets from the block top,
# and the gap from its last line to the row's own top.
BLOCK_OFFSETS = (0.0, 15.4, 39.9, 48.9, 57.9, 66.9)
# From the block's first line down to the row it belongs to (82.3 in the template).
BLOCK_TO_ROW = 82.3

COL_SKU_X = 26.4
COL_QUOTE_X = 143.0
COL_QTY_RIGHT = 251.1
COL_UP_RIGHT = 340.0
COL_DISC_RIGHT = 480.0
COL_AMOUNT_RIGHT = 569.0
SKU_ROOM = COL_QUOTE_X - COL_SKU_X - 4.0
SKU_MIN_SIZE = 6.5  # below this a SKU wraps onto extra lines instead of shrinking
DESC_ROOM = 520.0 - COL_SKU_X

# --- Header values (cover box: left, top, right, bottom) -----------------------
# key -> (x, text top, size, bold, cover box, align)
_HEADER_CELLS = {
    "po_number": (26.4, 138.6, 9.0, False, (23.0, 137.0, 112.0, 149.0)),
    "po_date": (118.4, 138.6, 9.0, False, (115.0, 137.0, 206.0, 149.0)),
    "vendor_code": (210.4, 138.6, 9.0, False, (207.0, 137.0, 297.0, 149.0)),
    "so_number": (26.4, 176.5, 9.0, False, (23.0, 175.0, 112.0, 187.0)),
    "requested_delivery_date": (118.4, 176.5, 9.0, False, (115.0, 175.0, 206.0, 187.0)),
    "exn_contact": (210.4, 176.5, 9.0, False, (207.0, 175.0, 297.0, 187.0)),
}
COMMENT_BOX = (24.0, 213.0, 574.0, 225.0)
COMMENT_TOP = 214.2
# Address blocks: (x, cover box, max width). Line pitch 9.0, first line top 251.9.
BLOCK_FIRST_TOP = 251.9
BLOCK_PITCH = 9.0
_BLOCKS = {
    "end_user_block": (26.4, (23.0, 250.0, 206.0, 326.0), 176.0),
    "reseller_block": (210.4, (207.0, 250.0, 405.0, 326.0), 190.0),
    "ship_to_block": (409.4, (406.0, 250.0, 574.0, 326.0), 160.0),
}
RESELLER_PO_LINE = 4  # the "Reseller PO: ..." line sits after the reseller's 4 address lines
SHIPPING_DETAILS_BOX = (24.0, 329.0, 574.0, 340.0)
INCOTERMS_BOX = (24.0, 338.0, 574.0, 349.0)

# --- Totals block ---------------------------------------------------------------
TOTALS_RIGHT = 569.0
TOTALS_TOP_VALUES = {  # key -> (top, right x)
    "subtotal": (605.0, 569.0),
    "tax_total": (620.4, 569.0),
    "total": (640.4, 569.0),
}
TAX_ROW_TOP = 615.8
TAX_ROW_XS = {"tax_rate": (24.0, "left"), "tax_net_amt": (135.0, "right"), "tax_amt": (215.0, "right"), "gross_amt": (295.0, "right")}
PAYMENT_TERMS_TOP = 643.9
PAYMENT_TERMS_X = 98.9
# Cover only the VALUES (labels such as "Subtotal" / "Total (USD)" stay): the
# right column's values start at x=522, the payment-terms value at x=98.9.
TOTALS_TEXT_COVERS = (
    (22.0, 614.8, 300.0, 627.0),  # tax table row (values; below the grey header cells)
    (520.0, 603.8, 574.0, 616.0),  # subtotal value
    (548.0, 619.0, 574.0, 631.0),  # tax total value
    (520.0, 639.5, 573.0, 651.0),  # total value (inside the grey box; grey, not white)
    (98.0, 642.5, 300.0, 655.0),  # payment terms value
)
TOTAL_BOX_GREY = (0.890196, 0.890196, 0.890196)
TOTALS_HEIGHT = TOTALS_BOTTOM - TOTALS_TOP

# --- Footer ---------------------------------------------------------------------
FOOTER_EMAIL_TOP = 794.5
FOOTER_EMAIL_X = 54.2
FOOTER_EMAIL_COVER = (53.0, 793.5, 200.0, 805.0)
FOOTER_PAGE_TOP = 797.7
FOOTER_PAGE_COVER = (526.0, 796.5, 560.0, 808.0)
FOOTER_EMAIL_ADDRESS = "salg_no@exclusive-networks.com"


# --- Cutting pieces out of the template ---------------------------------------
def _clip_piece(template_bytes: bytes, page_index: int, top: float, bottom: float) -> PageObject:
    """A fresh copy of template page page_index limited to the horizontal band
    top..bottom (top-origin), with the template's own link annotations removed
    (they would still open the original addresses)."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(template_bytes)))
    page = writer.pages[page_index]
    data = page.get_contents().get_data()
    stream = DecodedStreamObject()
    stream.set_data(f"q 0 {PAGE_H - bottom:.3f} {PAGE_W:.3f} {bottom - top:.3f} re W n\n".encode() + data + b"\nQ")
    page[NameObject("/Contents")] = writer._add_object(stream)
    if "/Annots" in page:
        del page["/Annots"]
    return page


def _compose_page(template_bytes: bytes, pieces: list[tuple[int, float, float, float]], overlay_page) -> PageObject:
    """A blank page with each (template page, clip top, clip bottom, dy-down) piece
    placed on it, then the drawn overlay on top."""
    page = PageObject.create_blank_page(width=PAGE_W, height=PAGE_H)
    for page_index, top, bottom, dy_down in pieces:
        piece = _clip_piece(template_bytes, page_index, top, bottom)
        page.merge_transformed_page(piece, Transformation().translate(0, -dy_down))
    page.merge_page(overlay_page)
    return page


def _add_links(writer: PdfWriter, links: list) -> None:
    page_index = len(writer.pages) - 1
    for left, top, right, bottom, uri in links:
        writer.add_annotation(
            page_number=page_index, annotation=Link(rect=(left, PAGE_H - bottom, right, PAGE_H - top), url=uri)
        )


# --- Drawing helpers --------------------------------------------------------------
def _cover(c: canvas.Canvas, box: tuple[float, float, float, float], dy: float = 0.0, fill=WHITE) -> None:
    left, top, right, bottom = box
    c.saveState()
    c.setFillColorRGB(*fill)
    c.rect(left, PAGE_H - bottom - dy, right - left, bottom - top, fill=1, stroke=0)
    c.restoreState()


def _fit(text: str, font: str, size: float, max_width: float) -> float:
    while size > MIN_FONT_SIZE and stringWidth(text, font, size) > max_width:
        size -= 0.1
    return size


def _text(
    c: canvas.Canvas,
    x: float,
    top: float,
    text: str,
    size: float = ITEM_TEXT,
    *,
    bold: bool = False,
    align: str = "left",
    max_width: float | None = None,
    links: list | None = None,
) -> None:
    """When `links` is given, every email address in the text is underlined (as
    the template does for its linked addresses) and recorded as a mailto link."""
    if not text:
        return
    font = FONT_BOLD if bold else FONT
    if max_width is not None:
        size = _fit(text, font, size, max_width)
    baseline = PAGE_H - top - size * BASELINE_FACTOR
    width = stringWidth(text, font, size)
    left = x - width if align == "right" else x
    c.saveState()
    c.setFont(font, size)
    c.setFillColorRGB(*BLACK)
    c.drawString(left, baseline, text)
    if links is not None:
        c.setStrokeColorRGB(*BLACK)
        c.setLineWidth(0.45)
    for match in _EMAIL_RE.finditer(text) if links is not None else ():
        start = left + stringWidth(text[: match.start()], font, size)
        end = start + stringWidth(match.group(0), font, size)
        c.line(start, baseline - 2.2, end, baseline - 2.2)
        links.append((start, top, end, top + size, f"mailto:{match.group(0)}"))
    c.restoreState()


def _replace(c: canvas.Canvas, box, x, top, text, size=9.0, *, bold=False, align="left", right=None, links=None) -> None:
    _cover(c, box)
    room = (box[2] - box[0]) - 4.0
    _text(c, right if align == "right" else x, top, text, size, bold=bold, align=align, max_width=room, links=links)


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def _qty_text(value: Decimal) -> str:
    return f"{int(value):,}" if value == value.to_integral_value() else f"{value.normalize():,f}"


def _unit_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


# --- Rows ------------------------------------------------------------------------
class _Row:
    def __init__(self, item: dict, default_quote: str) -> None:
        self.item = item
        self.sku = str(item.get("part_number") or "")
        # A SKU is an identifier: shrink it a little to fit, but past a readable
        # size wrap it mid-token onto extra lines (as the sample's own tables do)
        # instead of letting it run into the Quote ID column.
        self.sku_lines = (
            [self.sku]
            if _fit(self.sku, FONT_BOLD, ITEM_TEXT, SKU_ROOM) >= SKU_MIN_SIZE
            else wrap_chars(self.sku, SKU_ROOM, SKU_MIN_SIZE)
        )
        self.quote_id = str(item.get("quote_id") or "").strip() or default_quote
        self.qty = _to_decimal(item.get("qty"))
        self.unit_price = _to_decimal(item.get("unit_cost"))
        pct = _to_decimal(item.get("pct_disc"))
        self.disc_price = self.unit_price * (Decimal("1") - pct / Decimal("100"))
        self.amount = (self.qty * self.disc_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.description_lines = wrap_text(str(item.get("description") or ""), DESC_ROOM, ITEM_TEXT) if (
            item.get("description")
        ) else []
        terms = str(item.get("terms") or "").strip()
        if re.fullmatch(r"\d+(?:\.\d+)?", terms):
            terms = f"{terms} months"  # a bare number (as pulled from Salesforce) is months
        self.terms = (terms if terms.lower().startswith("terms") else f"Terms {terms}") if terms else ""
        self.block = [
            ("Supported S/N:", True),
            (str(item.get("serial_number") or ""), False),
            ("Contract Start Date:", True),
            (str(item.get("contract_start_date") or ""), False),
            ("Contract End Date:", True),
            (str(item.get("contract_end_date") or ""), False),
        ] if any(item.get(k) for k in ("serial_number", "contract_start_date", "contract_end_date")) else []

    @property
    def height(self) -> float:
        """Space from the row's top (or its block's top) to the next row's top."""
        h = self.block_height + self.sku_extra
        last = 0.0
        if self.description_lines:
            last = DESC_OFFSET + DESC_PITCH * (len(self.description_lines) - 1)
        if self.terms:
            last += TERMS_GAP if self.description_lines else DESC_OFFSET
            return h + last + ITEM_GAP
        return h + max(last, 0.0) + ITEM_GAP - (0.0 if self.description_lines else 6.0)

    @property
    def sku_extra(self) -> float:
        """Extra height for SKU lines past the first (the description follows them)."""
        return DESC_PITCH * (len(self.sku_lines) - 1)

    @property
    def block_height(self) -> float:
        return BLOCK_TO_ROW if self.block else 0.0


def _draw_row(c: canvas.Canvas, row: _Row, top: float) -> None:
    """Draws one item with its first line (or its block) starting at `top`."""
    if row.block:
        for (text, bold), offset in zip(row.block, BLOCK_OFFSETS):
            _text(c, COL_SKU_X, top + offset, text, ITEM_TEXT, bold=bold)
        top += row.block_height
    for i, sku_line in enumerate(row.sku_lines):
        size = ITEM_TEXT if len(row.sku_lines) == 1 else SKU_MIN_SIZE
        _text(c, COL_SKU_X, top + DESC_PITCH * i, sku_line, size, bold=True, max_width=SKU_ROOM)
    top_after_sku = top + row.sku_extra
    _text(c, COL_QUOTE_X, top, row.quote_id, ITEM_TEXT)
    _text(c, COL_QTY_RIGHT, top, _qty_text(row.qty), ITEM_TEXT, align="right")
    _text(c, COL_UP_RIGHT, top, _unit_text(row.unit_price), ITEM_TEXT, align="right")
    _text(c, COL_DISC_RIGHT, top, _unit_text(row.disc_price), ITEM_TEXT, align="right")
    _text(c, COL_AMOUNT_RIGHT, top, _money(row.amount), ITEM_TEXT, align="right")
    # The description and Terms lines start below the SKU's last line.
    y = top_after_sku
    for i, line in enumerate(row.description_lines):
        y = top_after_sku + DESC_OFFSET + DESC_PITCH * i
        _text(c, COL_SKU_X, y, line, ITEM_TEXT)
    if row.terms:
        y = y + TERMS_GAP if row.description_lines else top_after_sku + DESC_OFFSET
        _text(c, COL_SKU_X, y, row.terms, ITEM_TEXT)


# --- Pagination ------------------------------------------------------------------
def _paginate(rows: list[_Row]) -> list[dict]:
    """Page specs: {"rows": [...], "first_top": y of the page's first row,
    "kind": "first" | "cont", "totals": bool, "totals_top": y or None}."""
    pages: list[dict] = []

    def new_page(kind: str) -> dict:
        page = {"rows": [], "kind": kind, "totals": False, "totals_top": None}
        page["first_top"] = PAGE1_ITEMS_TOP if kind == "first" else CONT_ITEMS_TOP
        page["cursor"] = page["first_top"]
        pages.append(page)
        return page

    page = new_page("first")
    for row in rows:
        # A row needs its own lines to end above ITEMS_BOTTOM (its trailing gap may overhang).
        if page["rows"] and page["cursor"] + row.height - ITEM_GAP > ITEMS_BOTTOM:
            page = new_page("cont")
        page["rows"].append((row, page["cursor"]))
        page["cursor"] += row.height

    # The totals block goes under the last row if it fits above the footer rule.
    # If not, the last row moves to a new page with it, so the block never sits
    # under an empty table (the sample does the same: its last page carries a
    # few rows above the totals).
    if page["cursor"] + TOTALS_HEIGHT + 6.0 <= FOOTER_TOP - 4.0:
        page["totals"], page["totals_top"] = True, page["cursor"] + 6.0
        return pages

    last = new_page("cont")
    if len(page["rows"]) > 1:
        moved, _ = page["rows"].pop()
        page["cursor"] -= moved.height
        last["rows"].append((moved, last["cursor"]))
        last["cursor"] += moved.height
    last["totals"], last["totals_top"] = True, last["cursor"] + 6.0
    return pages


# --- Page drawing ------------------------------------------------------------------
def _split_block(text: str) -> list[str]:
    return [line for line in str(text or "").split("\n")]


def _draw_header(c: canvas.Canvas, fields: dict, links: list) -> None:
    for key, (x, top, size, bold, box) in _HEADER_CELLS.items():
        _replace(c, box, x, top, str(fields.get(key) or ""), size, bold=bold)
    _replace(c, COMMENT_BOX, 26.4, COMMENT_TOP, str(fields.get("comment") or ""), 9.0)

    for key, (x, box, room) in _BLOCKS.items():
        _cover(c, box)
        lines = _split_block(fields.get(key))
        po_line = f"Reseller PO: {fields.get('reseller_po')}" if key == "reseller_block" and fields.get("reseller_po") else None
        if po_line:
            lines.insert(min(RESELLER_PO_LINE, len(lines)), po_line)
        # The End User and Reseller blocks start with a bold company name; the
        # Shipping Address block's first line is regular, as in the template.
        first_bold = key != "ship_to_block"
        for i, line in enumerate(lines):
            _text(c, x, BLOCK_FIRST_TOP + BLOCK_PITCH * i, line, 9.0, bold=(i == 0 and first_bold), max_width=room, links=links)

    # The values start after their bold labels (x=101.7 / 77.5); cover only from there.
    for key, value_x, top, box in (
        ("shipping_details", 101.7, 330.3, SHIPPING_DETAILS_BOX),
        ("incoterms", 77.5, 339.3, INCOTERMS_BOX),
    ):
        _cover(c, (value_x - 0.5, box[1], box[2], box[3]))
        _text(c, value_x, top, str(fields.get(key) or ""), 9.0, max_width=BODY_RIGHT - value_x)


def _draw_totals(c: canvas.Canvas, fields: dict, subtotal: Decimal, tax: Decimal, total: Decimal, dy: float) -> None:
    for box in TOTALS_TEXT_COVERS:
        in_total_box = box[1] > 635.0 and box[0] > 500.0  # the grey Total (USD) box
        _cover(c, (box[0], box[1] + dy, box[2], box[3] + dy), fill=TOTAL_BOX_GREY if in_total_box else WHITE)
    rate = str(fields.get("tax_rate") or "0%")
    _text(c, TAX_ROW_XS["tax_rate"][0], TAX_ROW_TOP + dy, rate, 9.0)
    # Each tax-table value is right-aligned to its column's right edge and shrunk
    # to its own column, so large amounts can't run into the next column.
    for key, value, room in (
        ("tax_net_amt", subtotal, TAX_ROW_XS["tax_net_amt"][0] - 60.0),
        ("tax_amt", tax, TAX_ROW_XS["tax_amt"][0] - TAX_ROW_XS["tax_net_amt"][0] - 6.0),
        ("gross_amt", subtotal + tax, TAX_ROW_XS["gross_amt"][0] - TAX_ROW_XS["tax_amt"][0] - 6.0),
    ):
        _text(c, TAX_ROW_XS[key][0], TAX_ROW_TOP + dy, _money(value), 9.0, align="right", max_width=room)
    for key, value in (("subtotal", subtotal), ("tax_total", tax), ("total", total)):
        top, right = TOTALS_TOP_VALUES[key]
        _text(c, right, top + dy, _money(value), 9.0, align="right")
    _text(c, PAYMENT_TERMS_X, PAYMENT_TERMS_TOP + dy, str(fields.get("payment_terms") or ""), 9.0)


def _draw_footer(c: canvas.Canvas, number: int, total_pages: int) -> None:
    _cover(c, FOOTER_EMAIL_COVER)
    _text(c, FOOTER_EMAIL_X, FOOTER_EMAIL_TOP, sandbox_text(FOOTER_EMAIL_ADDRESS), 9.0)
    _cover(c, FOOTER_PAGE_COVER)
    _text(c, 529.3, FOOTER_PAGE_TOP, f"{number} of {total_pages}", 9.0)


def _tax_amount(subtotal: Decimal, rate_text: str) -> Decimal:
    match = re.search(r"\d+(?:[.,]\d+)?", str(rate_text or ""))
    rate = _to_decimal(match.group(0)) if match else Decimal("0")
    return (subtotal * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _refresh_comment(fields: dict, quote_number: str, quote_match) -> dict:
    """The comment line quotes the Quote number ("... ACCEPTS ALL ADDITIONAL TERMS ON
    Q-809902 DATED ..."). When a different Quote number has been supplied, swap it in
    so the line doesn't keep the sample PO's old Quote."""
    comment = str(fields.get("comment") or "")
    if not quote_match or not quote_number or quote_match.group(0) == quote_number:
        return fields
    return {**fields, "comment": comment.replace(quote_match.group(0), quote_number)}


def generate_exclusive_networks_norway_po(fields: dict, line_items: list[dict]) -> bytes:
    path = find_template_path(SLUG)
    if path is None:
        raise FileNotFoundError(f"No template PDF found for distributor '{SLUG}'")

    # A row's Quote ID: its own, else the form's "quote_number" (set when a Quote
    # is pulled from Salesforce), else the quote number in the comment line.
    quote_match = _QUOTE_RE.search(str(fields.get("comment") or ""))
    default_quote = str(fields.get("quote_number") or "").strip() or (quote_match.group(0) if quote_match else "")
    fields = _refresh_comment(fields, default_quote, quote_match)
    rows = [
        _Row(item, default_quote)
        for item in line_items
        if item and (item.get("part_number") or item.get("description"))
    ]
    subtotal = sum((r.amount for r in rows), Decimal("0"))
    tax = _tax_amount(subtotal, fields.get("tax_rate"))
    total = subtotal + tax
    pages = _paginate(rows)

    template_bytes = path.read_bytes()
    writer = PdfWriter()
    total_pages = len(pages)
    for number, spec in enumerate(pages, start=1):
        links: list = []
        is_first = spec["kind"] == "first"
        totals_dy = (spec["totals_top"] - TOTALS_TOP) if spec["totals"] else 0.0

        def draw(c: canvas.Canvas, spec=spec, is_first=is_first, number=number, totals_dy=totals_dy) -> None:
            if is_first:
                _draw_header(c, fields, links)
            for row, top in spec["rows"]:
                _draw_row(c, row, top)
            if spec["totals"]:
                _draw_totals(c, fields, subtotal, tax, total, totals_dy)
            _draw_footer(c, number, total_pages)

        # (template page, clip top, clip bottom, dy down). Page 1 supplies the
        # full head; page 2 the repeated header band and the totals block.
        pieces: list[tuple[int, float, float, float]] = []
        if is_first:
            pieces.append((0, 0.0, HEAD1_BOTTOM, 0.0))
        else:
            pieces.append((1, CONT_HEAD_TOP, CONT_HEAD_BOTTOM, 0.0))
        if spec["totals"]:
            pieces.append((1, TOTALS_TOP, TOTALS_BOTTOM, totals_dy))
        pieces.append((0, FOOTER_TOP, PAGE_H, 0.0))

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
