import json
import os
import webbrowser
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from config import JIRA_PROJECT_KEY, JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN
import jira_client

_SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "data", "settings.json")
_WRITE_ROUTES = {"/api/create-subtasks", "/api/create-epic-signoff-tasks",
                 "/api/assign-qa", "/api/add-comment", "/api/settings",
                 "/api/sprint-snapshot", "/api/cache"}

startup_error = None
_ws_clients: set = set()

# Flag scoped to the reloader process so hot-reloads don't re-open the browser.
# Each fresh `uvicorn` invocation gets a new reloader PID → new flag path → browser opens once.
_BROWSER_LOCK = f"/tmp/.jira_dashboard_{os.getppid()}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global startup_error
    missing = []
    if not JIRA_URL or "yourcompany" in JIRA_URL:
        missing.append("JIRA_URL")
    if not JIRA_EMAIL or "your-email" in JIRA_EMAIL:
        missing.append("JIRA_EMAIL")
    if not JIRA_API_TOKEN or "your-api-token" in JIRA_API_TOKEN:
        missing.append("JIRA_API_TOKEN")

    if missing:
        startup_error = (
            f"Please update your .env file with real values for: {', '.join(missing)}. "
            f"The server is running but cannot connect to JIRA until credentials are set."
        )
    else:
        try:
            from jira_client import test_connection
            user = test_connection()
            print(f"Connected to JIRA as: {user.get('displayName', 'Unknown')}")
        except Exception as e:
            startup_error = f"Failed to connect to JIRA: {e}"

    if not os.path.exists(_BROWSER_LOCK):
        open(_BROWSER_LOCK, "w").close()
        asyncio.get_event_loop().call_later(0.8, lambda: webbrowser.open("http://127.0.0.1:8000"))

    yield

    for ws in list(_ws_clients):
        try:
            await ws.send_text("shutdown")
            await ws.close()
        except Exception:
            pass


app = FastAPI(title="JIRA Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.url.path in _WRITE_ROUTES:
        api_key_setting = ""
        try:
            if os.path.exists(_SETTINGS_PATH):
                with open(_SETTINGS_PATH) as f:
                    api_key_setting = json.load(f).get("api_key", "")
        except Exception:
            pass
        if api_key_setting:
            provided = request.headers.get("X-API-Key", "")
            if provided != api_key_setting:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.websocket("/ws/keepalive")
async def ws_keepalive(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        while True:
            await asyncio.sleep(10)
            await websocket.send_text("ping")
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _ws_clients.discard(websocket)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"default_project": JIRA_PROJECT_KEY or ""},
    )


@app.get("/api/projects")
async def api_projects():
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        from jira_client import get_projects
        return get_projects()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/sprints")
async def api_sprints(project: str = Query(...)):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        from jira_client import get_sprints
        return get_sprints(project_key=project)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})



@app.post("/api/create-subtasks")
async def api_create_subtasks(request: Request):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        body = await request.json()
        parent_key = body.get("parentKey", "").strip()
        if not parent_key:
            return JSONResponse(status_code=400, content={"error": "parentKey is required"})
        project_key = body.get("projectKey", "").strip()
        if not project_key:
            return JSONResponse(status_code=400, content={"error": "projectKey is required"})
        subtasks = body.get("subtasks")
        if not subtasks or not isinstance(subtasks, list):
            return JSONResponse(status_code=400, content={"error": "subtasks (list) is required"})
        from jira_client import create_subtasks
        created = create_subtasks(parent_key, project_key, subtasks)
        return {"created": created}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/create-epic-signoff-tasks")
async def api_create_epic_signoff_tasks(request: Request):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        body = await request.json()
        epic_key = body.get("epicKey", "").strip()
        if not epic_key:
            return JSONResponse(status_code=400, content={"error": "epicKey is required"})
        project_key = body.get("projectKey", "").strip()
        if not project_key:
            return JSONResponse(status_code=400, content={"error": "projectKey is required"})
        tasks = body.get("tasks")
        if not tasks or not isinstance(tasks, list):
            return JSONResponse(status_code=400, content={"error": "tasks (list) is required"})
        from jira_client import create_epic_signoff_tasks
        created = create_epic_signoff_tasks(epic_key, project_key, tasks)
        return {"created": created}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/assign-qa")
