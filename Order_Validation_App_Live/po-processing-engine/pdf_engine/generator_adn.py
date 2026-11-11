"""Regenerates ADN Distribution GmbH purchase orders.

ADN's template is a flowing document rather than a fixed form: each item is a
multi-line block, every page repeats the PO number and "Page: n/N", and each
items page carries a running "Balance c/f". So instead of the coordinate
layouts in pdf_engine/layouts/, this module keeps the template's header, footer
and totals artwork, clears the item area on each page, and redraws the header
values, the items and the running balances, paginating the items itself.

Known limitations:
  - Text is drawn in Helvetica, not the template's Verdana.
  - The list price is printed equal to the unit price, matching the sample
    (whose discount is always 0; the parser does not carry a discount value).
"""

import io
from dataclasses import dataclass, field
from pathlib import Path
from decimal import ROUND_HALF_UP, Decimal


from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

import config
from pdf_engine.common import column_boxes, fit_size, order_columns
from pdf_engine.extractor import find_template_path
from pdf_engine.generator import _fresh_page, _render_overlay
from pdf_engine.paginate import _to_decimal, wrap_text

SLUG = "ADN Distribution GmbH"

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
ITEM_FONT_SIZE = 7.0

# Template page indexes in the ADN sample.
TEMPLATE_FIRST = 0  # header block + first items
TEMPLATE_CONT = 1  # continuation items page
TEMPLATE_LAST = 5  # totals page

# Vertical room for item blocks, in pdfplumber's top-down coordinates.
FIRST_TOP, FIRST_BOTTOM = 500.0, 744.0
CONT_TOP, CONT_BOTTOM = 190.0, 744.0
LAST_BOTTOM = 652.0  # the totals block starts at about y=662 on the last page

# Offsets within an item block, measured from the sample.
SKU_OFFSET = 10.0
UNIT_OFFSET = 20.0
DESCRIPTION_OFFSET = 41.0
LINE_HEIGHT = 10.0
BLOCK_GAP = 20.0
DESCRIPTION_WIDTH = 564.7 - 86.5

# Item area cleared on each template page: (x0, top, x1, bottom).
ITEMS_AREA = {
    TEMPLATE_FIRST: (56.0, 493.0, 567.0, 746.0),
    TEMPLATE_CONT: (56.0, 171.0, 567.0, 746.0),
    TEMPLATE_LAST: (56.0, 171.0, 567.0, LAST_BOTTOM),
}
PO_LINE_TOP = {TEMPLATE_FIRST: 302.7, TEMPLATE_CONT: 143.0, TEMPLATE_LAST: 143.0}
PAGE_LABEL_TOP = {TEMPLATE_FIRST: 308.2, TEMPLATE_CONT: 148.3, TEMPLATE_LAST: 148.3}

WHITE = (1.0, 1.0, 1.0)
FOOTER_GREY = (0.82745, 0.82745, 0.82745)

# --- Item columns ---------------------------------------------------------------
# The column-header band is template artwork (grey cells, a dark grey 0.75pt border on the
# top, bottom and outer sides, bold 7pt labels). In the default order it is left as printed;
# for any other order it is covered and redrawn in the new order. Keys follow the form's
# `column_order` (unit_cost -> unit_price, sno -> pos); "item" carries the item number with the
# SKU / description / terms lines beneath it, so the form's description moves with part_number.
# List price (printed equal to the unit price) travels beside Price per unit and VAT beside
# Total price; the form's Terms has no column (it is a line in the item block).
COLUMNS = ("pos", "item", "qty", "list_price", "discount", "unit_price", "total", "vat")
COL_EDGES = (56.69, 85.04, 201.6, 270.72, 345.6, 385.92, 455.04, 538.58, 566.93)
COL_WIDTHS = {key: COL_EDGES[i + 1] - COL_EDGES[i] for i, key in enumerate(COLUMNS)}
# The form's % disc. is not mapped: ADN's Discount column is always empty (the sample's discount is 0
# and the form has no source for it), and mapping it would make the form's own default order
# (unit cost before % disc.) disagree with the template's (Discount before Price per unit). So
# Discount sits just before Price per unit with the List price, and VAT just after Total price.
FORM_KEYS = {"sno": "pos", "part_number": "item", "description": "item", "qty": "qty",
             "unit_cost": "unit_price", "total": "total"}
