# Local Servers

Quick reference for every app in this repo that runs a local server. Paths are relative to the repo root (`ClaudeCodeProjects_MK/`).

## Port map

| Port | App | Stack | Started by |
|---|---|---|---|
| 8000 | [Jira Dashboard](#2-jira-dashboard) | FastAPI | `uvicorn main:app --reload` |
| 8001 | [BRD Jira UI](#3-brd-jira-ui) | FastAPI | `python main.py` |
| 8010 | [PO Processing Engine](#4-po-processing-engine) (standalone) | FastAPI | `uvicorn main:app --reload --port 8010` |
| 8501 | [Order Validation App](#1-order-validation-app) | Streamlit (or the gateway in front of it) | `./launch.sh` |
| 8510 | Order Validation internal Streamlit, behind the gateway | Streamlit | `gateway.js` |
| 3001 | Salesforce bridge for the EDI tool | Node | `launch.sh` / `gateway.js` |
| 8012 | PO Processing Engine when embedded in Order Validation | FastAPI | `pages/PO_Processing_Engine.py` |
| 4580 | SOQL Builder when embedded in Order Validation | Node | `pages/SOQL_Builder.py` |

No two apps share a port by default, so they can all run at the same time. If you see `[Errno 48] Address already in use`, something is already on that port. Find it with:

```bash
lsof -nP -iTCP:<port> -sTCP:LISTEN
```

---

## 1. Order Validation App

Streamlit app that validates Salesforce orders against business rules (QA and UAT). It also hosts the EDI Validator, Developer Console, SOQL Builder and PO Processing Engine as extra pages.

- **Folder:** `Order_Validation_App_Live/`
- **URL:** http://localhost:8501
- **Needs:** Python 3.8+, Node.js, Salesforce CLI (`sf`) logged in to `qa-org` / `uat-org`

```bash
cd Order_Validation_App_Live
chmod +x launch.sh        # first time only
./launch.sh
```

`launch.sh` installs dependencies, starts the Salesforce bridge on 3001 if it isn't already running, then starts Streamlit on 8501. Override the port with `STREAMLIT_PORT=8502 ./launch.sh`.

**Optional always-on gateway.** `gateway.js` listens on 8501 and starts Streamlit (on 8510) and the bridge on the first visit. It stops them again after 15 minutes with no open connection.

```bash
bash install_autostart.sh      # install, also starts at login
bash uninstall_autostart.sh    # remove
```

- **Logs:** `Order_Validation_App_Live/logs/` (`gateway.log`, `app.log`, `launchd.log`), plus `/tmp/sf_bridge_server.log`.
- **Details:** see `Order_Validation_App_Live/README.md`.
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

## 4. PO Processing Engine

Edit a distributor's purchase order PDF and regenerate it. It can also pull a Salesforce Quote (read-only) to pre-fill the form.

- **Folder:** `po-processing-engine/`
- **URL:** http://127.0.0.1:8010
- **Needs:** Salesforce CLI (`sf`) authenticated to `rbkqa` and `uat-org`
- **Config:** copy `env.example` to `.env`. `PORT` and `SALESFORCE_ORG_ALIAS` are optional.

```bash
cd po-processing-engine
python3 -m venv venv                 # first time only
source venv/bin/activate
pip install -r requirements.txt      # first time only
cp env.example .env                  # first time only
uvicorn main:app --reload --port 8010
```

You don't need to run this separately to use it from Order Validation. That app starts its own copy on 8012 when you open the PO Processing Engine page.

- **Details:** see `po-processing-engine/README.md`.

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
- `Order_Validation_App_backup_*/`, `po-processing-engine_backup_*/`: backups. Don't run these, they would clash with the live ports.
