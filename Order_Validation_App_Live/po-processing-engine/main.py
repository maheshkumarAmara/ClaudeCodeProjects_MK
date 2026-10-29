import json
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import config
import distributors
import salesforce_client
from sandbox_email import sandbox_fields
from pdf_engine import compare, detect, extractor, generator
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
        if not slug:
            slug = detect.detect(path, json_text)["slug"] or ""
            if not slug:
                raise HTTPException(
                    status_code=422,
                    detail="Could not tell which distributor this is from the files. Choose the distributor and try again.",
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


@app.post("/api/distributors/{slug}/generate")
async def generate_distributor_po(slug: str, body: GenerateRequest):
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
    pdf_bytes = strip_hidden_text(pdf_bytes)

    filename = f"{(body.fields.get('po_number') or slug).strip().replace('/', '-') or slug}.pdf"
    # Keep the archived copy (data/generated/<slug>/) identical to what was delivered.
    archive = config.GENERATED_DIR / slug / filename
    if archive.parent.is_dir():
        archive.write_bytes(pdf_bytes)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