ANCHORS = {"list_price": "unit_price", "discount": "unit_price"}
HEAD_LABELS = {
    "pos": "Pos.", "item": "Item number / Label", "qty": "Quantity", "list_price": "List price",
    "discount": "Discount", "unit_price": "Price per unit", "total": "Total price", "vat": "VAT",
}
# Band position per template page (top, bottom), its colours and the border thickness.
HEAD_BAND = {TEMPLATE_FIRST: (480.46, 491.97), TEMPLATE_CONT: (158.65, 170.15), TEMPLATE_LAST: (158.65, 170.15)}
HEAD_BORDER = (0.41176, 0.41176, 0.41176)
HEAD_RULE = 0.75
HEAD_LABEL_OFFSET = 3.01  # label top below the band's top
HEAD_LABEL_PAD = 0.7      # label left inside its cell
# The values' x positions in the sample (default column order). In another order each value
# moves by its column's shift, so it keeps the same place inside its cell.
POS_X, ITEM_X = 56.7, 86.5                                  # left-aligned
QTY_RIGHT, LIST_RIGHT, UNIT_RIGHT, TOTAL_RIGHT, VAT_RIGHT = 242.8, 325.0, 437.3, 535.7, 564.7
DESCRIPTION_RIGHT = 564.7  # the item block's free lines (SKU, description, terms) run to here


class _Columns:
    """Where each column sits for one PO. In the default order every shift is exactly 0 and the
    template's own header band is kept, so the output is the sample's layout unchanged."""

    def __init__(self, column_order: list[str] | None) -> None:
        requested = [FORM_KEYS[k] for k in (column_order or []) if k in FORM_KEYS]
        self.order = order_columns(requested, COLUMNS, ANCHORS)
        # VAT always prints right after Total price (order_columns only places before an anchor).
        self.order.remove("vat")
        self.order.insert(self.order.index("total") + 1, "vat")
        self.custom = tuple(self.order) != COLUMNS
        self.boxes = column_boxes(COL_EDGES[0], COL_WIDTHS, self.order)
        self.shift = {
            key: (self.boxes[key][0] - COL_EDGES[i]) if self.custom else 0.0 for i, key in enumerate(COLUMNS)
        }
        # The free lines start under the item number and run to the table's right margin; they
        # sit below the first line, so columns to the item's right don't get in their way.
        self.item_x = ITEM_X + self.shift["item"]
        self.description_width = DESCRIPTION_RIGHT - self.item_x


@dataclass
class _Block:
    pos: str
    item_number: str
    sku: str
    unit_text: str
    description_lines: list[str]
    terms: str
    qty: str
    unit_price: str
    amount: Decimal
    height: float
    # List price and Discount columns. With no discount they are the sample's: the List price
    # prints the unit price and Discount stays blank.
    list_price: str = ""
    discount: str = ""


@dataclass
class _PageSpec:
    template: int
    blocks: list[_Block] = field(default_factory=list)


def _format_number(value: Decimal, places: int) -> str:
    """EU-style number, e.g. 1643752.66 -> "1.643.752,66" (places=2)."""
    quantized = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    sign = "-" if quantized < 0 else ""
    whole, _, fraction = f"{abs(quantized):.{places}f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    return f"{sign}{grouped},{fraction}" if places else f"{sign}{grouped}"


