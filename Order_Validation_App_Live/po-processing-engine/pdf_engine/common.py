"""Helpers that several distributor generators used to define identically.

Only code whose copies were the same line for line lives here. Anything that
varies per generator (minimum font size, page height, text-drawing signature,
money format) is passed in or left in the generator that owns it.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

from pypdf import PdfWriter
from pypdf.annotations import Link
from reportlab.pdfbase.pdfmetrics import stringWidth

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

WHITE = (1.0, 1.0, 1.0)
BLACK = (0.0, 0.0, 0.0)
BLUE = (0.02, 0.388, 0.757)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")


def clip_text(text: str, font: str, size: float, max_width: float) -> str:
    """Drop characters from the end until the text fits max_width."""
    while text and stringWidth(text, font, size) > max_width:
        text = text[:-1]
    return text


def fit_size(text: str, font: str, size: float, max_width: float, min_size: float) -> float:
    """Shrink size in 0.1pt steps until the text fits max_width, but not below min_size."""
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 0.1
    return size


def money_2dp(value: Decimal) -> str:
    """1,234.50 -- two places, half-up, comma thousands."""
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def qty_text(value: Decimal) -> str:
    """Whole numbers without decimals, otherwise the normalised decimal; comma thousands."""
    return f"{int(value):,}" if value == value.to_integral_value() else f"{value.normalize():,f}"


def without_pulled_discount(line_items: list[dict]) -> list[dict]:
    """Line items for a generator that takes `pct_disc` OFF the amount.

    A row pulled from Salesforce shows the line's SBQQ__Discount__c in `pct_disc` and keeps the same
    text in `pct_disc_sf`. Its unit cost (SBQQ__NetPrice__c) is already net of that discount, so
    while `pct_disc` still equals `pct_disc_sf` it must not reduce the amount a second time: it is
    blanked here. A % the user typed over it (any other value) is kept and applies as before.
    A generator that only prints the figure (Arrow's Discount % and RRP) gets the rows unchanged."""
    cleaned = []
    for item in line_items:
        sf = str(item.get("pct_disc_sf") or "").strip()
        if sf and str(item.get("pct_disc") or "").strip() == sf:
            item = {**item, "pct_disc": ""}
        cleaned.append(item)
    return cleaned


# The order the page shows the Line items columns in until the user moves one.
FORM_DEFAULT_ORDER = ["sno", "part_number", "description", "qty", "unit_cost", "pct_disc", "terms", "total"]


def untouched_order(requested: list[str] | None) -> list[str] | None:
    """The requested column order, or None when nothing was moved: no request, or the form's own
    default order. A distributor's template rarely prints its columns in the form's order, so
    treating the form's default as a reorder would change the PDF of an untouched page."""
    if not requested or list(requested) == FORM_DEFAULT_ORDER:
        return None
    return requested


def order_columns(requested: list[str] | None, available: tuple[str, ...], anchors: dict[str, str] | None = None) -> list[str]:
    """The table's column keys in the order the user asked for (the form's `column_order`).

    `available` is the generator's own columns in their default order. Keys the form doesn't
    know (or that this PDF has no column for) are ignored, so the form can list columns the
    PDF lacks. A PDF column the form has no slot for is placed just before `anchors[key]`
    (e.g. Innocom's Exchange Rate travels with TERM), else it keeps its default place.
    With no usable request the default order is returned unchanged."""
    if not requested:
        return list(available)
    order = [k for k in requested if k in available]
    order = list(dict.fromkeys(order))
    for key in available:
        if key in order:
            continue
        anchor = (anchors or {}).get(key)
        if anchor in order:
            order.insert(order.index(anchor), key)
        else:
            default_at = available.index(key)
            order.insert(min(default_at, len(order)), key)
    return order


def column_boxes(x0: float, widths: dict[str, float], order: list[str]) -> dict[str, tuple[float, float]]:
    """Each column's (left, right) edge when the columns are laid side by side in `order`
    starting at x0. A column keeps its own width wherever it moves, so the table's overall
    width -- and the room each value has -- is the same as in the default order."""
    boxes: dict[str, tuple[float, float]] = {}
    x = x0
    for key in order:
        boxes[key] = (x, x + widths[key])
        x += widths[key]
    return boxes


def add_links(writer: PdfWriter, links: list, page_height: float) -> None:
    """Add clickable links to the last page. Each link is (left, top, right, bottom, uri) in top-down page coordinates."""
    page_index = len(writer.pages) - 1
    for left, top, right, bottom, uri in links:
        writer.add_annotation(
            page_number=page_index,
            annotation=Link(rect=(left, page_height - bottom, right, page_height - top), url=uri),
        )
