import json
import tempfile
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
        return template
    except LookupError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class GenerateRequest(BaseModel):
    fields: dict[str, str]
    line_items: list[dict]


def _build_po_pdf(slug: str, body: GenerateRequest) -> bytes:
    """The finished PO PDF for `body`: generated, sandboxed and stripped of hidden text.
    Shared by the PDF download and the Convert & Download formats, so they all start from
    exactly what Generate & download PDF delivers."""
    custom = distributors.get_generator(slug)
    fields = sandbox_fields(body.fields)
    try:
        if custom is not None:
            pdf_bytes = custom(fields, body.line_items)
        else:
            pdf_bytes = generator.generate_po(slug, fields, body.line_items)
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
    return strip_hidden_text(pdf_bytes)


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
