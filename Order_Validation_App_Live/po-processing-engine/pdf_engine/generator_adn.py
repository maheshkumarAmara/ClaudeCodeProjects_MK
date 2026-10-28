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
  - The template's static email addresses (the "E-mail:" in the header block,
    the licensee's address and the "E-mail:" in every page footer) are not form
    fields, so sandbox_email.sandbox_fields never sees them. They are removed
    from each page's content stream and redrawn on the sandbox domain.
"""

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from decimal import ROUND_HALF_UP, Decimal


from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream
from reportlab.pdfgen import canvas

import config
from pdf_engine.extractor import find_template_path
from pdf_engine.generator import _fresh_page, _render_overlay
from pdf_engine.paginate import _to_decimal, wrap_text
from sandbox_email import sandbox_text

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

# Static email addresses printed in the template: address -> (x, top, font size),
# in pdfplumber's top-down coordinates. The header and licensee addresses are on
# the first page only; the footer address is on every page.
TEMPLATE_EMAILS = {
    "iuliia.byshkina@adn.de": (434.5, 220.5, 6.75),
    "f.diroll@asklepios.com": (398.3, 386.8, 7.0),
    "info@adn.de": (486.7, 791.9, 6.0),
}

WHITE = (1.0, 1.0, 1.0)
FOOTER_GREY = (0.82745, 0.82745, 0.82745)


_HEX_RE = re.compile(r"<([0-9A-Fa-f]+)>")


def _parse_to_unicode(cmap: str) -> dict[int, str]:
    mapping: dict[int, str] = {}

    def decode(hex_text: str) -> str:
        return bytes.fromhex(hex_text).decode("utf-16-be")

    for block in re.findall(r"beginbfchar(.*?)endbfchar", cmap, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            mapping[int(src, 16)] = decode(dst)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", cmap, re.S):
        for lo, hi, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])", block):
            codes = range(int(lo, 16), int(hi, 16) + 1)
            if dst.startswith("["):
                for code, target in zip(codes, _HEX_RE.findall(dst)):
                    mapping[code] = decode(target)
            else:
                first = decode(dst[1:-1])
                for offset, code in enumerate(codes):
                    mapping[code] = first[:-1] + chr(ord(first[-1]) + offset)
    return mapping


def _strip_email_text(page) -> set[str]:
    """Remove every text-show operation containing an "@" from the page.

    The template's addresses are real ones, so painting over them would leave
    them in the PDF's text layer; dropping the operator removes them outright.
    Returns the decoded text of what was removed.
    """
    fonts = page["/Resources"].get("/Font", {})
    maps: dict[str, dict[int, str]] = {}
    for name, ref in fonts.items():
        font = ref.get_object()
        if "/ToUnicode" in font:
            maps[name] = _parse_to_unicode(font["/ToUnicode"].get_object().get_data().decode("latin-1"))

    content = ContentStream(page.get_contents(), page.pdf)
    removed: set[str] = set()
    current: dict[int, str] = {}
    kept = []
    for operands, operator in content.operations:
        if operator == b"Tf":
            current = maps.get(operands[0], {})
        elif operator in (b"Tj", b"TJ"):
            parts = [operands[0]] if operator == b"Tj" else [o for o in operands[0] if hasattr(o, "original_bytes")]
            decoded = "".join(
                current.get(int.from_bytes(raw[i : i + 2], "big"), "")
                for raw in (part.original_bytes for part in parts)
                for i in range(0, len(raw), 2)
            )
            if "@" in decoded:
                removed.add(decoded)
                continue
        kept.append((operands, operator))
    content.operations = kept
    page.replace_contents(content)
    return removed


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


def _build_blocks(line_items: list[dict]) -> list[_Block]:
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

        description_lines = wrap_text(str(item.get("description") or ""), DESCRIPTION_WIDTH, ITEM_FONT_SIZE)
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


def _draw_block(c: canvas.Canvas, page_height: float, block: _Block, top: float) -> None:
    _text(c, page_height, 56.7, top, block.pos)
    _text(c, page_height, 86.5, top, block.item_number, bold=True)
    _text(c, page_height, 242.8, top, block.qty, align="right")
    _text(c, page_height, 325.0, top, block.unit_price, align="right")
    _text(c, page_height, 437.3, top, block.unit_price, align="right")
    _text(c, page_height, 535.7, top, _format_number(block.amount, 2), align="right")
    _text(c, page_height, 564.7, top, "0 %", align="right")

    if block.sku:
        _text(c, page_height, 86.5, top + SKU_OFFSET, f"[{block.sku}]")
    if block.sku and block.unit_text:
        _text(c, page_height, 86.5, top + UNIT_OFFSET, f"{block.sku} - {block.unit_text}", bold=True)
    for i, line in enumerate(block.description_lines):
        _text(c, page_height, 86.5, top + DESCRIPTION_OFFSET + LINE_HEIGHT * i, line)
    if block.terms:
        _text(
            c,
            page_height,
            86.5,
            top + DESCRIPTION_OFFSET + LINE_HEIGHT * len(block.description_lines),
            block.terms,
        )


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

    accepts_line = (
        f"ADN Distribution GmbH ACCEPTS ALL ADDITIONAL TERMS ON "
        f"{fields.get('quote_number', '')} DATED {fields.get('quote_date', '')}"
    )
    _whiteout(c, page_height, 56.0, 472.0, 566.0, 480.0)
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


def _draw_template_emails(c: canvas.Canvas, page_height: float, emails: set[str]) -> None:
    for address, (x, top, size) in TEMPLATE_EMAILS.items():
        if address in emails:
            _text(c, page_height, x, top, sandbox_text(address), size)


def _draw_page(
    c: canvas.Canvas,
    page_height: float,
    spec: _PageSpec,
    number: int,
    total_pages: int,
    fields: dict,
    grand_total: Decimal,
    balance: Decimal | None,
    emails: set[str],
) -> None:
    t = spec.template
    _draw_template_emails(c, page_height, emails)
    x0, top, x1, bottom = ITEMS_AREA[t]
    _whiteout(c, page_height, x0, top, x1, bottom)

    po_top = PO_LINE_TOP[t]
    _whiteout(c, page_height, 56.0, po_top - 2.5, 300.0, po_top + 12.5)
    _text(c, page_height, 56.7, po_top, f"Purchase order {fields.get('po_number', '')}", 10, bold=True)

    page_top = PAGE_LABEL_TOP[t]
    _whiteout(c, page_height, 482.0, page_top - 2.5, 557.5, page_top + 9.5)
    _text(c, page_height, 483.2, page_top, "Page:", 6.8, bold=True)
    _text(c, page_height, 544.0, page_top, f"{number}/{total_pages}", 6.8)

    if t == TEMPLATE_FIRST:
        _draw_header_values(c, page_height, fields)

    y = FIRST_TOP if t == TEMPLATE_FIRST else CONT_TOP
    for block in spec.blocks:
        _draw_block(c, page_height, block, y)
        y += block.height

    if balance is not None:
        _whiteout(c, page_height, 480.0, 749.0, 540.5, 758.5, fill=FOOTER_GREY)
        _text(c, page_height, 540.0, 750.4, _format_number(balance, 2), 8, bold=True, align="right")

    if t == TEMPLATE_LAST:
        _draw_totals(c, page_height, fields, grand_total)


def generate_adn_po(fields: dict, line_items: list[dict]) -> bytes:
    path = find_template_path(SLUG)
    if path is None:
        raise FileNotFoundError(f"No template PDF found for distributor '{SLUG}'")

    pdf_bytes = path.read_bytes()
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_width = float(reader.pages[0].mediabox.width)
    page_height = float(reader.pages[0].mediabox.height)

    blocks = _build_blocks(line_items)
    grand_total = sum((b.amount for b in blocks), Decimal("0"))
    pages = _paginate(blocks)

    writer = PdfWriter()
    running = Decimal("0")
    for number, spec in enumerate(pages, start=1):
        running += sum((b.amount for b in spec.blocks), Decimal("0"))
        balance = None if spec.template == TEMPLATE_LAST else running

        page = _fresh_page(pdf_bytes, spec.template)
        emails = _strip_email_text(page)
        overlay = _render_overlay(
            page_width,
            page_height,
            lambda c, s=spec, n=number, b=balance, e=emails: _draw_page(
                c, page_height, s, n, len(pages), fields, grand_total, b, e
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
