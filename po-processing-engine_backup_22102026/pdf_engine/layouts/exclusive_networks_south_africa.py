"""Hardcoded coordinate layout for Exclusive Networks (South Africa) purchase orders.

Coordinates were captured by dumping pdfplumber's word-level extraction
(top/x0/x1 per word) for both pages of the sample template
`data/templates/exclusive-networks-south-africa/Rubrik_Business Connexion
(Pty) Limited_PO162221 29.04.2026 (1) (1).pdf` and reading off each field's
bounding box directly from the real text positions.

Page geometry in the sample:
  - Page 0: header (PO number, PO date, account number), the items table
    (header row at top≈276.5), and a totals/signature/footer block fixed at
    y≈693-800 (Sub Total / Discount / Total Excl Tax / Tax / Total (Incl),
    each with a static "$" glyph that must never be overwritten).
  - Page 1: a dedicated trailer page. Same header/totals block repeated,
    plus an info panel (Quote #, reseller/end user, contact, address,
    shipment/payment terms). Most of that info panel is static distributor
    boilerplate (dispatch instructions, the vendor's own "Ship to"/contact
    block, a billing address) — only the lines that clearly vary per order
    are modeled as fields here; the rest is left as untouched background.
  - Each line item prints as up to 3 stacked lines: a "value" line carrying
    the first half of part_number + description plus qty/unit_cost/amount,
    a "continuation" line ~10.2pt below it carrying the second half of
    part_number (concatenated with no separator, e.g. "RS-UR-FE-USL-P" +
    "E-RSV" -> "RS-UR-FE-USL-PE-RSV") and of description (space-joined),
    and an optional "Terms:..." line ~14.3pt further below. In the sample,
    item 4's terms line overflows onto page 1, printed directly under a
    repeated copy of the items-table header row baked into that page's
    static background — `trailer_whiteout_regions` blanks both.
"""

from pdf_engine.models import DistributorLayout, FieldBox, TableColumn, TableLayout

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 841.89

_HEADER_FIELD_SPECS = [
    # key, x0, top, x1, bottom, font_size, align
    ("po_number", 520.0, 175.5, 576.0, 187.5, 9.0, "left"),
    ("po_date", 520.0, 201.5, 576.0, 213.5, 9.0, "left"),
    ("account_number", 520.0, 227.5, 576.0, 239.5, 9.0, "left"),
]

# Identical fields printed on both page 0 and page 1 of the sample.
HEADER_FIELDS = [
    FieldBox(key, page, x0, top, x1, bottom, font_size, align)
    for (key, x0, top, x1, bottom, font_size, align) in _HEADER_FIELD_SPECS
    for page in (0, 1)
]

_TOTALS_FIELD_SPECS = [
    # key, x0, top, x1, bottom, font_size, align
    ("discount", 548.0, 713.5, 576.0, 726.0, 9.0, "right"),
    ("total_excl_tax", 520.0, 734.0, 576.0, 746.5, 9.0, "right"),
    ("tax", 548.0, 754.0, 576.0, 766.5, 9.0, "right"),
    ("total_incl", 516.0, 784.0, 576.0, 797.0, 9.0, "right"),
]

TOTALS_FIELDS = [
    FieldBox(key, page, x0, top, x1, bottom, font_size, align)
    for (key, x0, top, x1, bottom, font_size, align) in _TOTALS_FIELD_SPECS
    for page in (0, 1)
]

INFO_PANEL_FIELDS: list[FieldBox] = []

# Page-1-only fields: the repeated subtotal plus the order-specific lines
# from the info panel. Each real line sits on its own ~10pt pitch with no
# blank space between adjacent lines, so boxes are kept tight to the line's
# own top to avoid bleeding into a neighboring field.
TRAILER_FIELDS = [
    FieldBox("subtotal_repeat", 1, 520.0, 693.5, 576.0, 706.0, 9.0, "right"),
    FieldBox("quote_number_line", 1, 35.0, 309.3, 300.0, 320.3, 8.5, "left"),
    FieldBox("reseller_end_user_line", 1, 35.0, 329.2, 400.0, 340.2, 8.5, "left"),
    FieldBox("reseller_po_number_line", 1, 35.0, 339.2, 400.0, 350.2, 8.5, "left"),
    FieldBox("contact_person_line", 1, 35.0, 349.2, 400.0, 360.2, 8.5, "left"),
    FieldBox("tel_nr_line", 1, 35.0, 359.1, 300.0, 370.1, 8.5, "left"),
    FieldBox("address_block", 1, 35.0, 369.1, 400.0, 390.0, 8.5, "left", multiline=True),
    FieldBox("email_line", 1, 35.0, 389.0, 400.0, 400.0, 8.5, "left"),
    FieldBox("shipment_terms_line", 1, 35.0, 458.7, 300.0, 469.7, 8.5, "left"),
    FieldBox("payment_terms_line", 1, 35.0, 578.2, 400.0, 589.2, 8.5, "left"),
]

TABLE = TableLayout(
    columns=[
        TableColumn("part_number", 20.0, 98.0, "left"),
        TableColumn("description", 100.0, 223.0, "left"),
        TableColumn("qty", 225.0, 280.0, "right"),
        TableColumn("unit_cost", 355.0, 430.0, "right"),
        TableColumn("pct_disc", 430.0, 465.0, "right"),
        TableColumn("amount", 490.0, 572.0, "right"),
    ],
    # Kept well below the real header text (top=276.5) so the extractor's
    # `header_top + 15` row-filter cutoff doesn't clip the real first item
    # row (top=291.4) -- that off-by-a-hair cutoff was the root cause of the
    # first draft's garbled row clustering.
    header_top=270.0,
    items_page_first_row_top=291.4,
    items_page_max_row_bottom=690.0,
    continuation_page_max_row_bottom=690.0,
    footer_subtotal_box=FieldBox(
        "subtotal", 0, 520.0, 693.5, 576.0, 706.0, 9.0, "right"
    ),
    row_line_height=10.2,
    terms_line_height=14.5,
    font_size=8.5,
    terms_label="terms:",
)

PAGE_NUMBER_BOX = FieldBox("page_number", 0, 522.0, 245.2, 576.0, 257.0, 9.0, "left")

EXCLUSIVE_NETWORKS_SOUTH_AFRICA_LAYOUT = DistributorLayout(
    slug="exclusive-networks-south-africa",
    page_width=PAGE_WIDTH,
    page_height=PAGE_HEIGHT,
    items_page_template_index=0,
    trailer_page_template_index=1,
    header_fields=HEADER_FIELDS + TOTALS_FIELDS,
    info_panel_fields=INFO_PANEL_FIELDS,
    table=TABLE,
    trailer_fields=TRAILER_FIELDS,
    page_number_box=PAGE_NUMBER_BOX,
    currency_symbol="$",
    number_style="us",
    page_number_format="Page {page} of {total}",
    # Blanks the item-4 terms-line overflow + repeated items-table header
    # row baked into the trailer page's static background.
    trailer_whiteout_regions=[(16.0, 273.5, 576.0, 301.5)],
    # `account_number` is a fixed per-distributor constant (not a per-order
    # input) and the four totals fields below are already fully derived by
    # generator.generate_po from the line items plus discount/tax -- none of
    # these are real manual per-order entries, so they're hidden from the
    # Fields grid. `discount`/`tax` have no formula to derive from line items
    # (no per-order discount-amount or tax-rate source exists), so they're
    # hidden too and simply default to 0 unless a future data source appears.
    hidden_field_keys=frozenset(
        {"account_number", "discount", "total_excl_tax", "tax", "total_incl", "subtotal_repeat"}
    ),
)
