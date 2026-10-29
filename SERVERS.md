# Local Servers

Quick reference for every app in this repo that runs a local server. Paths are relative to the repo root (`ClaudeCodeProjects_MK/`).

## Port map

| Port | App | Stack | Started by |
|---|---|---|---|
| 8000 | [Jira Dashboard](#2-jira-dashboard) | FastAPI | `uvicorn main:app --reload` |
| 8001 | [BRD Jira UI](#3-brd-jira-ui) | FastAPI | `python main.py` |
| 8502 | [Order Validation App](#1-order-validation-app) | Streamlit (or the gateway in front of it) | `./launch.sh` |
| 8510 | Order Validation internal Streamlit, behind the gateway | Streamlit | `gateway.js` |
| 3001 | Salesforce bridge for the EDI tool | Node | `launch.sh` / `gateway.js` |
| 8012 | PO Processing Engine, embedded in Order Validation | FastAPI | `pages/PO_Processing_Engine.py` |
| 4570 | [SOQL Builder](#4-soql-builder-standalone) (standalone default) | Node | `node server.mjs` |
| 4580 | SOQL Builder when embedded in Order Validation | Node | `pages/SOQL_Builder.py` |

No two apps share a port by default, so they can all run at the same time. If you see `[Errno 48] Address already in use`, something is already on that port. Find it with:

```bash
lsof -nP -iTCP:<port> -sTCP:LISTEN
```

---

## 1. Order Validation App

Streamlit app that validates Salesforce orders against business rules (QA and UAT). It also hosts the EDI Validator, Developer Console, SOQL Builder and PO Processing Engine as extra pages.

- **Folder:** `Order_Validation_App_Live/`
- **URL:** http://localhost:8502
- **Needs:** Python 3.8+, Node.js, Salesforce CLI (`sf`) logged in to `qa-org` / `uat-org`

```bash
cd Order_Validation_App_Live
chmod +x launch.sh        # first time only
./launch.sh
```

`launch.sh` installs dependencies, starts the Salesforce bridge on 3001 if it isn't already running, then starts Streamlit on 8502. Override the port with `STREAMLIT_PORT=8503 ./launch.sh`.

- **Pages:** Order Validation (main, `Order_Validation_App.py`), EDI Validator, Developer Console, SOQL Builder and PO Processing Engine (all in `pages/`). The main app's helpers live in `ov/` (including `ov/opp_header_checks.py`, the Opportunity header checks).
- **Two copies on one machine:** `launch.sh` skips starting the bridge if something already listens on 3001, even when that bridge belongs to another checkout. The EDI Validator page then talks to that other checkout's bridge. Stop the old one on 3001 first if you want this checkout's bridge code.
- **Always-on gateway:** the launchd agent `com.rubrik.order-validation-gateway` is pinned to the folder you ran `install_autostart.sh` from. If that is a different checkout, the gateway's port serves that checkout's code, not this one. The old checkout's gateway still listens on 8501 until you reinstall it from this folder.

**Optional always-on gateway.** `gateway.js` listens on 8502 and starts Streamlit (on 8510) and the bridge on the first visit. It stops them again after 15 minutes with no open connection.

```bash
bash install_autostart.sh      # install, also starts at login
bash uninstall_autostart.sh    # remove
```

- **Logs:** `Order_Validation_App_Live/logs/` (`gateway.log`, `app.log`, `launchd.log`), plus `/tmp/sf_bridge_server.log`.
- **Details:** see `Order_Validation_App_Live/README.md`.
- **PO Processing Engine:** there is no standalone PO engine folder in this repo any more. The engine lives in `Order_Validation_App_Live/po-processing-engine/` (FastAPI, see its own `README.md`) and runs only as the app's PO Processing Engine page. Opening that page starts it on 8012 (override with `PO_ENGINE_PORT`). It needs `sf` authenticated to `rbkqa` and `uat-org`.
- **Note:** the servers that its pages start themselves (PO engine on 8012, SOQL Builder on 4580) keep running after Streamlit stops.

## 2. Jira Dashboard

FastAPI dashboard for Jira projects, sprints, issues and QA tracking.

- **Folder:** `jira-dashboard/`
- **URL:** http://127.0.0.1:8000
- **Config:** `.env` with `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY` (gitignored)

```bash
cd jira-dashboard
python3 -m venv venv                 # first time only
source venv/bin/activate
pip install -r requirements.txt      # first time only
uvicorn main:app --reload
```

The app opens the browser itself on startup. To use another port, add `--port 8002`.

- **Local data:** `data/` (alert history, settings, sprint snapshots) is gitignored and starts empty on a fresh checkout.
- **Run from the project folder:** `main:app` and the `static/` / `templates/` paths resolve relative to `jira-dashboard/`.

## 3. BRD Jira UI

Compares BRD documents against Jira tickets.

- **Folder:** `brd-jira-ui/`
- **URL:** http://localhost:8001
- **Config:** reads `brd-jira-ui/.env`. If `JIRA_URL` isn't set there, it falls back to `jira-dashboard/.env`.

```bash
cd brd-jira-ui
python3 -m venv venv                 # first time only
source venv/bin/activate
pip install -r requirements.txt      # first time only
python main.py
```

`python main.py` starts uvicorn on port 8001 with reload and opens the browser. It binds to `0.0.0.0`, so it is reachable from other machines on your network. Use `uvicorn main:app --reload --port 8001` if you'd rather bind to localhost only.

## 4. SOQL Builder (standalone)

Visual SOQL builder, a small Node server with no npm dependencies to install. Order Validation normally starts it for you on 4580 when you open its SOQL Builder page.

- **Folder:** `Order_Validation_App_Live/soql-builder/`
- **URL:** http://127.0.0.1:4570 (default). Override with `SOQL_BUILDER_PORT`.
- **Needs:** Node.js and the Salesforce CLI (`sf`)

```bash
cd Order_Validation_App_Live/soql-builder
node server.mjs
```

## 5. SF Inspector Plus

React + TypeScript + Vite project built as a Chrome extension (`@crxjs/vite-plugin`).

- **Folder:** `sf-inspector-plus/`
- **Port:** Vite default (5173), no override configured

```bash
cd sf-inspector-plus
npm install          # first time only
npm run dev          # dev server with hot reload
npm run build        # production build to dist/
```

To use it as an extension, run `npm run build`, open `chrome://extensions`, turn on Developer mode, then choose **Load unpacked** and select `dist/`. The dev server alone is not enough to use the extension.

---

## Not servers

These have nothing to start locally:

- `LiveReport_AppsScript/` and `MSPPayGo_LiveReport_AppsScript/`: Google Apps Script web apps (`Code.gs` + `report.html`), deployed from the Apps Script editor.
- `weekly-status-checker/`: `WeeklyStatusChecker.gs`, an Apps Script.
- `MK_Branch/`: notes and a `.gs` tracker, no server.
- `MSPPayGo.html`, `SalaryBreakupCalculator.html`: standalone HTML files, open them in a browser.
- `PRDOPS-1625-linked-doc.md`: a notes file.

The top-level `po-processing-engine/`, the backup folders (`Order_Validation_App_backup_*`, `po-processing-engine_backup_*`) and `Ope mid year/` are no longer on disk, although git still tracks them. Don't restore and run a backup copy of an app while the live one is up, because it would clash on the same ports.
