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


def add_links(writer: PdfWriter, links: list, page_height: float) -> None:
    """Add clickable links to the last page. Each link is (left, top, right, bottom, uri) in top-down page coordinates."""
    page_index = len(writer.pages) - 1
    for left, top, right, bottom, uri in links:
        writer.add_annotation(
            page_number=page_index,
            annotation=Link(rect=(left, page_height - bottom, right, page_height - top), url=uri),
        )
