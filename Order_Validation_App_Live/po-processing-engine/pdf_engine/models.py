"""Layout data structures shared by every distributor.

Each distributor gets one hardcoded `DistributorLayout` (see `layouts/`)
describing exactly where every editable value sits on its template PDF.
There is no runtime auto-detection of field positions.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldBox:
    """A single editable field's bounding box on one specific template page.

    Coordinates are in pdfplumber's coordinate space (origin top-left,
    y grows downward, same units as `page.width`/`page.height`), which is
    the space `extractor.py` reads in. `generator.py` converts to PDF's
    bottom-left-origin space when drawing with reportlab.
    """

    key: str
    page: int
    x0: float
    top: float
    x1: float
    bottom: float
    font_size: float = 9.0
    align: str = "left"  # "left" | "right"
    multiline: bool = False  # value may contain literal "\n" separated lines


@dataclass(frozen=True)
class TableColumn:
    key: str
    x0: float
    x1: float
    align: str = "left"  # "left" | "right"


@dataclass(frozen=True)
class TableLayout:
    columns: list[TableColumn]
    header_top: float
    items_page_first_row_top: float
    items_page_max_row_bottom: float
    continuation_page_max_row_bottom: float
    footer_subtotal_box: FieldBox
    row_line_height: float = 13.0
    terms_line_height: float = 11.0
    font_size: float = 8.5
    # When set, a lookahead row is only treated as the terms line if its text
    # starts with this (case-insensitive, whitespace stripped). Needed for
    # distributors whose item rows wrap a description-continuation line
    # between the main row and the terms row; leave unset (None) to keep the
    # original proximity-only behavior.
    terms_label: str | None = None


@dataclass(frozen=True)
class DistributorLayout:
    slug: str
    page_width: float
    page_height: float
    items_page_template_index: int
    trailer_page_template_index: int
    header_fields: list[FieldBox]
    info_panel_fields: list[FieldBox]
    table: TableLayout
    trailer_fields: list[FieldBox]
    page_number_box: FieldBox
    currency_symbol: str = ""
    # "eu" (default, e.g. 1.234,56) or "us" (e.g. 1,234.56) — passed to
    # paginate.format_amount for every drawn amount.
    number_style: str = "eu"
    # Composed with .format(page=..., total=...) when drawing the page number
    # box. "{page}" (default) preserves the original bare-numeral behavior.
    page_number_format: str = "{page}"
    # Extra (x0, top, x1, bottom) rectangles whited out unconditionally on the
    # trailer page, before fields are drawn — for static background artifacts
    # (e.g. overflow text baked into the template) that aren't real fields.
    trailer_whiteout_regions: list[tuple[float, float, float, float]] = field(default_factory=list)
    # Field keys extracted from the template but not shown as editable inputs
    # in the UI -- either because generator.py already derives their value
    # automatically (e.g. totals computed from line items) or because the
    # value is a fixed per-distributor constant rather than a per-order
    # input. The extracted/last-known value for each key is still round-
    # tripped through the frontend and submitted with the generate request,
    # so generator.py keeps receiving a value for any key it doesn't itself
    # compute (see static/script.js's hidden-field handling).
    hidden_field_keys: frozenset[str] = frozenset()

    def fields_for_page(self, page_index: int) -> list[FieldBox]:
        all_boxes = self.header_fields + self.info_panel_fields + self.trailer_fields
        return [f for f in all_boxes if f.page == page_index]
