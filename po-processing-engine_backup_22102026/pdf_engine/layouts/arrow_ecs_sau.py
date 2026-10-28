"""Hardcoded coordinate layout for ARROW E.C.S., SAU purchase orders.

Coordinates were captured by running pdfplumber's word extraction against
the sample template `data/templates/arrow-ecs-sau/CP26-34785.pdf` and
reading off each field's bounding box. Boxes are padded a few points wider
than the observed text so a longer replacement value isn't clipped and the
whiteout fully covers the original.

Page geometry discovered in the sample:
  - Page 0 carries the header, the first block of item rows (top ≈343,
    capped around y≈430), a fixed "order info" panel (Quote #, END USER,
    RESELLER, ship-to, carrier) that always sits at y≈438-698 on the very
    first page, and a running-subtotal ("Suma") footer fixed at y≈713-723.
  - Page 1 is a dedicated trailer page: header repeated, "Suma" repeated
    near the top, "Total USD IVA excl.", then payment/shipping fields.
  - If line items overflow page 0's capacity, continuation item pages are
    synthesized by cloning page 0's background with the info panel blanked
    out, letting rows run further down (to just above the Suma footer).
"""

from pdf_engine.models import DistributorLayout, FieldBox, TableColumn, TableLayout

PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0

_HEADER_FIELD_SPECS = [
    # key, x0, top, x1, bottom, font_size, align
    ("supplier_ref", 133.2, 245.2, 230.0, 256.2, 9.0, "left"),
    ("po_date", 341.5, 245.2, 430.0, 256.2, 9.0, "left"),
    ("expected_receipt_date", 133.0, 257.2, 230.0, 268.2, 9.0, "left"),
    ("po_number", 448.7, 269.2, 560.0, 280.2, 9.0, "left"),
    ("buyer", 133.2, 281.2, 330.0, 292.2, 9.0, "left"),
    ("precios_iva_incluido", 448.5, 281.2, 490.0, 292.2, 9.0, "left"),
]

# These identical fields are printed on both page 0 and page 1 of the
# original sample; give each one a FieldBox per page it appears on.
HEADER_FIELDS = [
    FieldBox(key, page, x0, top, x1, bottom, font_size, align)
    for (key, x0, top, x1, bottom, font_size, align) in _HEADER_FIELD_SPECS
    for page in (0, 1)
]

# Fixed "order info" panel — only ever printed once, on page 0, regardless
# of how many item rows precede it or how many continuation pages follow.
INFO_PANEL_FIELDS = [
    FieldBox("quote_number", 0, 121.3, 437.1, 300.0, 448.1, 8.5, "left"),
    FieldBox("po_end_user_number", 0, 121.3, 449.1, 300.0, 460.1, 8.5, "left"),
    FieldBox("delivery_terms", 0, 121.3, 461.0, 300.0, 472.0, 8.5, "left"),
    FieldBox("bill_to_email", 0, 121.3, 473.0, 300.0, 484.0, 8.5, "left"),
    FieldBox("end_user_block", 0, 121.3, 485.0, 300.0, 545.0, 8.5, "left", multiline=True),
    FieldBox("carrier_number", 0, 121.3, 545.0, 300.0, 556.0, 8.5, "left"),
    FieldBox("carrier_contact", 0, 121.3, 557.0, 300.0, 568.0, 8.5, "left"),
    FieldBox("carrier_phone", 0, 121.3, 569.0, 300.0, 580.0, 8.5, "left"),
    FieldBox("carrier_email", 0, 121.3, 581.0, 300.0, 592.0, 8.5, "left"),
    FieldBox("reseller_block", 0, 121.3, 593.0, 300.0, 653.0, 8.5, "left", multiline=True),
    FieldBox("ship_to_block", 0, 121.3, 653.0, 300.0, 699.0, 8.5, "left", multiline=True),
]

TRAILER_FIELDS = [
    FieldBox("payment_terms", 1, 139.1, 437.1, 300.0, 448.1, 8.5, "left"),
    FieldBox("payment_method", 1, 139.1, 449.1, 300.0, 460.1, 8.5, "left"),
    FieldBox("shipping_conditions", 1, 139.1, 461.0, 300.0, 472.0, 8.5, "left"),
    # Repeated subtotal + grand total, printed near the top of the trailer page.
    FieldBox("subtotal_repeat", 1, 445.0, 341.0, 517.0, 351.5, 9.0, "right"),
    FieldBox("total", 1, 445.0, 377.0, 517.0, 388.0, 9.0, "right"),
]

TABLE = TableLayout(
    columns=[
        TableColumn("part_number", 14.2, 131.0, "left"),
        TableColumn("description", 151.1, 380.0, "left"),
        TableColumn("qty", 330.0, 389.2, "right"),
        TableColumn("unit_cost", 391.0, 430.9, "right"),
        TableColumn("pct_disc", 433.0, 461.0, "right"),
        TableColumn("amount", 463.0, 520.2, "right"),
    ],
    header_top=308.5,
    items_page_first_row_top=343.1,
    items_page_max_row_bottom=430.0,
    continuation_page_max_row_bottom=700.0,
    footer_subtotal_box=FieldBox(
        "subtotal", 0, 445.0, 713.0, 517.0, 723.5, 9.0, "right"
    ),
    row_line_height=13.0,
    terms_line_height=11.0,
    font_size=8.5,
)

# "Pág. N" sits at a fixed spot near the top-right of every page in the
# sample; only the numeral is redrawn per output page (the "Pág." label
# itself is part of the template background). Same position on both
# template pages, so one box covers every page we might clone.
PAGE_NUMBER_BOX = FieldBox("page_number", 0, 368.6, 41.5, 400.0, 52.5, 8.98, "left")

ARROW_ECS_SAU_LAYOUT = DistributorLayout(
    slug="arrow-ecs-sau",
    page_width=PAGE_WIDTH,
    page_height=PAGE_HEIGHT,
    items_page_template_index=0,
    trailer_page_template_index=1,
    header_fields=HEADER_FIELDS,
    info_panel_fields=INFO_PANEL_FIELDS,
    table=TABLE,
    trailer_fields=TRAILER_FIELDS,
    page_number_box=PAGE_NUMBER_BOX,
    currency_symbol="",
)