def _build_blocks(line_items: list[dict], description_width: float = DESCRIPTION_WIDTH) -> list[_Block]:
    blocks: list[_Block] = []
    last_pos = 0
    for item in line_items:
        if not (item.get("part_number") or item.get("description")):
            continue

        # Keep ADN's own position numbers; rows added in the UI continue the sequence.
        pos = str(item.get("pos") or "").strip()
        if pos.isdigit():
            last_pos = int(pos)
        else:
            last_pos += 1
            pos = str(last_pos)

        qty = _to_decimal(item.get("qty"))
        unit_price = _to_decimal(item.get("unit_cost")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        amount = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        qty_places = 0 if qty == qty.to_integral_value() else 2
        # The price per unit and the total stay the unit cost and qty x unit cost (the unit cost is
        # already net of any discount). A discount (a % pulled from Salesforce, or typed) prints in
        # the Discount column, and the List price becomes the price before it:
        # unit price / (1 - discount / 100), as Arrow derives its RRP.
        discount = _to_decimal(str(item.get("pct_disc") or "").replace("%", ""))
        list_price = unit_price
        if 0 < discount < 100:
            list_price = (unit_price / (1 - discount / 100)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        description_lines = wrap_text(str(item.get("description") or ""), description_width, ITEM_FONT_SIZE)
        terms = str(item.get("terms") or "")
        height = (
            DESCRIPTION_OFFSET
            + LINE_HEIGHT * (len(description_lines) - 1)
            + (LINE_HEIGHT if terms else 0)
            + BLOCK_GAP
        )
        blocks.append(
            _Block(
                pos=pos,
                item_number=str(item.get("item_number") or ""),
                sku=str(item.get("part_number") or ""),
                unit_text=str(item.get("unit_text") or ""),
                description_lines=description_lines,
                terms=terms,
                qty=_format_number(qty, qty_places),
                unit_price=_format_number(unit_price, 4),
                amount=amount,
                height=height,
                list_price=_format_number(list_price, 4),
                discount=_format_number(discount, 2).replace(",00", "") + " %" if discount > 0 else "",
            )
        )
    return blocks


def _paginate(blocks: list[_Block]) -> list[_PageSpec]:
    pages = [_PageSpec(TEMPLATE_FIRST)]
    y, bottom = FIRST_TOP, FIRST_BOTTOM
    for block in blocks:
        if pages[-1].blocks and y + block.height > bottom:
            pages.append(_PageSpec(TEMPLATE_CONT))
            y, bottom = CONT_TOP, CONT_BOTTOM
        pages[-1].blocks.append(block)
        y += block.height

    # The final items page doubles as the totals page when its rows leave room
    # for the totals block; otherwise an empty totals page follows. The first
    # page can't be the totals page because the template's first page has no
    # totals block.
    if len(pages) > 1 and y <= LAST_BOTTOM:
        pages[-1].template = TEMPLATE_LAST
    else:
        pages.append(_PageSpec(TEMPLATE_LAST))
    return pages


def _whiteout(c: canvas.Canvas, page_height: float, x0: float, top: float, x1: float, bottom: float, fill=WHITE) -> None:
    c.saveState()
    c.setFillColorRGB(*fill)
    c.rect(x0, page_height - bottom, x1 - x0, bottom - top, fill=1, stroke=0)
    c.restoreState()


def _text(
    c: canvas.Canvas,
    page_height: float,
    x: float,
    top: float,
    text: str,
    size: float = ITEM_FONT_SIZE,
    bold: bool = False,
    align: str = "left",
) -> None:
    if not text:
        return
    c.saveState()
    c.setFont(FONT_BOLD if bold else FONT, size)
    c.setFillColorRGB(0, 0, 0)
    baseline = page_height - (top + size * 0.82)
    if align == "right":
        c.drawRightString(x, baseline, text)
    else:
        c.drawString(x, baseline, text)
    c.restoreState()


def _draw_block(c: canvas.Canvas, page_height: float, block: _Block, top: float, cols: _Columns) -> None:
    s = cols.shift
    item_x = cols.item_x
    _text(c, page_height, POS_X + s["pos"], top, block.pos)
    _text(c, page_height, item_x, top, block.item_number, bold=True)
    _text(c, page_height, QTY_RIGHT + s["qty"], top, block.qty, align="right")
    _text(c, page_height, LIST_RIGHT + s["list_price"], top, block.unit_price, align="right")
    _text(c, page_height, UNIT_RIGHT + s["unit_price"], top, block.unit_price, align="right")
    _text(c, page_height, TOTAL_RIGHT + s["total"], top, _format_number(block.amount, 2), align="right")
    _text(c, page_height, VAT_RIGHT + s["vat"], top, "0 %", align="right")

    if block.sku:
        _text(c, page_height, item_x, top + SKU_OFFSET, f"[{block.sku}]")
    if block.sku and block.unit_text:
        unit_line = f"{block.sku} - {block.unit_text}"
        # In a custom order the item column can sit further right, leaving this one-line label
        # less room than in the sample; shrink it to fit there (the default is drawn as before).
        size = fit_size(unit_line, FONT_BOLD, ITEM_FONT_SIZE, cols.description_width, 4.5) if cols.custom else ITEM_FONT_SIZE
        _text(c, page_height, item_x, top + UNIT_OFFSET, unit_line, size, bold=True)
    for i, line in enumerate(block.description_lines):
        _text(c, page_height, item_x, top + DESCRIPTION_OFFSET + LINE_HEIGHT * i, line)
    if block.terms:
        _text(
            c,
            page_height,
            item_x,
            top + DESCRIPTION_OFFSET + LINE_HEIGHT * len(block.description_lines),
            block.terms,
        )


def _draw_head_band(c: canvas.Canvas, page_height: float, template: int, cols: _Columns) -> None:
    """Redraws the column-header band in `cols` order over the template's own band. Its grey
    is the template's, so main.py's strip pass (which removes text under ADN's 0.827 grey)
    drops the template's original labels from the text layer."""
    top, bottom = HEAD_BAND[template]
    x0, x1 = COL_EDGES[0], COL_EDGES[-1]
    _whiteout(c, page_height, x0, top, x1, bottom, fill=FOOTER_GREY)
    _whiteout(c, page_height, x0, top, x1, top + HEAD_RULE, fill=HEAD_BORDER)
    _whiteout(c, page_height, x0, bottom - HEAD_RULE, x1, bottom, fill=HEAD_BORDER)
    _whiteout(c, page_height, x0, top, x0 + HEAD_RULE, bottom, fill=HEAD_BORDER)
    _whiteout(c, page_height, x1 - HEAD_RULE, top, x1, bottom, fill=HEAD_BORDER)
    for key in cols.order:
        left = cols.boxes[key][0]
        _text(c, page_height, left + HEAD_LABEL_PAD, top + HEAD_LABEL_OFFSET, HEAD_LABELS[key], bold=True)


LICENSEE_BLOCK_COVER = (396.0, 334.0, 546.0, 396.5)
LICENSEE_FIRST_TOP = 336.0
LICENSEE_PITCH = 8.4
LICENSEE_SIZE = 7.0
LICENSEE_ROOM = 546.0 - 398.0


def _draw_licensee_address(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    """Licensee address block, right column of the first page. The template's
    own lines sit under a white cover so only the edited address shows."""
    x0, top, x1, bottom = LICENSEE_BLOCK_COVER
    _whiteout(c, page_height, x0, top, x1, bottom)
    y = LICENSEE_FIRST_TOP
    for raw in str(fields.get("licensee_address") or "").split("\n"):
        for line in wrap_text(raw, LICENSEE_ROOM, LICENSEE_SIZE):
            _text(c, page_height, 398.0, y, line, LICENSEE_SIZE)
            y += LICENSEE_PITCH


# The Invoice address (left) and Delivery / Effort address (middle) blocks, below their labels
# and above the rule at about y=399. Both print in the template's 7pt text at an 8.5pt pitch,
# so at most this many lines fit before the rule.
ADDRESS_FIRST_TOP = 336.0
ADDRESS_PITCH = 8.5
ADDRESS_SIZE = 7.0
ADDRESS_MAX_LINES = 7
# (field key, cover box x0/top/x1/bottom, text x, wrap width)
ADDRESS_BLOCKS = (
    ("invoice_address", (54.0, 334.0, 226.0, 397.0), 56.7, 222.0 - 56.7),
    ("delivery_address", (226.0, 334.0, 396.0, 397.0), 228.2, 393.0 - 228.2),
)


def _draw_address_blocks(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    """Invoice and Delivery / Effort address blocks of the first page. The template's own
    lines sit under a white cover so only the edited address shows; long lines wrap inside
    their column. A block whose field isn't supplied keeps the template's text."""
    for key, (x0, top, x1, bottom), text_x, room in ADDRESS_BLOCKS:
        if key not in fields:
            continue
        _whiteout(c, page_height, x0, top, x1, bottom)
        lines: list[str] = []
        for raw in str(fields.get(key) or "").split("\n"):
            lines.extend(wrap_text(raw.strip(), room, ADDRESS_SIZE) if raw.strip() else [])
        for i, line in enumerate(lines[:ADDRESS_MAX_LINES]):
            _text(c, page_height, text_x, ADDRESS_FIRST_TOP + ADDRESS_PITCH * i, line, ADDRESS_SIZE)


def _draw_header_values(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    """Values on the first page's header block, which only prints once."""
    _whiteout(c, page_height, 433.0, 156.5, 566.0, 165.5)
    _text(c, page_height, 434.5, 157.7, fields.get("po_date", ""), 6.75)

    _whiteout(c, page_height, 433.0, 170.5, 566.0, 179.5)
    _text(c, page_height, 434.5, 171.5, fields.get("reference_number", ""), 6.75)

    _whiteout(c, page_height, 433.0, 198.5, 566.0, 207.5)
    _text(c, page_height, 434.5, 199.6, fields.get("processed_by", ""), 6.75)

    quote_line = (
        f"Quote Ersteller: {fields.get('quote_creator', '')}, "
        f"Endkunden PO: {fields.get('enduser_po', '')}, "
        f"Reseller PO: {fields.get('reseller_po', '')}, "
        f"Quote: {fields.get('quote_number', '')}"
    )
    _whiteout(c, page_height, 56.0, 444.5, 566.0, 455.0)
    _text(c, page_height, 56.7, 446.0, quote_line, 7)

    _whiteout(c, page_height, 56.0, 463.5, 566.0, 472.5)
    _text(c, page_height, 56.7, 464.8, f"Enduser-PO: {fields.get('enduser_po', '')}", 6.8)

    # The contingency note is editable: print whatever the user supplied, and nothing at
    # all when they cleared it. Only when the field isn't supplied is the default built.
    if "contingency_note" in fields:
        accepts_line = str(fields.get("contingency_note") or "").strip()
    else:
        accepts_line = (
            f"ADN Distribution GmbH ACCEPTS ALL ADDITIONAL TERMS ON "
            f"{fields.get('quote_number', '')} DATED {fields.get('quote_date', '')}"
        )
    _whiteout(c, page_height, 56.0, 472.0, 566.0, 480.0)
    if accepts_line:
        _text(c, page_height, 56.7, 473.0, accepts_line, 6.75)


def _draw_totals(c: canvas.Canvas, page_height: float, fields: dict, grand_total: Decimal) -> None:
    total_text = _format_number(grand_total, 2)

    _whiteout(c, page_height, 486.0, 661.5, 541.0, 671.0)
    _text(c, page_height, 540.0, 663.0, total_text, 7, align="right")

    # ADN prices in this document carry no VAT, so the VAT amount is always 0.
    _whiteout(c, page_height, 520.0, 672.5, 541.0, 681.0)
    _text(c, page_height, 540.0, 673.5, _format_number(Decimal("0"), 2), 7, align="right")

    _whiteout(c, page_height, 484.0, 683.5, 541.0, 693.0)
    _text(c, page_height, 540.0, 685.2, total_text, 7, bold=True, align="right")

    _whiteout(c, page_height, 56.0, 672.8, 300.0, 681.0)
    _text(c, page_height, 56.7, 674.2, fields.get("payment_terms", ""), 7)

    _whiteout(c, page_height, 56.0, 684.5, 200.0, 693.0)
    _text(c, page_height, 56.7, 685.5, fields.get("delivery_terms", ""), 7)


def _draw_page(
    c: canvas.Canvas,
    page_height: float,
    spec: _PageSpec,
    number: int,
    total_pages: int,
    fields: dict,
    grand_total: Decimal,
    balance: Decimal | None,
    cols: _Columns,
) -> None:
    t = spec.template
    x0, top, x1, bottom = ITEMS_AREA[t]
    _whiteout(c, page_height, x0, top, x1, bottom)
    if cols.custom:
        _draw_head_band(c, page_height, t, cols)

    po_top = PO_LINE_TOP[t]
    _whiteout(c, page_height, 56.0, po_top - 2.5, 300.0, po_top + 12.5)
    _text(c, page_height, 56.7, po_top, f"Purchase order {fields.get('po_number', '')}", 10, bold=True)

    page_top = PAGE_LABEL_TOP[t]
    _whiteout(c, page_height, 482.0, page_top - 2.5, 557.5, page_top + 9.5)
    _text(c, page_height, 483.2, page_top, "Page:", 6.8, bold=True)
    _text(c, page_height, 544.0, page_top, f"{number}/{total_pages}", 6.8)

    if t == TEMPLATE_FIRST:
        _draw_header_values(c, page_height, fields)
        _draw_licensee_address(c, page_height, fields)
        _draw_address_blocks(c, page_height, fields)

    y = FIRST_TOP if t == TEMPLATE_FIRST else CONT_TOP
    for block in spec.blocks:
        _draw_block(c, page_height, block, y, cols)
        y += block.height

    if balance is not None:
        _whiteout(c, page_height, 480.0, 749.0, 540.5, 758.5, fill=FOOTER_GREY)
        _text(c, page_height, 540.0, 750.4, _format_number(balance, 2), 8, bold=True, align="right")

    if t == TEMPLATE_LAST:
        _draw_totals(c, page_height, fields, grand_total)


def generate_adn_po(fields: dict, line_items: list[dict], column_order: list[str] | None = None) -> bytes:
    cols = _Columns(column_order)
    path = find_template_path(SLUG)
    if path is None:
        raise FileNotFoundError(f"No template PDF found for distributor '{SLUG}'")

    pdf_bytes = path.read_bytes()
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_width = float(reader.pages[0].mediabox.width)
    page_height = float(reader.pages[0].mediabox.height)

    blocks = _build_blocks(line_items, cols.description_width)
    grand_total = sum((b.amount for b in blocks), Decimal("0"))
    pages = _paginate(blocks)

    writer = PdfWriter()
    running = Decimal("0")
    for number, spec in enumerate(pages, start=1):
        running += sum((b.amount for b in spec.blocks), Decimal("0"))
        balance = None if spec.template == TEMPLATE_LAST else running

        page = _fresh_page(pdf_bytes, spec.template)
        overlay = _render_overlay(
            page_width,
            page_height,
            lambda c, s=spec, n=number, b=balance: _draw_page(
                c, page_height, s, n, len(pages), fields, grand_total, b, cols
            ),
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
