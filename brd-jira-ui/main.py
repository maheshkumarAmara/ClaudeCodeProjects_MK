import asyncio
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

# Always resolve paths relative to this file so the app works from any directory
BASE_DIR = Path(__file__).parent
os.chdir(BASE_DIR)
sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import analyzer
import brd_differ
import brd_parser
import config
import jira_fetcher

config.validate()

app = FastAPI(title="BRD-Jira Validator", version="1.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# In-memory job store  {job_id: {status, result, error}}
_jobs: dict = {}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
def health():
    return {"status": "ok", "jira": config.JIRA_URL, "claude": bool(config.ANTHROPIC_API_KEY)}


@app.post("/api/validate")
async def validate(
    brd_url: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    if not brd_url and not file:
        raise HTTPException(400, "Provide either brd_url or a file upload")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "progress": "Starting...", "result": None, "error": None}

    asyncio.create_task(_run_job(job_id, brd_url, file))
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


async def _run_job(job_id: str, brd_url: Optional[str], file: Optional[UploadFile]):
    def update(msg: str):
        _jobs[job_id]["progress"] = msg

    try:
        # Step 1: Parse BRD
        update("Downloading and parsing BRD...")
        if file:
            file_bytes = await file.read()
            requirements = await asyncio.to_thread(brd_parser.parse_from_bytes, file_bytes)
        else:
            requirements = await asyncio.to_thread(brd_parser.parse_from_url, brd_url)

        if not requirements:
            _jobs[job_id].update({"status": "error", "error": "No requirements found in BRD. Check the document format."})
            return

        update(f"Fetching Jira tickets for {len(requirements)} requirements...")

        # Step 2: Collect unique Jira IDs
        all_ids = list(dict.fromkeys(jid for r in requirements for jid in r.get("jira_ids", [])))

        # Step 3: Fetch Jira data
        ticket_cache, parent_cache = await asyncio.to_thread(jira_fetcher.fetch_tickets, all_ids)

        update(f"Analyzing {len(requirements)} requirements...")

        # Step 4: Analyze
        analysis = await asyncio.to_thread(analyzer.analyze, requirements, ticket_cache, parent_cache)
        analysis_by_idx = {r["req_index"]: r for r in analysis}

        # Step 5: Build response
        rows = []
        for i, req in enumerate(requirements):
            result = analysis_by_idx.get(i, {"status": "NO_JIRA", "issues": []})
            fields = req.get("fields", {})
            jira_ids = req.get("jira_ids", [])

            # Build Jira ticket details
            tickets_detail = []
            for jid in jira_ids:
                t = ticket_cache.get(jid)
                if t:
                    pk = t.get("parent_key")
                    parent = None
                    if pk:
                        parent = parent_cache.get(pk) or ticket_cache.get(pk)
                    tickets_detail.append({
                        "key": jid,
                        "url": t.get("url", f"{config.JIRA_URL}/browse/{jid}"),
                        "summary": t.get("summary", ""),
                        "description": t.get("description", ""),
                        "acceptance_criteria": t.get("acceptance_criteria", ""),
                        "issue_type": t.get("issue_type", ""),
                        "parent": {
                            "key": pk,
                            "url": f"{config.JIRA_URL}/browse/{pk}" if pk else None,
                            "summary": parent.get("summary", "") if parent else "",
                            "description": parent.get("description", "") if parent else "",
                            "acceptance_criteria": parent.get("acceptance_criteria", "") if parent else "",
                        } if pk else None,
                    })
                else:
                    tickets_detail.append({
                        "key": jid,
                        "url": f"{config.JIRA_URL}/browse/{jid}",
                        "summary": "NOT FOUND",
                        "description": "",
                        "acceptance_criteria": "",
                        "issue_type": "",
                        "parent": None,
                    })

            rows.append({
                "index": i,
                "section": req.get("section", "General"),
                "jira_ids": jira_ids,
                "status_brd": req.get("status_brd", ""),
                "priority_brd": req.get("priority_brd", ""),
                "fields": {
                    "what": fields.get("what", ""),
                    "why": fields.get("why", ""),
                    "who": fields.get("who", ""),
                    "as_is": fields.get("as_is", ""),
                    "to_be": fields.get("to_be", ""),
                    "functional": fields.get("functional", ""),
                    "conditions": fields.get("conditions", ""),
                    "exceptions": fields.get("exceptions", ""),
                    "assumptions": fields.get("assumptions", ""),
                    "dependencies": fields.get("dependencies", ""),
                    "acceptance": fields.get("acceptance", ""),
                },
                "tickets": tickets_detail,
                "status": result.get("status", "NO_JIRA"),
                "issues": result.get("issues", []),
                "testability": result.get("testability", {}),
                "ac_gap": result.get("ac_gap", {}),
            })

        # Summary counts
        counts = {"GREEN": 0, "YELLOW": 0, "RED": 0, "NO_JIRA": 0}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1

        sections = sorted(set(r["section"] for r in rows))

        _jobs[job_id].update({
            "status": "done",
            "progress": "Complete",
            "result": {
                "rows": rows,
                "summary": counts,
                "sections": sections,
                "total": len(rows),
                "generated_at": datetime.now().isoformat(),
                "analysis_engine": "Claude API" if config.ANTHROPIC_API_KEY else "Keyword heuristics",
            },
        })

    except Exception as e:
        import traceback
        _jobs[job_id].update({"status": "error", "error": str(e), "traceback": traceback.format_exc()})


@app.post("/api/diff")
async def api_diff(
    v1_file: Optional[UploadFile] = File(None),
    v2_file: Optional[UploadFile] = File(None),
    v1_url: Optional[str] = Form(None),
    v2_url: Optional[str] = Form(None),
):
    if not (v1_file or v1_url) or not (v2_file or v2_url):
        raise HTTPException(400, "Provide both v1 and v2 BRD documents")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "progress": "Starting diff...", "result": None, "error": None}

    v1_bytes = await v1_file.read() if v1_file else None
    v2_bytes = await v2_file.read() if v2_file else None

    asyncio.create_task(_run_diff_job(job_id, v1_url, v1_bytes, v2_url, v2_bytes))
    return {"job_id": job_id}