async def api_assign_qa(request: Request):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        body = await request.json()
        issue_key = body["issueKey"]
        account_id = body.get("accountId")
        display_name = body.get("displayName")
        from jira_client import assign_qa_contact, assign_qa_contact_by_name
        if account_id:
            assign_qa_contact(issue_key, account_id)
        elif display_name:
            assign_qa_contact_by_name(issue_key, display_name)
        else:
            return JSONResponse(status_code=400, content={"error": "accountId or displayName required"})
        return {"success": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/qa-tracking")
async def api_qa_tracking(
    project: str = Query(...),
    sprintId: str = Query(None),
    created_from: str = Query(None),
    created_to: str = Query(None),
):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        from jira_client import get_qa_tracking
        return get_qa_tracking(project_key=project, sprint_id=sprintId,
                               created_from=created_from, created_to=created_to)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/add-comment")
async def api_add_comment(request: Request):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        body = await request.json()
        issue_key = body["issueKey"]
        qa_name = body["qaName"]
        account_id = body.get("accountId")
        message_suffix = body.get("messageSuffix", ", can you please update the QA Progress?")
        message_prefix = body.get("messagePrefix", "")
        alert_type = body.get("alertType", "qa_update")
        force = body.get("force", False)
        from jira_client import add_comment
        result = add_comment(issue_key, qa_name, account_id, message_suffix, message_prefix,
                             alert_type=alert_type, force=force)
        if isinstance(result, dict) and result.get("skipped"):
            return {"success": False, "skipped": True, "reason": result.get("reason", "dedup")}
        return {"success": True, "commentId": result.get("id") if isinstance(result, dict) else None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})



@app.get("/api/qa-contacts")
async def api_qa_contacts(projects: str = Query(...)):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        from jira_client import get_qa_contacts
        project_keys = [p.strip() for p in projects.split(",") if p.strip()]
        return get_qa_contacts(project_keys)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/issues-by-qa-contact")
async def api_issues_by_qa_contact(name: str = Query(...)):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        from jira_client import get_issues_by_qa_contact
        return get_issues_by_qa_contact(qa_name=name)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/api/cache")
