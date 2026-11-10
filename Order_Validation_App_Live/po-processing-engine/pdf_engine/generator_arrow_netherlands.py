"""Regenerates Arrow ECS BV (Netherlands) purchase orders.

The template is a flowing document: every items page repeats the PO number and
"Page N of M", the first page carries the header panels, the last items page
carries the totals and payment/delivery terms, and a "Complementary Order
Information" page closes the document. Rows have no rules between them and
their height depends on how many lines their text wraps to, so this module
keeps the template's artwork, clears the items area on each page, and redraws
the header values, the items (paginating them itself), the totals and the
complementary page.

Behaviors worth knowing:
  - Line numbers are renumbered 10, 20, 30... in row order.
  - The Arrow item number is always the part number, as on every row of the
    sample (the form edits one part number column).
  - RRP and the printed discount come from the loaded row when it has them;
    otherwise (e.g. rows pulled from a Quote) RRP equals the unit price.
  - A row's "terms" value (e.g. a subscription term of 36) is appended to its
    description as " : 36 months", the way the sample prints its terms.
  - VAT is always 0.00, matching the sample.
  - Fields missing from the request are left as they are on the template.
"""

import io
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

import config
from pdf_engine.extractor import find_template_path
from pdf_engine.generator import _fresh_page, _render_overlay
from pdf_engine.paginate import _to_decimal, format_amount, wrap_chars, wrap_text

SLUG = "Arrow (Netherlands)"

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_SIZE = 8.0
# pdfplumber's `top` is the top of a box whose bottom sits one descent
# (0.207 em for Helvetica) below the baseline.
BASELINE_FACTOR = 0.793

# Template page indexes in the Arrow (Netherlands) sample.
TEMPLATE_FIRST = 0  # header panels + first items
TEMPLATE_CONT = 1  # continuation items page
TEMPLATE_LAST = 14  # last items page, with totals and terms
TEMPLATE_INFO = 15  # complementary order information

# Item rows, in pdfplumber's top-down coordinates. A row is 20pt of padding
# plus 9pt per wrapped line (38pt for two lines, 47pt for three, as in the sample).
FIRST_TOP = 302.8
CONT_TOP = 89.3
BLOCK_BOTTOM = 487.5  # the Arrow ECS address footer box starts at 484.5
LAST_BOTTOM = 222.0  # the totals block starts at about y=218 on the last page
LINE_HEIGHT = 9.0
BLOCK_PADDING = 20.0

# Item columns: left edges for text, right edges for numbers.
X_LINE_NO = 21.9
X_ARROW_ITEM = 58.3
X_VENDOR_ITEM = 148.9
X_DESCRIPTION = 273.8
R_QTY = 505.8
R_RRP = 591.3
R_DISCOUNT = 662.0
R_UNIT_PRICE = 747.3
R_TOTAL = 818.9
X_CURRENCY = 821.9
ARROW_ITEM_WIDTH = 144.7 - X_ARROW_ITEM
VENDOR_ITEM_WIDTH = 271.0 - X_VENDOR_ITEM
DESCRIPTION_WIDTH = 457.7 - X_DESCRIPTION

# Item area cleared on each template page: (x0, top, x1, bottom).
ITEMS_AREA = {
    TEMPLATE_FIRST: (14.0, 301.0, 828.0, 483.5),
    TEMPLATE_CONT: (14.0, 87.2, 828.0, 483.5),
    TEMPLATE_LAST: (14.0, 87.2, 828.0, 217.6),
}

WHITE = (1.0, 1.0, 1.0)
PANEL_GREY = (0.827, 0.827, 0.827)  # first page's header panels
INFO_GREY = (0.961, 0.961, 0.961)  # complementary page's panels

# (key, text x, text top, cover right edge, cover top, cover bottom, cover fill)
HEADER_VALUES = [
    ("po_date", 655.0, 80.0, 822.0, 79.4, 88.6, PANEL_GREY),
    ("arrow_contact", 687.3, 181.6, 822.0, 181.0, 190.0, PANEL_GREY),
    ("arrow_email", 687.4, 193.1, 822.0, 192.5, 201.5, PANEL_GREY),
    ("end_user_number", 91.1, 237.3, 300.0, 236.8, 245.8, WHITE),
    ("quote_number", 80.9, 246.3, 300.0, 245.8, 254.8, WHITE),
]