async def _run_diff_job(
    job_id: str,
    v1_url: Optional[str], v1_bytes: Optional[bytes],
    v2_url: Optional[str], v2_bytes: Optional[bytes],
):
    def update(msg: str):
        _jobs[job_id]["progress"] = msg

    try:
        update("Parsing BRD v1 (original)...")
        if v1_bytes:
            reqs_v1 = await asyncio.to_thread(brd_parser.parse_from_bytes, v1_bytes)
        else:
            reqs_v1 = await asyncio.to_thread(brd_parser.parse_from_url, v1_url)

        if not reqs_v1:
            _jobs[job_id].update({"status": "error", "error": "No requirements found in BRD v1. Check the document format."})
            return

        update(f"Parsing BRD v2 (new)... ({len(reqs_v1)} requirements in v1)")
        if v2_bytes:
            reqs_v2 = await asyncio.to_thread(brd_parser.parse_from_bytes, v2_bytes)
        else:
            reqs_v2 = await asyncio.to_thread(brd_parser.parse_from_url, v2_url)

        if not reqs_v2:
            _jobs[job_id].update({"status": "error", "error": "No requirements found in BRD v2. Check the document format."})
            return

        update(f"Comparing {len(reqs_v1)} vs {len(reqs_v2)} requirements...")
        result = await asyncio.to_thread(brd_differ.diff_brds, reqs_v1, reqs_v2)

        _jobs[job_id].update({"status": "done", "progress": "Complete", "result": result})

    except Exception as e:
        import traceback
        _jobs[job_id].update({"status": "error", "error": str(e), "traceback": traceback.format_exc()})


@app.post("/api/generate-tests")
async def api_generate_tests(request: Request):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        body = await request.json()
        result = await asyncio.to_thread(
            analyzer.generate_test_scenarios,
            body.get("requirement", ""),
            body.get("jira_ac", ""),
            body.get("section", ""),
        )
        if result is None:
            return JSONResponse(status_code=503, content={"error": "Claude API key not configured. Add ANTHROPIC_API_KEY to your .env file."})
        return {"scenarios": result}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/compare/{jira_id}")
async def api_compare(jira_id: str):
    jid = jira_id.upper()
    ticket_cache, parent_cache = await asyncio.to_thread(jira_fetcher.fetch_tickets, [jid])
    ticket = ticket_cache.get(jid)
    if not ticket:
        return JSONResponse(status_code=404, content={"error": f"{jid} not found in Jira"})
    parent = None
    pk = ticket.get("parent_key")
    if pk:
        parent = parent_cache.get(pk)
    return {"jira_id": jid, "ticket": ticket, "parent": parent}


if __name__ == "__main__":
    import threading
    import webbrowser
    import uvicorn

    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open("http://localhost:8001")

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
