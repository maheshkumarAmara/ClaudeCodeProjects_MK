"""Regenerates a distributor's PO PDF from edited field values + line items.

Technique: redact-and-overlay. For every value we might change, paint a white
rectangle over its original position and draw the new text at the same spot
with reportlab, then merge that overlay onto the original template page with
pypdf. The line-items table is laid out by `paginate.py`, which decides how
many "items" pages are needed; any page beyond the first clones the template's
first items page as a background (with its fixed info panel blanked out) since
we only have one real items-page sample to work from. A single trailer page
always follows, reusing the template's trailer page background.
"""

import io
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

import config
from pdf_engine.extractor import find_template_path
from pdf_engine.layouts import get_layout
from pdf_engine.models import DistributorLayout, FieldBox, TableLayout
from pdf_engine.paginate import ItemsPage, RowLayout, _to_decimal, format_amount, paginate

WHITEOUT_PAD = 1.0


def _draw_whiteout(c: canvas.Canvas, page_height: float, x0: float, top: float, x1: float, bottom: float) -> None:
    c.saveState()
    c.setFillColorRGB(1, 1, 1)
    y = page_height - bottom - WHITEOUT_PAD
    height = (bottom - top) + 2 * WHITEOUT_PAD
    c.rect(x0 - WHITEOUT_PAD, y, (x1 - x0) + 2 * WHITEOUT_PAD, height, fill=1, stroke=0)
    c.restoreState()


def _draw_field(c: canvas.Canvas, page_height: float, box: FieldBox, value: str) -> None:
    _draw_whiteout(c, page_height, box.x0, box.top, box.x1, box.bottom)
    if not value:
        return
    c.setFont("Helvetica", box.font_size)
    c.setFillColorRGB(0, 0, 0)
    lines = value.split("\n") if box.multiline else [value]
    line_height = box.font_size + 2.5
    baseline = page_height - box.top - box.font_size
    for i, line in enumerate(lines):
        y = baseline - i * line_height
        if box.align == "right":
            c.drawRightString(box.x1, y, line)
        else:
            c.drawString(box.x0, y, line)


def _draw_row(
    c: canvas.Canvas,
    page_height: float,
    table: TableLayout,
    row: RowLayout,
    row_top: float,
    number_style: str = "eu",
) -> None:
    c.setFont("Helvetica", table.font_size)
    c.setFillColorRGB(0, 0, 0)
    item = row.item
    baseline = page_height - row_top - table.font_size

    for col in table.columns:
        if col.key == "description":
            for i, line in enumerate(row.description_lines):
                y = baseline - i * table.row_line_height
                c.drawString(col.x0, y, line)
            continue
        if col.key == "part_number":
            for i, line in enumerate(row.part_number_lines):
                y = baseline - i * table.row_line_height
                c.drawString(col.x0, y, line)
            continue
        text = format_amount(row.line_amount, number_style) if col.key == "amount" else str(item.get(col.key) or "")
        if not text:
            continue
        if col.align == "right":
            c.drawRightString(col.x1, baseline, text)
        else:
            c.drawString(col.x0, baseline, text)

    if item.get("terms"):
        main_lines = max(1, len(row.description_lines), len(row.part_number_lines))
        terms_top = row_top + main_lines * table.row_line_height
        terms_baseline = page_height - terms_top - table.font_size + 1
        c.drawString(table.columns[1].x0 - 30, terms_baseline, str(item["terms"]))


def _render_overlay(page_width: float, page_height: float, draw_fn) -> "PdfReader":
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    draw_fn(c)
    c.showPage()
    c.save()
    buffer.seek(0)
    return PdfReader(buffer)


def _fresh_page(pdf_bytes: bytes, index: int):
    # Re-opening the source bytes for every page we place gives each one an
    # independent PageObject, so merge_page() on one can't bleed into another
    # (needed since several output pages clone the same template page).
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return reader.pages[index]


