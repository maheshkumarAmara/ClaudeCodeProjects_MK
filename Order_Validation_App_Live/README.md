# Order Validation App

Streamlit app that validates Salesforce orders against a set of business rules, authenticated via Salesforce CLI (no username/password required). It also hosts a few related tools as extra pages (see [Pages](#pages)).

Supports both **QA** and **UAT** Salesforce sandboxes.

---

## Launch (Single Command)

```bash
./launch.sh
```

The script handles everything automatically:
1. Installs any missing dependencies (`requirements.txt`, which also covers the PO Processing Engine)
2. Starts the Salesforce bridge server for the EDI tool (port 3001) if it isn't already running
3. Launches the app at `http://localhost:8501`
4. Select **QA** or **UAT** from the Environment dropdown in the app sidebar

The first time, make the launcher executable: `chmod +x launch.sh`.

---

## Pages

| Page | File | What it does | Needs |
|---|---|---|---|
| **Order Validation** (main) | `Order_Validation_App.py` | Validates one or more orders against the business rules, with booking line item checks | `sf` CLI |
| **EDI Validator** | `pages/EDI_Validator.py` | Embeds `assets/EDI_Order_Ops_Tool.html`, which queries order/quote data through the local bridge server (`bridge/sf-bridge-server.js`) | `sf` CLI, Node.js |
| **Developer Console** | `pages/Developer_Console.py` | Runs Anonymous Apex and SOQL against QA/UAT through `sf`. Statements that look like DML ask for confirmation first. Keeps a run history | `sf` CLI |
| **SOQL Builder** | `pages/SOQL_Builder.py` | Visual SOQL builder (`soql-builder/`), a local Node server started on demand | Node.js |
| **PO Processing Engine** | `pages/PO_Processing_Engine.py` | Edit a distributor's purchase order and regenerate the PDF, optionally pre-filled from a Salesforce Quote. See [`po-processing-engine/README.md`](po-processing-engine/README.md) | `sf` CLI, Python deps |

Each page lives in `pages/` and starts its own local server (where it needs one) the first time it is opened. Those servers keep running after Streamlit stops.

---

## Ports

| Port | What | Started by |
|---|---|---|
| 8501 | The app (or the gateway in front of it, see below) | `./launch.sh` (override with `STREAMLIT_PORT`) |
| 8510 | Internal Streamlit instance behind the gateway | `gateway.js` |
| 3001 | Salesforce bridge for the EDI tool (hard-coded in `bridge/sf-bridge-server.js` and the EDI HTML) | `launch.sh` / `gateway.js` |
| 8012 | PO Processing Engine when embedded (override with `PO_ENGINE_PORT`) | `pages/PO_Processing_Engine.py` |
| 8010 | PO Processing Engine when run on its own (`uvicorn main:app`) | you |
| 4580 | SOQL Builder when embedded (override with `SOQL_BUILDER_PORT`) | `pages/SOQL_Builder.py` |

Server logs: `/tmp/sf_bridge_server.log`, `/tmp/po_processing_engine_server.log`, `/tmp/soql_builder_server.log`.

---

## Environments

| Environment | Alias | Login URL |
|---|---|---|
| QA  | `qa-org`  | `https://rubrikinc--rbkqa.sandbox.my.salesforce.com` |
| UAT | `uat-org` | `https://rubrikinc--rbkuat.sandbox.my.salesforce.com` |

Log in with the device flow:

```bash
sf org login device --alias qa-org  --instance-url https://rubrikinc--rbkqa.sandbox.my.salesforce.com
sf org login device --alias uat-org --instance-url https://rubrikinc--rbkuat.sandbox.my.salesforce.com
```

If `sf org login web` fails with `AuthCodeExchangeError / invalid_grant`, use the device flow above instead.

**Alias note:** the main app uses `qa-org`. The Developer Console tries `qa-org` and then `rbkqa`. The PO Processing Engine uses `rbkqa` (QA) and `uat-org` (UAT). If your QA org is saved under only one of those aliases, the other tools will not find it. Check with `sf org list`.

---

## Using the Order Validation App

1. Select **Environment** (QA or UAT) in the sidebar
2. Click **Connect**
3. Paste one or more **Order Numbers**, or upload a CSV
4. Check the **Target Date** (fetched automatically from the order configuration where available)
5. Adjust **Validation Scope**, upload a **Scenario Matrix** or skip specific checks in the sidebar if needed
6. Click **Run Validation**

Results are shown per order:
- **Order Details**: informational fields and metrics
- **Passed / Failed**: the validation results
- **OrderItem validations**: line item level checks
- **Booking Header and Line Items** comparison against formula-calculated values
- Downloads (CSV / Excel / HTML) and a batch summary when several orders are run

Run history is kept in `data/history.json`. An uploaded scenario matrix is saved to `data/fulfillment_matrix.json`.

---

## Requirements

- Python 3.8+
- [Salesforce CLI](https://developer.salesforce.com/tools/salesforcecli) (`sf`), logged in to the org(s) you use
- [Node.js](https://nodejs.org/), for the EDI Validator (bridge server) and the SOQL Builder
- Access to the Salesforce QA or UAT org

---

## Repository layout

```
Order_Validation_App.py   Main app (Order Validation page)
streamlit_app.py          Older copy of the main app. NOT launched by launch.sh; kept for reference
pages/                    Extra Streamlit pages (one file = one sidebar entry)
po-processing-engine/     FastAPI app for the PO Processing Engine (own README)
soql-builder/             Node app for the SOQL Builder page
bridge/                   Node bridge between the EDI tool and the sf CLI
assets/                   EDI_Order_Ops_Tool.html
gateway.js                Optional always-on gateway (see below)
launch.sh                 One-command launcher
data/                     Run history and scenario matrix (local data)
```

---

## Auto-start / auto-stop gateway (local machine only)

Instead of running `./launch.sh` by hand, you can install a small always-on
gateway (`gateway.js`) that sits on `http://localhost:8501` permanently:

- **Visit the URL** → if the app isn't running, the gateway starts it
  automatically (Streamlit on port 8510 + the bridge server) and proxies you
  through once it's ready. This takes a few seconds the first time.
- **Close the browser tab** → after **15 minutes** with no open connection to
  the app, the gateway stops Streamlit and the bridge server to free up
  resources. The gateway itself keeps listening, so visiting the URL again
  later transparently restarts everything.
- A tab left open keeps the app's WebSocket connection alive, so it will not
  be shut down while you're actively using it.
- The PO Processing Engine and SOQL Builder servers are **not** stopped by the
  gateway (they were started by their pages, not by the gateway).

Environment overrides: `GATEWAY_PORT`, `GATEWAY_BACKEND_PORT`, `GATEWAY_BRIDGE_PORT`, `GATEWAY_IDLE_MS`.

**Install (one-time):**
```bash
bash install_autostart.sh
```
This registers the gateway as a per-user `launchd` agent so it also starts
automatically at login. The agent points at the folder you run the script from,
so re-run it if you move or copy this folder.

**Temporarily stop / start it:**
```bash
launchctl bootout   gui/$(id -u)/com.rubrik.order-validation-gateway
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.rubrik.order-validation-gateway.plist
```

**Uninstall:**
```bash
bash uninstall_autostart.sh
```

**Logs:**
- `logs/gateway.log`: gateway start/stop/proxy events
- `logs/app.log`: Streamlit + bridge output from the internal instance
- `logs/launchd.log`: launchd-level stdout/stderr for the gateway process

The standard `./launch.sh` workflow above works exactly as before if you'd
rather run things manually.
