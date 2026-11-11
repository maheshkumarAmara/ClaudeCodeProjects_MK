import inspect
import json
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import config
import distributors
import history
import salesforce_client
from sandbox_email import sandbox_fields
from pdf_engine import compare, convert, detect, extractor, generator
from pdf_engine.common import untouched_order, without_pulled_discount
from pdf_engine.sandbox_pdf import sandbox_pdf_emails
from pdf_engine.strip_hidden import strip_hidden_text

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# Fail at startup, not on the first request, if the distributor registry points at
# a parser/generator/layout that doesn't exist.
distributors.validate()

app = FastAPI(title="PO Processing Engine")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/compare")
async def compare_page(request: Request):
    return templates.TemplateResponse(request, "compare.html", {})


# The Streamlit app's Home page asks any open engine tab to close itself. The tab polls
# GET /api/close-request and calls window.close() once the time below is later than the
# server time it saw when it loaded. Plain in-memory state; nothing is stored.
_close_requested_at = 0.0


@app.post("/api/close-request")
async def request_tab_close():
    global _close_requested_at
    _close_requested_at = time.time()
    return {"ok": True}


@app.get("/api/close-request")
async def get_close_request():
    return {"now": time.time(), "closeRequestedAt": _close_requested_at}


@app.post("/api/compare/detect")
async def detect_distributor(
    pdf: UploadFile | None = File(None),
    json_file: UploadFile | None = File(None),
):
    """Which distributor an uploaded PDF and/or JSON belongs to (either file may be sent alone)."""
    pdf_bytes = await pdf.read() if pdf is not None else b""
    json_bytes = await json_file.read() if json_file is not None else b""
    if len(pdf_bytes) > MAX_UPLOAD_BYTES or len(json_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 20 MB.")
    json_text = json_bytes.decode("utf-8-sig", errors="replace") if json_bytes else None
    with tempfile.TemporaryDirectory() as tmp:
        path = None
        if pdf_bytes.startswith(b"%PDF"):
            path = Path(tmp) / "upload.pdf"
            path.write_bytes(pdf_bytes)
        result = detect.detect(path, json_text)
    result["name"] = config.DISTRIBUTORS.get(result["slug"]) if result["slug"] else None
    return result


@app.post("/api/compare")
async def compare_pdf_json(
    pdf: UploadFile = File(...),
    json_file: UploadFile = File(...),
    slug: str = Form(""),
    tolerance: str = Form("0.01"),
):
    pdf_bytes = await pdf.read()
    json_bytes = await json_file.read()
    if not pdf_bytes or not json_bytes:
        raise HTTPException(status_code=400, detail="Both a PDF and a JSON file are required.")
    if len(pdf_bytes) > MAX_UPLOAD_BYTES or len(json_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 20 MB.")
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="The first file is not a PDF.")
    try:
        json_text = json_bytes.decode("utf-8-sig")
        json.loads(json_text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"The JSON file is not valid JSON: {exc}") from exc

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.pdf"
        path.write_bytes(pdf_bytes)
        found = detect.detect(path, json_text)
        if not slug:
            slug = found["slug"] or ""
            if not slug:
                raise HTTPException(
                    status_code=422,
                    detail="Could not tell which distributor this is from the files. Choose the distributor and try again.",
                )
        if found["conflict"]:
            # The JSON and the PDF name different distributors, so parsing the PDF with
            # either one would compare the wrong layout or an unrelated order.
            raise HTTPException(
                status_code=422,
                detail=(
                    f"The JSON is for {config.DISTRIBUTORS.get(found['json'], found['json'])} but the PDF looks like "
                    f"{config.DISTRIBUTORS.get(found['pdf'], found['pdf'])}. Use matching files."
                ),
            )
        if distributors.get(slug) is None:
            raise HTTPException(status_code=400, detail=f"Unknown distributor '{slug}'.")
        try:
            parsed = extractor.parse_pdf(slug, path, visible_only=True)
        except LookupError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except Exception as exc:  # a parser failing on an unexpected layout
            raise HTTPException(
                status_code=422,
                detail=f"Could not read this PDF as a {config.DISTRIBUTORS.get(slug, slug)} purchase order: {exc}",
            ) from exc
    if not parsed.get("line_items"):
        raise HTTPException(
            status_code=422,
            detail="No line items were found in the PDF. It may be a scanned image or a different distributor's layout.",
        )
    result = compare.compare(parsed, json_text, tolerance)
    result["distributor"] = {"slug": slug, "name": config.DISTRIBUTORS.get(slug, slug)}
    return result


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/distributors")
async def list_distributors():
    return config.DISTRIBUTORS


@app.get("/api/distributors/{slug}/template")
async def get_distributor_template(slug: str):
    try:
        template = extractor.parse_template(slug)
        template["fields"] = sandbox_fields(template["fields"])
        # Networld only: a CRSD (customer requested ship date) field, typed as a Date on the
        # page, and a BILL_TO_BLOCK text area that starts as the BILL TO text the CRSD template
        # prints on page 1 (the CRSD PDF's BILL TO block follows whatever is typed there).
        if slug == "Networld Corporation":
            from pdf_engine.generator_networld_crsd import template_bill_to_block

            template["fields"]["crsd"] = ""
            template["fields"]["bill_to_block"] = template_bill_to_block()
        return template
    except LookupError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class GenerateRequest(BaseModel):
    fields: dict[str, str]
    line_items: list[dict]
    # Order of the Line items table's columns as the user arranged it (keys: sno, part_number,
    # description, qty, unit_cost, pct_disc, terms, total). Generators that can lay their PDF
    # table out in that order take it as a `column_order` argument; the rest ignore it.
    column_order: list[str] | None = None


def _accepts_column_order(fn) -> bool:
    try:
        return "column_order" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


# Distributors whose template needs strip_hidden_text's per-operator mode.
_STRIP_PER_SHOW = {"NextGen Distribution Pty Ltd", "NOX Co.,LTD.", "Exclusive Networks (Norway)"}
# Distributors that only need per-operator stripping when the user has reordered the columns:
# the generator then covers the template's own column headings with a white box and redraws them,
# and the old headings (part of a larger text block) are only found by judging each operator.
# Left out of _STRIP_PER_SHOW so the default-order PDF is stripped exactly as before.
_STRIP_PER_SHOW_REORDERED = {"Carahsoft Technology Corp"}
# Distributors whose generator hides template text behind a clipping rectangle.
_STRIP_CLIPPED = {"Computer Gross spa", "Exclusive Networks (Norway)", "Networld Corporation"}
# Pixels a removal may change in strip_hidden_text's render check. Computer Gross paints its own
# cell backgrounds, so removing the old value under one shifts a pixel or two at a cell edge. Those
# few pixels add up across the page's ~45 removals (about 8 in all), and the check that all removals
# together still look the same then threw away the last one, the old closing sentence under the
# CONTINGENCY_NOTE cover, so 12 leaves room for them.
_STRIP_TOLERANCE = {"Computer Gross spa": 12}
# Extra background fills (besides white) a generator paints over old text. Networld's PO number
# sits in a pale green band, which it covers with that green before drawing the new number.
# Arrow (Netherlands) covers its info-page values with INFO_GREY and its first-page header values with
# PANEL_GREY (generator_arrow_netherlands.py); keep these two greys in step with those constants.
# ADN covers some values with a grey (0.827) and NOX covers its footer values with a grey (0.859);
# text left under those boxes is removed the same way.
_STRIP_COVER_COLORS = {
    # The second fill is the teal header band Networld repaints when its columns are reordered.
    "Networld Corporation": ((0.886, 0.937, 0.855), (0.0, 0.698, 0.663)),
    "Arrow (Netherlands)": ((0.961, 0.961, 0.961), (0.827, 0.827, 0.827)),
    "ADN Distribution GmbH": ((0.827, 0.827, 0.827),),
    "NOX Co.,LTD.": ((0.859, 0.859, 0.859),),
}
# Distributors whose generator draws the template as a Form XObject (pypdf's merge_page wraps a
# clipped template page that way), so its hidden text sits inside the form, not the page stream.
_STRIP_FORMS = {"Innocom Ltd"}
# Distributors whose generator only PRINTS pct_disc (never takes it off the amount), so a pulled
# Salesforce discount reaches it unchanged: Arrow's Discount % column and its derived RRP.
_SHOWS_PULLED_DISCOUNT = {"Arrow (Netherlands)"}


def _build_po_pdf(slug: str, body: GenerateRequest) -> bytes:
    """The finished PO PDF for `body`: generated, sandboxed and stripped of hidden text.
    Shared by the PDF download and the Convert & Download formats, so they all start from
    exactly what Generate & download PDF delivers."""
    custom = distributors.get_generator(slug)
    fields = sandbox_fields(body.fields)
    # Networld only: a filled CRSD date selects the CRSD layout ("4700738674 .pdf"); with no
    # CRSD the ordinary layout ("4700670275 Details .pdf") is used as before.
    crsd_layout = slug == "Networld Corporation" and bool(str(body.fields.get("crsd") or "").strip())
    if crsd_layout:
        from pdf_engine.generator_networld_crsd import generate_networld_crsd_po

        custom = generate_networld_crsd_po
    # A pulled row's % disc. is Salesforce's own SBQQ__Discount__c, which its unit cost is already
    # net of; the generators that take pct_disc off the amount must not take it off again. Arrow
    # only prints the figure (Discount % and RRP), so it gets the rows as they are.
    line_items = body.line_items if slug in _SHOWS_PULLED_DISCOUNT else without_pulled_discount(body.line_items)
    try:
        if custom is not None:
            if _accepts_column_order(custom):
                pdf_bytes = custom(fields, line_items, column_order=body.column_order)
            else:
                pdf_bytes = custom(fields, line_items)
        else:
            pdf_bytes = generator.generate_po(slug, fields, line_items)
    except LookupError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Template-printed addresses aren't form fields, so sandbox_fields can't reach them.
    pdf_bytes = sandbox_pdf_emails(pdf_bytes)

    # The generators cover the template's values with white boxes and draw new text over
    # them, leaving the old text in the file. Remove it, so the PDF holds only what shows.
    # NextGen's template keeps a whole page of text in one block, so its covered rows are
    # only found by judging each text operator on its own (other distributors are unchanged).
    # Computer Gross cuts bands out of the whole template page with a clipping rectangle, so
    # the rest of that page's text is hidden by the clip and needs the clip-aware pass.
    # The CRSD layout's first page is one big text block (the Japanese PO), so, like NextGen's,
    # its covered CRSD line is only found by judging each text operator on its own.
    return strip_hidden_text(
        pdf_bytes,
        per_show=slug in _STRIP_PER_SHOW or crsd_layout or (slug in _STRIP_PER_SHOW_REORDERED and untouched_order(body.column_order) is not None),
        clipped=slug in _STRIP_CLIPPED,
        tolerance=_STRIP_TOLERANCE.get(slug, 0),
        cover_colors=_STRIP_COVER_COLORS.get(slug, ()),
        forms=slug in _STRIP_FORMS,
    )


def _po_basename(slug: str, body: GenerateRequest) -> str:
    return (body.fields.get("po_number") or slug).strip().replace("/", "-") or slug


@app.post("/api/distributors/{slug}/generate")
async def generate_distributor_po(slug: str, body: GenerateRequest, preview: bool = False):
    pdf_bytes = _build_po_pdf(slug, body)
    filename = f"{_po_basename(slug, body)}.pdf"
    # Keep the archived copy (data/generated/<slug>/) identical to what was delivered.
    archive = config.GENERATED_DIR / slug / filename
    if archive.parent.is_dir():
        archive.write_bytes(pdf_bytes)
    # "Preview PDF" calls this same endpoint with ?preview=true; only a real download is history.
    if not preview:
        history.add(slug, "PDF", sandbox_fields(body.fields), body.line_items)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/convert/formats")
async def list_convert_formats():
    return {"formats": [{"key": key, "label": label} for key, (label, _) in convert.FORMATS.items()]}


@app.post("/api/distributors/{slug}/convert/{fmt}")
async def convert_distributor_po(slug: str, fmt: str, body: GenerateRequest):
    if fmt not in convert.FORMATS:
        raise HTTPException(status_code=400, detail=f"Unknown format '{fmt}'. Choose one of: {', '.join(convert.FORMATS)}.")
    # Image and text formats are made from the finished PDF, so build it first. Data formats
    # read the form values, but go through the same build so a layout that can't be
    # generated (or a bad value) is reported the same way as for the PDF download.
    pdf_bytes = _build_po_pdf(slug, body)
    basename = _po_basename(slug, body)
    try:
        content, media_type, ext = convert.convert(
            fmt,
            pdf_bytes=pdf_bytes,
            fields=sandbox_fields(body.fields),
            line_items=body.line_items,
            slug=slug,
            basename=basename,
        )
    except Exception as exc:  # a renderer failing on an unusual PDF
        raise HTTPException(status_code=500, detail=f"Could not convert to {fmt.upper()}: {exc}") from exc
    history.add(slug, fmt.upper(), sandbox_fields(body.fields), body.line_items)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{basename}.{ext}"'},
    )