async def api_clear_cache():
    try:
        from jira_client import clear_cache
        clear_cache()
        return {"success": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/issues")
async def api_issues(
    project: str = Query(...),
    sprintId: str = Query(None),
    type: str = Query(None),
    created_from: str = Query(None),
    created_to: str = Query(None),
):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        from jira_client import get_issues
        return get_issues(project_key=project, sprint_id=sprintId, issue_type=type,
                          created_from=created_from, created_to=created_to)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def api_get_settings():
    try:
        if os.path.exists(_SETTINGS_PATH):
            with open(_SETTINGS_PATH) as f:
                data = json.load(f)
        else:
            data = {}
        # Never expose the raw api_key to the client — just indicate if set
        safe = {k: v for k, v in data.items() if k != "api_key"}
        safe["api_key_set"] = bool(data.get("api_key"))
        return safe
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


ALLOWED_SETTINGS_KEYS = {
    "sla_hours", "cache_ttl", "alert_cooldown_hours",
    "tc_sheet_project", "tc_sheet_id", "api_key",
    "slack_bot_token",
}

@app.post("/api/settings")
async def api_post_settings(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse(status_code=400, content={"error": "Expected JSON object"})
        filtered = {k: v for k, v in body.items() if k in ALLOWED_SETTINGS_KEYS}
        existing = {}
        if os.path.exists(_SETTINGS_PATH):
            with open(_SETTINGS_PATH) as f:
                existing = json.load(f)
        existing.update(filtered)
        os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
        with open(_SETTINGS_PATH, "w") as f:
            json.dump(existing, f, indent=2)
        return {"success": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Slack Ping ────────────────────────────────────────────────────────────────

@app.post("/api/slack-ping")
async def api_slack_ping(request: Request):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        body = await request.json()
        account_id = body.get("accountId", "")
        qa_name    = body.get("qaName", "")
        issue_key  = body.get("issueKey", "")
        summary    = body.get("summary", "")
        jira_url   = body.get("url", "")
        status     = body.get("status", "")
        days       = int(body.get("days", 0))

        if not account_id:
            return JSONResponse(status_code=400, content={"error": "accountId is required"})

        from slack_client import send_ping_dm
        result = send_ping_dm(account_id, qa_name, issue_key, summary, jira_url, status, days)
        return {"success": True, **result}
    except ValueError as e:
        return JSONResponse(status_code=422, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/retry-connection")
async def api_retry_connection():
    """Re-attempt the JIRA connection and clear startup_error if successful."""
    global startup_error
    try:
        from jira_client import test_connection
        user = test_connection()
        startup_error = None
        return {"success": True, "user": user.get("displayName", "Unknown")}
    except Exception as e:
        startup_error = f"Failed to connect to JIRA: {e}"
        return JSONResponse(status_code=503, content={"error": startup_error})


@app.get("/api/slack-token-set")
async def api_slack_token_set():
    """Returns whether a Slack bot token is configured (without exposing the token itself)."""
    from jira_client import get_settings_value
    token = get_settings_value("slack_bot_token", "")
    return {"configured": bool(token)}


# ── Workload ──────────────────────────────────────────────────────────────────

@app.get("/api/workload")
async def api_workload(project: str = Query(...), sprintId: str = Query(None)):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        return jira_client.get_workload(project_key=project, sprint_id=sprintId)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Health Score ──────────────────────────────────────────────────────────────

@app.get("/api/health-score")
async def api_health_score(project: str = Query(...), sprintId: str = Query(None)):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        # Use get_issues() — it runs _process_issue() which populates qaUpdateMissing/subtasksMissing
        issues = jira_client.get_issues(project_key=project, sprint_id=sprintId)
        total = len(issues)
        if total == 0:
            return {"score": 100, "total": 0, "alerts": 0, "missing_subtasks": 0}
        alert_count = sum(1 for i in issues if i.get("qaUpdateMissing") or i.get("uatSanityMissing"))
        missing_subtask_count = sum(
            1 for i in issues
            if i.get("subtasksMissing") and (
                i["subtasksMissing"].get("design") or i["subtasksMissing"].get("execution")
            )
        )
        deductions = (alert_count * 5) + (missing_subtask_count * 3)
        score = max(0, 100 - int(deductions * 100 / max(total, 1)))
        return {
            "score": score,
            "total": total,
            "alerts": alert_count,
            "missing_subtasks": missing_subtask_count,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Velocity ──────────────────────────────────────────────────────────────────

@app.get("/api/velocity")
async def api_velocity(project: str = Query(...), sprintId: str = Query(None)):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        return jira_client.get_velocity(project_key=project, sprint_id=sprintId)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Digest ────────────────────────────────────────────────────────────────────

@app.get("/api/digest")
async def api_digest(project: str = Query(...), sprintId: str = Query(None)):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        issues = jira_client.get_qa_tracking(project_key=project, sprint_id=sprintId,
                                             created_from=None, created_to=None)
        lines = [f"QA Digest — {project}" + (f" sprint {sprintId}" if sprintId else ""), ""]
        total = len(issues)
        alerts = [i for i in issues if i.get("qaUpdateMissing") or i.get("commentMissing")]
        lines.append(f"Total issues: {total}")
        lines.append(f"Issues needing attention: {len(alerts)}")
        lines.append("")
        if alerts:
            lines.append("Issues needing QA update:")
            for i in alerts[:20]:
                lines.append(f"  • {i.get('key')} — {i.get('summary', '')[:60]} [{i.get('status','')}]")
        return {"text": "\n".join(lines)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Alert History ─────────────────────────────────────────────────────────────

@app.get("/api/alerts-history")
async def api_alerts_history():
    try:
        with jira_client._history_lock:
            data = jira_client._load_alerts_history()
        return data
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/api/alerts-history/{issue_key}")
async def api_delete_alert_history(issue_key: str):
    try:
        with jira_client._history_lock:
            data = jira_client._load_alerts_history()
            keys_to_remove = [k for k in data if k.startswith(f"{issue_key}:")]
            for k in keys_to_remove:
                del data[k]
            jira_client._save_alerts_history(data)
        return {"success": True, "removed": len(keys_to_remove)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Sprint Snapshots ──────────────────────────────────────────────────────────

@app.post("/api/sprint-snapshot")
async def api_post_sprint_snapshot(request: Request):
    if startup_error:
        return JSONResponse(status_code=503, content={"error": startup_error})
    try:
        body = await request.json()
        project = body.get("project", "")
        sprint_id = body.get("sprintId")
        issues = jira_client.get_qa_tracking(project_key=project, sprint_id=sprint_id,
                                             created_from=None, created_to=None)
        from datetime import datetime, timezone
        snapshot = {
            "project_key": project,
            "sprint_id": sprint_id,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "total": len(issues),
            "statuses": {},
        }
        for i in issues:
            st = i.get("currentStatus", "Unknown")
            snapshot["statuses"][st] = snapshot["statuses"].get(st, 0) + 1
        jira_client._save_sprint_snapshot(snapshot)
        return {"success": True, "snapshot": snapshot}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/sprint-snapshots")
async def api_get_sprint_snapshots(project: str = Query(None)):
    try:
        snapshots = jira_client._load_sprint_snapshots()
        if project:
            snapshots = [s for s in snapshots if s.get("project_key") == project]
        return snapshots
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