INFO_VALUES = [
    ("reseller_company", 105.0, 86.6),
    ("reseller_contact", 104.8, 144.2),
    ("reseller_email", 104.8, 155.7),
    ("reseller_phone", 104.8, 167.2),
    ("end_user_company", 104.5, 229.5),
    ("end_user_contact", 104.5, 276.9),
    ("end_user_email", 104.5, 288.4),
    ("end_user_phone", 104.5, 299.9),
    ("reseller_zip_city", 105.0, 116.1),
    ("reseller_country", 105.0, 127.6),
    ("reseller_order_reference", 104.8, 178.8),
    ("end_user_zip_city", 105.0, 250.0),
    ("end_user_country", 105.0, 259.0),
    ("end_user_order_reference", 105.0, 311.5),
]
INFO_VALUE_RIGHT = 361.0

# Multi-line address blocks on the first page: (field key, text x, first line top, extra gap
# after the first line, max lines, cover box x0/top/x1/bottom, cover fill). The template's
# first address line sits a little higher than the rest, which are 9pt apart.
ADDRESS_PITCH = 9.0
ADDRESS_BLOCKS = [
    ("ship_to_block", 221.2, 91.6, 2.5, 9, (220.5, 90.5, 411.5, 172.0), PANEL_GREY),
    ("bill_to_block", 419.6, 92.2, 2.6, 9, (419.0, 90.5, 610.5, 172.0), PANEL_GREY),
]
# Ship To contact rows: (key, text x, text top). Values start after the bold label.
SHIP_TO_CONTACT_VALUES = [
    ("ship_to_contact", 258.7, 178.5),
    ("ship_to_phone", 258.7, 196.5),
    ("ship_to_email", 258.7, 208.0),
]
SHIP_TO_CONTACT_RIGHT = 411.5
# Street values on the Complementary page: (key, text x, first line top, max lines). The
# reseller's street wraps onto a second line in the sample; the end user's has room for one
# line only, so it shrinks to fit instead.
INFO_STREETS = [
    ("reseller_street", 105.0, 98.1, 2),
    ("end_user_street", 105.0, 241.0, 1),
]
# Terms of payment / Delivery terms values on the totals page.
X_TERMS_VALUE = 141.8
TERMS_RIGHT = 826.0
TERMS_FIRST_TOP = 265.4
TERMS_GAP = 13.9  # Delivery terms sits this far under Terms of payment in the template
# Special Information panel: (key, text x, first line top, line pitch, cover box).
SPECIAL_BLOCK = ("special_information", 374.5, 90.6, 9.0, (370.0, 88.5, 817.5, 325.0))


@dataclass
class _Block:
    line_no: str
    arrow_lines: list[str]
    vendor_lines: list[str]
    description_lines: list[str]
    qty: str
    rrp: str
    discount: str
    unit_price: str
    amount: Decimal
    height: float


@dataclass
class _PageSpec:
    template: int
    blocks: list[_Block] = field(default_factory=list)


def _money(value: Decimal) -> str:
    return format_amount(value, "us")


def _percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')).normalize():f}"


def _wrap_code(text: str, max_width: float) -> list[str]:
    """Wraps an item number after its hyphens, as the sample does
    ("RS-BT-BE-RSCP-PE-" / "PP"), falling back to character wrapping for a
    piece that is wider than the column on its own."""
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    for piece in re.findall(r"[^-]*-|[^-]+", text):
        if stringWidth(current + piece, FONT, FONT_SIZE) <= max_width:
            current += piece
            continue
        if current:
            lines.append(current)
            current = ""
        if stringWidth(piece, FONT, FONT_SIZE) <= max_width:
            current = piece
        else:
            chunks = wrap_chars(piece, max_width, FONT_SIZE)
            lines.extend(chunks[:-1])
            current = chunks[-1]
    if current:
        lines.append(current)
    return lines or [""]


def _description_with_terms(description: str, terms) -> str:
    description = description.strip()
    terms = str(terms or "").strip()
    if not terms:
        return description
    suffix = f"{terms} months" if terms.isdigit() else terms
    if suffix.lower() in description.lower():
        return description
    return f"{description} : {suffix}".strip(" :")