@app.get("/api/history")
async def list_history():
    return {"entries": history.summaries()}


@app.get("/api/history/{entry_id}")
async def get_history_entry(entry_id: str):
    entry = history.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="That history entry no longer exists.")
    return entry


@app.delete("/api/history/{entry_id}")
async def delete_history_entry(entry_id: str):
    if not history.delete(entry_id):
        raise HTTPException(status_code=404, detail="That history entry no longer exists.")
    return {"deleted": entry_id}


@app.delete("/api/history")
async def clear_history():
    history.clear()
    return {"cleared": True}


def _resolve_sf_org(org: str) -> str:
    if org not in config.SALESFORCE_ORGS:
        valid = ", ".join(config.SALESFORCE_ORGS)
        raise HTTPException(status_code=400, detail=f"Unknown Salesforce org '{org}'. Valid options: {valid}.")
    return org


@app.get("/api/salesforce/orgs")
async def list_salesforce_orgs():
    return {"orgs": config.SALESFORCE_ORGS, "default": config.SALESFORCE_ORG_ALIAS}


@app.get("/api/salesforce/quotes/search")
async def search_salesforce_quotes(q: str = "", org: str = config.SALESFORCE_ORG_ALIAS):
    org = _resolve_sf_org(org)
    if len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Search term must be at least 2 characters.")
    try:
        return salesforce_client.search_quotes(q, org=org)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/salesforce/quotes/{quote_id}/data")
async def get_salesforce_quote_data(quote_id: str, org: str = config.SALESFORCE_ORG_ALIAS, slug: str | None = None):
    org = _resolve_sf_org(org)
    try:
        data = salesforce_client.get_quote_data(quote_id, org=org, slug=slug)
        data["fields"] = sandbox_fields(data["fields"])
        return data
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=config.PORT, reload=True)