def _build_items_page(
    pdf_bytes: bytes,
    layout: DistributorLayout,
    items_page: ItemsPage,
    field_values: dict,
    page_number: int,
    total_pages: int,
) -> "object":
    table = layout.table
    template_index = layout.items_page_template_index
    page_w, page_h = layout.page_width, layout.page_height
    info_panel_keys = {f.key for f in layout.info_panel_fields}
    page = _fresh_page(pdf_bytes, template_index)

    def draw(c: canvas.Canvas) -> None:
        for box in layout.fields_for_page(template_index):
            if box.key in info_panel_keys and not items_page.is_first:
                _draw_whiteout(c, page_h, box.x0, box.top, box.x1, box.bottom)
                continue
            _draw_field(c, page_h, box, field_values.get(box.key, ""))

        page_number_text = layout.page_number_format.format(page=page_number, total=total_pages)
        _draw_field(c, page_h, layout.page_number_box, page_number_text)

        body_bottom = (
            table.items_page_max_row_bottom if items_page.is_first else table.continuation_page_max_row_bottom
        )
        # Top edge sits just above the first row rather than just below the
        # column-header text: the header prints as two stacked lines (e.g.
        # "Coste unit" / "directo"), and a fixed offset from header_top was
        # clipping into the header's own glyphs.
        _draw_whiteout(
            c,
            page_h,
            table.columns[0].x0 - 4,
            table.items_page_first_row_top - 4,
            table.columns[-1].x1 + 4,
            body_bottom + 4,
        )

        y = table.items_page_first_row_top
        for row in items_page.rows:
            _draw_row(c, page_h, table, row, y, layout.number_style)
            y += row.height

        subtotal_box = table.footer_subtotal_box
        _draw_field(c, page_h, subtotal_box, format_amount(items_page.running_subtotal, layout.number_style))

    overlay = _render_overlay(page_w, page_h, draw)
    page.merge_page(overlay.pages[0])
    return page


def _build_trailer_page(
    pdf_bytes: bytes, layout: DistributorLayout, field_values: dict, page_number: int, total_pages: int
) -> "object":
    template_index = layout.trailer_page_template_index
    page_w, page_h = layout.page_width, layout.page_height
    page = _fresh_page(pdf_bytes, template_index)

    def draw(c: canvas.Canvas) -> None:
        for x0, top, x1, bottom in layout.trailer_whiteout_regions:
            _draw_whiteout(c, page_h, x0, top, x1, bottom)

        for box in layout.fields_for_page(template_index):
            _draw_field(c, page_h, box, field_values.get(box.key, ""))

        page_number_text = layout.page_number_format.format(page=page_number, total=total_pages)
        _draw_field(c, page_h, layout.page_number_box, page_number_text)

    overlay = _render_overlay(page_w, page_h, draw)
    page.merge_page(overlay.pages[0])
    return page


def generate_po(slug: str, fields: dict, line_items: list[dict]) -> bytes:
    layout = get_layout(slug)
    if layout is None:
        raise LookupError(f"No layout configured yet for distributor '{slug}'")

    path = find_template_path(slug)
    if path is None:
        raise FileNotFoundError(f"No template PDF found for distributor '{slug}'")

    pdf_bytes = path.read_bytes()
    pagination = paginate(layout.table, line_items)

    field_values = dict(fields)
    field_values["subtotal_repeat"] = format_amount(pagination.grand_total, layout.number_style)
    field_values["total"] = format_amount(pagination.grand_total, layout.number_style)

    discount = _to_decimal(fields.get("discount"))
    tax = _to_decimal(fields.get("tax"))
    total_excl_tax = pagination.grand_total - discount
    total_incl = total_excl_tax + tax
    field_values["discount"] = format_amount(discount, layout.number_style)
    field_values["total_excl_tax"] = format_amount(total_excl_tax, layout.number_style)
    field_values["tax"] = format_amount(tax, layout.number_style)
    field_values["total_incl"] = format_amount(total_incl, layout.number_style)

    total_pages = len(pagination.items_pages) + 1

    writer = PdfWriter()
    for page_number, items_page in enumerate(pagination.items_pages, start=1):
        writer.add_page(
            _build_items_page(pdf_bytes, layout, items_page, field_values, page_number, total_pages)
        )
    writer.add_page(_build_trailer_page(pdf_bytes, layout, field_values, total_pages, total_pages))

    output = io.BytesIO()
    writer.write(output)
    pdf_output = output.getvalue()

    po_number = (fields.get("po_number") or "PO").strip().replace("/", "-").replace(" ", "_") or "PO"
    out_dir = Path(config.GENERATED_DIR) / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{po_number}.pdf").write_bytes(pdf_output)

    return pdf_output
