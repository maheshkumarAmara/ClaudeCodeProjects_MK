from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import config
import salesforce_client
from sandbox_email import sandbox_fields
from pdf_engine import (
    extractor,
    generator,
    generator_adn,
    generator_arrow_netherlands,
    generator_computer_gross_spa,
    generator_exclusive_networks_norway,
    generator_ingram_micro_canada,
    generator_innocom_ltd,
    generator_networld_corporation,
    generator_nextgen_distribution_pty_ltd,
    generator_nox_co_ltd,
)

# Distributors whose PDF is built by a dedicated generator instead of the
# coordinate-layout one in pdf_engine/generator.py.
CUSTOM_GENERATORS = {
    "ADN Distribution GmbH": generator_adn.generate_adn_po,
    "Arrow (Netherlands)": generator_arrow_netherlands.generate_arrow_netherlands_po,
    "Computer Gross spa": generator_computer_gross_spa.generate_computer_gross_spa_po,
    "Exclusive Networks (Norway)": generator_exclusive_networks_norway.generate_exclusive_networks_norway_po,
    "Ingram Micro Canada": generator_ingram_micro_canada.generate_ingram_micro_canada_po,
    "Innocom Ltd": generator_innocom_ltd.generate_innocom_ltd_po,
    "Networld Corporation": generator_networld_corporation.generate_networld_corporation_po,
    "NOX Co.,LTD.": generator_nox_co_ltd.generate_nox_co_ltd_po,
    "NextGen Distribution Pty Ltd": generator_nextgen_distribution_pty_ltd.generate_nextgen_distribution_pty_ltd_po,
}

app = FastAPI(title="PO Processing Engine")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


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
    custom = CUSTOM_GENERATORS.get(slug)
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

    filename = f"{(body.fields.get('po_number') or slug).strip().replace('/', '-') or slug}.pdf"
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
