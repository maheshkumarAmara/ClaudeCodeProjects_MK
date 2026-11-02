"""Converts a finished PO into the formats offered by "Convert & Download".

Two kinds of output:
  - Image and text formats (png, jpg, txt) are made from the generated PDF itself, so they
    show exactly what "Generate & download PDF" delivers.
  - Data formats (html, xml, json, csv) are made from the form's fields and line items.

Each converter returns (bytes, media_type, extension).
"""

import base64
import csv
import io
import json
import re
import zipfile
from html import escape
from xml.etree import ElementTree as ET

import pdfplumber
import pypdfium2 as pdfium

IMAGE_DPI = 150
LINE_ITEM_COLUMNS = ("part_number", "description", "qty", "unit_cost", "pct_disc", "terms")

# The distributor slug often has spaces and punctuation ("NOX Co.,LTD."), which are not
# valid in an XML name, so field keys are used as tag names only when they are safe.
_XML_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


def _render_pages(pdf_bytes: bytes, image_format: str) -> list[bytes]:
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        pages = []
        for index in range(len(pdf)):
            image = pdf[index].render(scale=IMAGE_DPI / 72).to_pil().convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format=image_format, **({"quality": 92} if image_format == "JPEG" else {}))
            pages.append(buffer.getvalue())
        return pages
    finally:
        pdf.close()


def _image(pdf_bytes: bytes, basename: str, image_format: str, ext: str, media_type: str):
    """One image for a single-page PO, a ZIP of page images for a longer one."""
    pages = _render_pages(pdf_bytes, image_format)
    if len(pages) == 1:
        return pages[0], media_type, ext
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for number, data in enumerate(pages, start=1):
            archive.writestr(f"{basename}_page{number}.{ext}", data)
    return buffer.getvalue(), "application/zip", "zip"


def to_png(pdf_bytes: bytes, basename: str, **_):
    return _image(pdf_bytes, basename, "PNG", "png", "image/png")


def to_jpg(pdf_bytes: bytes, basename: str, **_):
    return _image(pdf_bytes, basename, "JPEG", "jpg", "image/jpeg")


def to_txt(pdf_bytes: bytes, **_):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n\n".join((page.extract_text() or "").strip() for page in pdf.pages)
    return text.encode("utf-8"), "text/plain; charset=utf-8", "txt"


def to_json(fields: dict, line_items: list[dict], slug: str, **_):
    document = {"distributor": slug, "fields": fields, "line_items": line_items}
    return json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8"), "application/json", "json"


def to_csv(line_items: list[dict], **_):
    columns = list(LINE_ITEM_COLUMNS)
    for item in line_items:
        columns += [key for key in item if key not in columns]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(line_items)
    # A BOM lets Excel read the file as UTF-8.
    return ("﻿" + buffer.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", "csv"


def to_xml(fields: dict, line_items: list[dict], slug: str, **_):
    root = ET.Element("purchase_order", distributor=slug)
    fields_el = ET.SubElement(root, "fields")
    for key, value in fields.items():
        if _XML_NAME.match(key):
            ET.SubElement(fields_el, key).text = str(value)
        else:
            ET.SubElement(fields_el, "field", name=key).text = str(value)
    items_el = ET.SubElement(root, "line_items")
    for number, item in enumerate(line_items, start=1):
        item_el = ET.SubElement(items_el, "line_item", number=str(number))
        for key, value in item.items():
            if _XML_NAME.match(key):
                ET.SubElement(item_el, key).text = "" if value is None else str(value)
    ET.indent(root)
    body = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'.encode("utf-8"), "application/xml", "xml"


_HTML_STYLE = (
    "body{margin:0;padding:24px 0;background:#e6e6e6;font-family:Arial,Helvetica,sans-serif}"
    ".page{position:relative;margin:0 auto 24px;background:#fff no-repeat;background-size:100% 100%;"
    "box-shadow:0 1px 6px rgba(0,0,0,.3);overflow:hidden}"
    # The PDF's text sits over the picture of the page: invisible, but selectable and searchable.
    ".page span{position:absolute;white-space:pre;color:transparent;line-height:1}"
    ".page span::selection{background:rgba(0,90,255,.3)}"
)


def to_html(pdf_bytes: bytes, fields: dict, slug: str, **_):
    """The PO as it looks in the PDF: one block per page, each a picture of the page with the
    PDF's own text laid over it, so the HTML matches the PDF and the text can still be
    selected, copied and searched."""
    images = _render_pages(pdf_bytes, "PNG")
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page, image in zip(pdf.pages, images):
            width, height = float(page.width), float(page.height)
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False, extra_attrs=["size"])
            spans = "".join(
                f'<span style="left:{w["x0"]:.2f}pt;top:{w["top"]:.2f}pt;font-size:{w["size"]:.2f}pt">'
                f'{escape(w["text"])}</span>'
                for w in words
            )
            picture = base64.b64encode(image).decode("ascii")
            pages.append(
                f'<div class="page" style="width:{width:.2f}pt;height:{height:.2f}pt;'
                f'background-image:url(data:image/png;base64,{picture})">{spans}</div>'
            )
    title = escape(str(fields.get("po_number") or slug))
    document = (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title><style>{_HTML_STYLE}</style></head><body>{''.join(pages)}</body></html>\n"
    )
    return document.encode("utf-8"), "text/html; charset=utf-8", "html"


# format key -> (label, converter). The page builds its menu from /api/convert/formats.
FORMATS = {
    "html": ("HTML", to_html),
    "xml": ("XML", to_xml),
    "json": ("JSON", to_json),
    "csv": ("CSV (line items)", to_csv),
    "png": ("PNG image", to_png),
    "jpg": ("JPG image", to_jpg),
    "txt": ("Text (TXT)", to_txt),
}


def convert(fmt: str, *, pdf_bytes: bytes, fields: dict, line_items: list[dict], slug: str, basename: str):
    if fmt not in FORMATS:
        raise LookupError(f"Unknown format '{fmt}'. Choose one of: {', '.join(FORMATS)}.")
    return FORMATS[fmt][1](pdf_bytes=pdf_bytes, fields=fields, line_items=line_items, slug=slug, basename=basename)
