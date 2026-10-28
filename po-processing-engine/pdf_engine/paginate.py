"""Distributor-agnostic pagination engine for the dynamic line-items table.

Given a `TableLayout` and a list of line items, lays rows out top-down,
wraps long descriptions to the column width, and breaks onto as many
"items" pages as needed before always emitting one final "trailer" page.
This mirrors the convention observed in the ARROW E.C.S. sample: a running
subtotal footer on every items page, and a dedicated trailer page with the
subtotal repeated + grand total + payment/shipping fields.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from reportlab.pdfbase.pdfmetrics import stringWidth

from pdf_engine.models import TableLayout

FONT_NAME = "Helvetica"


def _to_decimal(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    text = str(value).strip()
    # Accept both "1.234,56" (es-ES) and "1234.56" style input from the form.
    if "," in text and text.count(",") == 1 and text.rfind(",") > text.rfind("."):
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def format_amount(value: Decimal, style: str = "eu") -> str:
    quantized = value.quantize(Decimal("0.01"))
    sign = "-" if quantized < 0 else ""
    quantized = abs(quantized)
    whole, _, frac = f"{quantized:.2f}".partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    if style == "us":
        return f"{sign}{','.join(groups)}.{frac}"
    return f"{sign}{'.'.join(groups)},{frac}"


def wrap_text(text: str, max_width: float, font_size: float) -> list[str]:
    if not text:
        return [""]
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, FONT_NAME, font_size) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def wrap_chars(text: str, max_width: float, font_size: float) -> list[str]:
    """Wraps text onto multiple lines by raw character count, not words.

    Part numbers/codes are typically one hyphenated token with no spaces, so
    `wrap_text`'s word-splitting never breaks them -- a long code would just
    overflow its column. Some source PDFs (e.g. the exclusive-networks-south-
    africa sample) wrap these mid-character when the column is narrow (e.g.
    "RS-UR-FE-USL-P" / "E-RSV"), so we mirror that instead of letting the text
    bleed into the next column.
    """
    if not text:
        return [""]
    if stringWidth(text, FONT_NAME, font_size) <= max_width:
        return [text]
    lines: list[str] = []
    current = ""
    for ch in text:
        candidate = current + ch
        if stringWidth(candidate, FONT_NAME, font_size) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines or [""]


@dataclass
class RowLayout:
    item: dict
    description_lines: list[str]
    part_number_lines: list[str]
    line_amount: Decimal
    height: float


@dataclass
class ItemsPage:
    rows: list[RowLayout]
    running_subtotal: Decimal
    is_first: bool = False


@dataclass
class PaginationResult:
    items_pages: list[ItemsPage] = field(default_factory=list)
    grand_total: Decimal = Decimal("0")


def _build_row_layout(table: TableLayout, item: dict) -> RowLayout:
    columns = table.columns
    desc_index = next(i for i, c in enumerate(columns) if c.key == "description")
    desc_col = columns[desc_index]
    # The description column's own x1 (captured from the sample PDF's actual
    # printed text) can sit past where the next column visually starts, since
    # that text never got wide enough to reveal the true boundary. Cap
    # wrapping at the next column's start so long user-edited descriptions
    # can't run into it.
    desc_right_limit = desc_col.x1
    if desc_index + 1 < len(columns):
        desc_right_limit = min(desc_right_limit, columns[desc_index + 1].x0 - 6)
    description = str(item.get("description") or "")
    wrapped = wrap_text(description, desc_right_limit - desc_col.x0 - 2, table.font_size)

    part_index = next((i for i, c in enumerate(columns) if c.key == "part_number"), None)
    part_lines = [str(item.get("part_number") or "")]
    if part_index is not None:
        part_col = columns[part_index]
        part_right_limit = part_col.x1
        if part_index + 1 < len(columns):
            part_right_limit = min(part_right_limit, columns[part_index + 1].x0 - 6)
        part_lines = wrap_chars(
            str(item.get("part_number") or ""), part_right_limit - part_col.x0 - 2, table.font_size
        )

    qty = _to_decimal(item.get("qty"))
    unit_cost = _to_decimal(item.get("unit_cost"))
    pct_disc = _to_decimal(item.get("pct_disc"))
    line_amount = qty * unit_cost * (Decimal("1") - pct_disc / Decimal("100"))

    main_lines = max(1, len(wrapped), len(part_lines))
    height = main_lines * table.row_line_height
    if item.get("terms"):
        height += table.terms_line_height

    return RowLayout(
        item=item,
        description_lines=wrapped,
        part_number_lines=part_lines,
        line_amount=line_amount,
        height=height,
    )


def paginate(table: TableLayout, line_items: list[dict]) -> PaginationResult:
    rows = [_build_row_layout(table, item) for item in line_items if item]

    pages: list[ItemsPage] = []
    current_rows: list[RowLayout] = []
    y = table.items_page_first_row_top
    is_first_page = True
    running_subtotal = Decimal("0")

    def close_page():
        nonlocal current_rows, y, is_first_page
        pages.append(
            ItemsPage(rows=current_rows, running_subtotal=running_subtotal, is_first=is_first_page)
        )
        current_rows = []
        y = table.items_page_first_row_top
        is_first_page = False

    for row in rows:
        max_bottom = (
            table.items_page_max_row_bottom
            if is_first_page
            else table.continuation_page_max_row_bottom
        )
        if current_rows and y + row.height > max_bottom:
            close_page()
        current_rows.append(row)
        running_subtotal += row.line_amount
        y += row.height

    # Always emit at least one items page, even with zero rows.
    if current_rows or not pages:
        pages.append(
            ItemsPage(rows=current_rows, running_subtotal=running_subtotal, is_first=is_first_page)
        )

    return PaginationResult(items_pages=pages, grand_total=running_subtotal)