def _build_blocks(line_items: list[dict]) -> list[_Block]:
    blocks: list[_Block] = []
    for item in line_items:
        if not (item.get("part_number") or item.get("description")):
            continue

        qty = _to_decimal(item.get("qty"))
        unit_price = _to_decimal(item.get("unit_cost")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        discount = _to_decimal(str(item.get("pct_disc") or "").replace("%", ""))
        rrp = _to_decimal(item.get("rrp"))
        if rrp <= 0:
            rrp = unit_price / (1 - discount / 100) if discount < 100 else unit_price
        amount = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        part_number = str(item.get("part_number") or "").strip()
        description = _description_with_terms(str(item.get("description") or ""), item.get("terms"))
        arrow_lines = _wrap_code(part_number, ARROW_ITEM_WIDTH)
        vendor_lines = _wrap_code(part_number, VENDOR_ITEM_WIDTH)
        description_lines = wrap_text(description, DESCRIPTION_WIDTH, FONT_SIZE)
        line_count = max(len(arrow_lines), len(vendor_lines), len(description_lines))

        blocks.append(
            _Block(
                line_no=str(10 * (len(blocks) + 1)),
                arrow_lines=arrow_lines,
                vendor_lines=vendor_lines,
                description_lines=description_lines,
                qty=f"{qty.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f}",
                rrp=f"{_money(rrp.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))} $",
                discount=f"{_percent(discount)}%",
                unit_price=f"{_money(unit_price)} $",
                amount=amount,
                height=BLOCK_PADDING + LINE_HEIGHT * line_count,
            )
        )
    return blocks


def _paginate(blocks: list[_Block]) -> list[_PageSpec]:
    pages = [_PageSpec(TEMPLATE_FIRST)]
    y = FIRST_TOP
    for block in blocks:
        if pages[-1].blocks and y + block.height > BLOCK_BOTTOM:
            pages.append(_PageSpec(TEMPLATE_CONT))
            y = CONT_TOP
        pages[-1].blocks.append(block)
        y += block.height

    # The last items page doubles as the totals page when its rows leave room
    # for the totals block; otherwise a page with only the totals follows. The
    # first page can't be the totals page because the template's first page has
    # no totals block.
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


def _fit_size(text: str, font: str, size: float, max_width: float) -> float:
    while size > 4.0 and stringWidth(text, font, size) > max_width:
        size -= 0.25
    return size


def _text(
    c: canvas.Canvas,
    page_height: float,
    x: float,
    top: float,
    text: str,
    size: float = FONT_SIZE,
    bold: bool = False,
    align: str = "left",
) -> None:
    if not text:
        return
    font = FONT_BOLD if bold else FONT
    c.saveState()
    c.setFont(font, size)
    c.setFillColorRGB(0, 0, 0)
    baseline = page_height - top - size * BASELINE_FACTOR
    if align == "right":
        c.drawRightString(x, baseline, text)
    else:
        c.drawString(x, baseline, text)
    c.restoreState()


def _replace_value(
    c: canvas.Canvas,
    page_height: float,
    text: str,
    x: float,
    top: float,
    cover: tuple[float, float, float, float],
    fill=WHITE,
) -> None:
    """Covers a value with the panel's own color, then draws its replacement,
    shrinking the text if it would run past the cover's right edge."""
    cover_x0, cover_top, cover_x1, cover_bottom = cover
    _whiteout(c, page_height, cover_x0, cover_top, cover_x1, cover_bottom, fill)
    size = _fit_size(text, FONT, FONT_SIZE, cover_x1 - x - 1)
    _text(c, page_height, x, top, text, size)


def _draw_block(c: canvas.Canvas, page_height: float, block: _Block, top: float) -> None:
    _text(c, page_height, X_LINE_NO, top, block.line_no)
    for i, line in enumerate(block.arrow_lines):
        _text(c, page_height, X_ARROW_ITEM, top + LINE_HEIGHT * i, line)
    for i, line in enumerate(block.vendor_lines):
        _text(c, page_height, X_VENDOR_ITEM, top + LINE_HEIGHT * i, line)
    for i, line in enumerate(block.description_lines):
        _text(c, page_height, X_DESCRIPTION, top + LINE_HEIGHT * i, line)
    _text(c, page_height, R_QTY, top, block.qty, align="right")
    _text(c, page_height, R_RRP, top, block.rrp, align="right")
    _text(c, page_height, R_DISCOUNT, top, block.discount, align="right")
    _text(c, page_height, R_UNIT_PRICE, top, block.unit_price, align="right")
    _text(c, page_height, R_TOTAL, top, _money(block.amount), align="right")
    _text(c, page_height, X_CURRENCY, top, "$")


def _draw_header_values(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    """Values on the first page's header panels and comments, which print once."""
    for key, x, top, cover_x1, cover_top, cover_bottom, fill in HEADER_VALUES:
        if key not in fields:
            continue
        _replace_value(
            c, page_height, str(fields[key] or ""), x, top, (x - 1.5, cover_top, cover_x1, cover_bottom), fill
        )


def _wrapped_lines(text: str, width: float) -> list[str]:
    """Each line the user typed, word-wrapped to the width; blank lines are dropped."""
    lines: list[str] = []
    for raw in str(text or "").split("\n"):
        if raw.strip():
            lines.extend(wrap_text(raw.strip(), width, FONT_SIZE))
    return lines


def _draw_address_blocks(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    """Ship To / Billing addresses and the Ship To contact rows on the first page. The
    template's own lines sit under a grey cover so only the edited text shows. A block
    whose field isn't supplied keeps the template's text."""
    for key, x, first_top, gap, max_lines, cover, fill in ADDRESS_BLOCKS:
        if key not in fields:
            continue
        _whiteout(c, page_height, *cover, fill)
        lines = _wrapped_lines(fields.get(key), cover[2] - x - 1)
        for i, line in enumerate(lines[:max_lines]):
            top = first_top if i == 0 else first_top + gap + ADDRESS_PITCH * i
            _text(c, page_height, x, top, line)
    for key, x, top in SHIP_TO_CONTACT_VALUES:
        if key not in fields:
            continue
        _replace_value(
            c,
            page_height,
            str(fields[key] or ""),
            x,
            top,
            (x - 1.5, top - 0.6, SHIP_TO_CONTACT_RIGHT, top + 8.6),
            PANEL_GREY,
        )


def _wrap_bold(text: str, max_width: float) -> list[str]:
    """Word-wraps bold text (wider than regular, so wrap_text can't measure it); a single
    word wider than the line falls back to character wrapping."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, FONT_BOLD, FONT_SIZE) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if stringWidth(word, FONT_BOLD, FONT_SIZE) <= max_width:
            current = word
        else:
            for ch in word:
                if stringWidth(current + ch, FONT_BOLD, FONT_SIZE) > max_width:
                    lines.append(current)
                    current = ""
                current += ch
    if current:
        lines.append(current)
    return lines or [""]


def _draw_totals(c: canvas.Canvas, page_height: float, fields: dict, grand_total: Decimal) -> None:
    total_text = _money(grand_total)

    _whiteout(c, page_height, 740.0, 219.2, 828.0, 228.0)
    _text(c, page_height, 818.8, 219.3, total_text, align="right")
    _text(c, page_height, 821.9, 219.3, "$")

    # Prices in this document carry no VAT, so the VAT amount is always 0.
    _whiteout(c, page_height, 740.0, 232.8, 828.0, 241.05)
    _text(c, page_height, 824.3, 233.0, f"{_money(Decimal('0'))}$", align="right")

    _whiteout(c, page_height, 740.0, 242.2, 828.0, 250.6)
    _text(c, page_height, 818.7, 242.6, total_text, bold=True, align="right")
    _text(c, page_height, 819.9, 242.6, "$")

    # Terms values are bold and can be long, so they wrap inside the page's right margin. The
    # template puts Delivery terms 13.9pt under Terms of payment; each extra payment line
    # pushes it down one more line so the two never overlap.
    top = TERMS_FIRST_TOP
    # The template's own values sit at two fixed heights; clear both rows once so no old
    # text is left showing between the redrawn lines, whatever the new lines' heights.
    for key, row_top in (("payment_terms", TERMS_FIRST_TOP), ("delivery_terms", TERMS_FIRST_TOP + TERMS_GAP)):
        if key in fields:
            _whiteout(c, page_height, X_TERMS_VALUE - 1.8, row_top - 0.5, 828.0, row_top + 9.0)
    for key, template_gap in (("payment_terms", TERMS_GAP), ("delivery_terms", 0.0)):
        if key not in fields:
            top += template_gap
            continue
        lines = _wrap_bold(str(fields[key] or ""), TERMS_RIGHT - X_TERMS_VALUE)
        _whiteout(c, page_height, X_TERMS_VALUE - 1.8, top - 0.5, 828.0, top + LINE_HEIGHT * max(len(lines), 1) - 0.5)
        for i, line in enumerate(lines):
            _text(c, page_height, X_TERMS_VALUE, top + LINE_HEIGHT * i, line, bold=True)
        top += template_gap + LINE_HEIGHT * max(len(lines) - 1, 0)
        if key == "payment_terms" and len(lines) > 1:
            # The Delivery terms label is template text at its original height; cover it and
            # draw it again beside the value's new position.
            label_top = TERMS_FIRST_TOP + TERMS_GAP
            _whiteout(c, page_height, 20.0, label_top - 0.5, X_TERMS_VALUE - 1.8, label_top + 9.0)
            _text(c, page_height, 26.9, top, "Delivery terms:", bold=True)


def _draw_po_number(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    if "po_number" not in fields:
        return
    text = str(fields["po_number"] or "")
    _whiteout(c, page_height, 641.0, 16.5, 830.0, 36.5)
    size = _fit_size(text, FONT_BOLD, 18.0, 826.0 - 685.3)
    _text(c, page_height, 685.3, 17.3, text, size, bold=True)


def _draw_items_page(
    c: canvas.Canvas,
    page_height: float,
    spec: _PageSpec,
    number: int,
    total_pages: int,
    fields: dict,
    grand_total: Decimal,
) -> None:
    x0, top, x1, bottom = ITEMS_AREA[spec.template]
    _whiteout(c, page_height, x0, top, x1, bottom)

    _draw_po_number(c, page_height, fields)
    _whiteout(c, page_height, 760.0, 541.0, 828.0, 550.0)
    _text(c, page_height, 826.0, 541.4, f"Page {number} of {total_pages}", align="right")

    if spec.template == TEMPLATE_FIRST:
        _draw_header_values(c, page_height, fields)
        _draw_address_blocks(c, page_height, fields)

    y = FIRST_TOP if spec.template == TEMPLATE_FIRST else CONT_TOP
    for block in spec.blocks:
        _draw_block(c, page_height, block, y)
        y += block.height

    if spec.template == TEMPLATE_LAST:
        _draw_totals(c, page_height, fields, grand_total)


def _draw_info_page(c: canvas.Canvas, page_height: float, fields: dict) -> None:
    for key, x, top in INFO_VALUES:
        if key not in fields:
            continue
        _replace_value(
            c,
            page_height,
            str(fields[key] or ""),
            x,
            top,
            (x - 1.5, top - 0.6, INFO_VALUE_RIGHT, top + 8.6),
            INFO_GREY,
        )

    for key, x, top, max_lines in INFO_STREETS:
        if key not in fields:
            continue
        lines = _wrapped_lines(fields.get(key), INFO_VALUE_RIGHT - x - 1)
        # The cover spans every line the street can use.
        cover = (x - 1.5, top - 0.6, INFO_VALUE_RIGHT, top + 9.0 * (max_lines - 1) + 8.6)
        if max_lines == 1:
            _replace_value(c, page_height, " ".join(lines), x, top, cover, INFO_GREY)
            continue
        _whiteout(c, page_height, *cover, INFO_GREY)
        for i, line in enumerate(lines[:max_lines]):
            _text(c, page_height, x, top + 9.0 * i, line)

    key, x, first_top, pitch, cover = SPECIAL_BLOCK
    if key in fields:
        _whiteout(c, page_height, *cover, INFO_GREY)
        for i, line in enumerate(_wrapped_lines(fields.get(key), cover[2] - x - 1)):
            top = first_top + pitch * i
            if top + 8.0 > cover[3]:
                break
            _text(c, page_height, x, top, line)


def generate_arrow_netherlands_po(fields: dict, line_items: list[dict]) -> bytes:
    path = find_template_path(SLUG)
    if path is None:
        raise FileNotFoundError(f"No template PDF found for distributor '{SLUG}'")

    pdf_bytes = path.read_bytes()

    blocks = _build_blocks(line_items)
    grand_total = sum((b.amount for b in blocks), Decimal("0"))
    pages = _paginate(blocks)

    writer = PdfWriter()
    for number, spec in enumerate(pages, start=1):
        page = _fresh_page(pdf_bytes, spec.template)
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        overlay = _render_overlay(
            width,
            height,
            lambda c, s=spec, n=number, h=height: _draw_items_page(c, h, s, n, len(pages), fields, grand_total),
        )
        page.merge_page(overlay.pages[0])
        writer.add_page(page)

    info_page = _fresh_page(pdf_bytes, TEMPLATE_INFO)
    width, height = float(info_page.mediabox.width), float(info_page.mediabox.height)
    overlay = _render_overlay(width, height, lambda c: _draw_info_page(c, height, fields))
    info_page.merge_page(overlay.pages[0])
    writer.add_page(info_page)

    output = io.BytesIO()
    writer.write(output)
    pdf_output = output.getvalue()

    po_number = (fields.get("po_number") or "PO").strip().replace("/", "-").replace(" ", "_") or "PO"
    out_dir = Path(config.GENERATED_DIR) / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{po_number}.pdf").write_bytes(pdf_output)

    return pdf_output
