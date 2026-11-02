# Local Servers

How to start every app in this repo that runs a local server, by hand, from the terminal. Paths are relative to the repo root (`ClaudeCodeProjects_MK/`).

Each server runs in the foreground of its own terminal tab/window. Open one terminal per server, leave it open while you use the app, and press `Ctrl+C` in it to stop.

## Port map

| Port | App | Stack | Manual start command |
|---|---|---|---|
| 8000 | [Jira Dashboard](#2-jira-dashboard) | FastAPI | `uvicorn main:app --reload` |
| 8001 | [BRD Jira UI](#3-brd-jira-ui) | FastAPI | `python main.py` |
| 8501 | [Order Validation App](#1-order-validation-app) | Streamlit (or the gateway in front of it) | `./launch.sh` |
| 8510 | Order Validation internal Streamlit, behind the gateway | Streamlit | started by `gateway.js` |
| 3001 | Salesforce bridge for the EDI tool | Node | `node sf-bridge-server.js` |
| 8012 | PO Processing Engine, embedded in Order Validation | FastAPI | `python3 -m uvicorn main:app --port 8012` |
| 4570 | [SOQL Builder](#4-soql-builder-standalone) (standalone default) | Node | `node server.mjs` |
| 4580 | SOQL Builder when embedded in Order Validation | Node | started by `pages/SOQL_Builder.py` |
| 5173 | [SF Inspector Plus](#5-sf-inspector-plus) (Vite dev server) | Vite | `npm run dev` |

No two apps share a port by default, so they can all run at the same time. If you see `[Errno 48] Address already in use`, something is already on that port.

**Find what is on a port:**

```bash
lsof -nP -iTCP:<port> -sTCP:LISTEN
```

**Stop whatever is on a port** (when `Ctrl+C` isn't an option, e.g. the server was started in the background):

```bash
lsof -t -iTCP:<port> -sTCP:LISTEN | xargs kill
```

---

## 1. Order Validation App

Streamlit app that validates Salesforce orders against business rules (QA and UAT). It also hosts the EDI Validator, Developer Console, SOQL Builder and PO Processing Engine as extra pages.

- **Folder:** `Order_Validation_App_Live/`
- **URL:** http://localhost:8501
- **Needs:** Python 3.8+, Node.js, Salesforce CLI (`sf`) logged in to `qa-org` / `uat-org` (the PO engine uses `rbkqa` and `uat-org`)

### Easiest: one terminal

```bash
cd Order_Validation_App_Live
chmod +x launch.sh        # first time only
./launch.sh
```

`launch.sh` installs dependencies, starts the Salesforce bridge on 3001 if nothing is already listening there, then runs Streamlit on 8501. Override the port with `STREAMLIT_PORT=8502 ./launch.sh`.

When run from a terminal it also handles the browser and cleanup for you (skip all of this with `NO_BROWSER=1 ./launch.sh`):

- **On start:** opens the app in your browser once Streamlit is up.
- **On exit** (`Ctrl+C` or closing the terminal window): stops Streamlit, stops the Salesforce bridge if that run started it (a bridge that was already running is left alone), and closes the browser tabs for the app (`localhost` or `127.0.0.1` on the app port), plus any tab its pages opened with "Open in a new tab": the PO Processing Engine (8012) and the SOQL Builder (4580).
- **Closing the tabs (macOS only):** uses AppleScript for Chrome, Brave, Edge and Safari, only if they're already running, and only tabs on those addresses. Other tabs are left alone. The first time, macOS may ask whether Terminal can control your browser. Allow it, or the tab won't close.
- **Not affected:** the PO engine (8012) and SOQL Builder (4580), which the app's pages start themselves, keep running. Stop them with the `kill` command above. The always-on gateway runs `launch.sh` in the background with its output going to a log, so it never opens or closes a browser tab.

### Fully manual: one terminal per piece

Use this when you want to see each server's output, or restart one piece without the others.

**Terminal 1: Salesforce bridge** (needed by the EDI Validator page)

```bash
cd Order_Validation_App_Live/bridge
node sf-bridge-server.js
```

**Terminal 2: the app**

```bash
cd Order_Validation_App_Live
pip3 install -r requirements.txt      # first time only
streamlit run Order_Validation_App.py --server.port 8501 --server.headless true --server.enableCORS false --server.enableXsrfProtection false
```

Then open http://localhost:8501.

**Terminal 3 (optional): PO Processing Engine.** Opening the PO Processing Engine page starts this for you, so you only need it when you want its logs or want to run it without Streamlit. If something already listens on 8012, the page uses it instead of starting its own.

```bash
cd Order_Validation_App_Live/po-processing-engine
pip3 install -r requirements.txt      # first time only
python3 -m uvicorn main:app --host 127.0.0.1 --port 8012 --reload
```

The engine's own UI is then at http://127.0.0.1:8012. `python3 main.py` also works, but it uses the engine's default port 8010 (`PORT` env var). If you start it that way, set `PO_ENGINE_PORT=8010` before launching Streamlit so the page finds it.

**Terminal 4 (optional): SOQL Builder.** Same idea: the SOQL Builder page starts it on 4580 by itself. See [section 4](#4-soql-builder-standalone) to run it by hand.

### Notes

- **Pages:** Order Validation (main, `Order_Validation_App.py`), EDI Validator, Developer Console, SOQL Builder and PO Processing Engine (all in `pages/`). The main app's helpers live in `ov/`.
- **Servers its pages start themselves:** the PO engine (8012) and SOQL Builder (4580) keep running after Streamlit stops. Stop them with the `kill` command above.
- **Two copies on one machine:** `launch.sh` skips starting the bridge if something already listens on 3001, even when that bridge belongs to another checkout. The EDI Validator page then talks to that other checkout's bridge. Stop the old one on 3001 first if you want this checkout's bridge code.
- **Logs:** when started manually, output goes to the terminal. The bridge started by `launch.sh` logs to `/tmp/sf_bridge_server.log`. Servers started by the Streamlit pages log under `Order_Validation_App_Live/logs/`.
- **Details:** see `Order_Validation_App_Live/README.md`. The PO engine has its own `po-processing-engine/README.md`. There is no standalone PO engine folder in this repo any more.

### Optional: always-on gateway (not manual)

`gateway.js` listens on 8501 and starts Streamlit (on 8510) and the bridge on the first visit, then stops them after 15 minutes with no open connection. It is a launchd agent (`com.rubrik.order-validation-gateway`), so it starts at login. While it is installed, **it holds port 8501**, so a manual `./launch.sh` will fail with "Address already in use".

```bash
bash install_autostart.sh      # install, also starts at login
bash uninstall_autostart.sh    # remove, then 8501 is free for manual runs
```

The agent is pinned to the folder you ran `install_autostart.sh` from. If that is a different checkout, port 8501 serves that checkout's code, not this one. Uninstall and reinstall from this folder to change that. Gateway logs: `Order_Validation_App_Live/logs/` (`gateway.log`, `app.log`, `launchd.log`).

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

The app opens the browser itself on startup. To use another port, add `--port 8002`. `Ctrl+C` stops it. Run `deactivate` afterwards to leave the virtualenv.

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

To use another port: `SOQL_BUILDER_PORT=4580 node server.mjs`.

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

The top-level `po-processing-engine/`, the backup folders (`Order_Validation_App_backup_*`, `po-processing-engine_backup_*`) and `Ope mid year/` are no longer on disk, although git still tracks them. Don't restore and run a backup copy of an app while the live one is up, because it would clash on the same ports.
