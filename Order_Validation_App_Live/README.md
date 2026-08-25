# Order Validation App

Streamlit app that validates Salesforce orders against a set of business rules, authenticated via Salesforce CLI (no username/password required).

Supports both **QA** and **UAT** Salesforce sandboxes.

---

## Launch (Single Command)

```bash
./launch.sh
```

The script handles everything automatically:
1. Installs any missing dependencies
2. Launches the app at `http://localhost:8501`
3. Select **QA** or **UAT** from the Environment dropdown in the app sidebar

---

## First-Time Setup

Clone the repo, then from inside this folder make the launcher executable (one-time only):

```bash
chmod +x launch.sh
```

Then run:
```bash
./launch.sh
```

---

## Environments

| Environment | Alias     | Login URL |
|---|---|---|
| QA  | `qa-org`  | `https://test.salesforce.com` |
| UAT | `uat-org` | `https://rubrikinc--rbkuat.sandbox.my.salesforce.com` |

To log in manually (if needed):

**QA:**
```bash
sf org login web --alias qa-org --instance-url https://test.salesforce.com
```

**UAT:**
```bash
sf org login web --alias uat-org --instance-url https://rubrikinc--rbkuat.sandbox.my.salesforce.com
```

---

## Using the App

1. Select **Environment** (QA or UAT) in the sidebar
2. Click **Connect**
3. Enter an **Order Number** in the main area
4. Select **POC Stage** if needed
5. Click **Run Validation**

Results are displayed in sections:
- **🔵 Order Details** — informational fields and metrics
- **✅ Passed** — validations that passed
- **❌ Failed** — validations that failed
- **📦 OrderItem Validations** — line item level checks (ManualFulfilment, Product Name, Payment Options, Product Count)
- **POC Dates Validation** — POC start/end date checks (hidden for Revenue orders)

---

## Requirements

- Python 3.8+
- [Salesforce CLI](https://developer.salesforce.com/tools/salesforcecli) (`sf`)
- Access to the Salesforce QA or UAT org
- [Node.js](https://nodejs.org/) — required for the EDI Order Ops Tool page (runs a local bridge server)

---

## EDI Order Ops Tool

An additional page, **EDI Order Ops Tool**, is available in the sidebar. It queries Salesforce order/quote data directly through a local bridge server (`bridge/sf-bridge-server.js`) that shells out to the Salesforce CLI.

`launch.sh` automatically starts this bridge server in the background on `http://localhost:3001` (skipping the start if it's already running), so no manual setup is needed — just make sure you're logged in via `sf org login` first.

---

## Auto-start / auto-stop gateway (local machine only)

Instead of running `./launch.sh` by hand, you can install a small always-on
gateway (`gateway.js`) that sits on `http://localhost:8501` permanently:

- **Visit the URL** → if the app isn't running, the gateway starts it
  automatically (Streamlit + the bridge server) and proxies you through once
  it's ready. This takes a few seconds the first time.
- **Close the browser tab** → after **15 minutes** with no open connection to
  the app, the gateway stops Streamlit and the bridge server to free up
  resources. The gateway itself keeps listening, so visiting the URL again
  later transparently restarts everything.
- A tab left open keeps the app's WebSocket connection alive, so it will not
  be shut down while you're actively using it.

**Install (one-time):**
```bash
bash install_autostart.sh
```
This registers the gateway as a per-user `launchd` agent so it also starts
automatically at login.

**Uninstall:**
```bash
bash uninstall_autostart.sh
```

**Logs:**
- `logs/gateway.log` — gateway start/stop/proxy events
- `logs/app.log` — Streamlit + bridge output from the internal instance
- `logs/launchd.log` — launchd-level stdout/stderr for the gateway process

This setup (`gateway.js`, the plist, and the install/uninstall scripts) is
local to this machine only and is not part of the shared repo — the standard
`./launch.sh` workflow above still works exactly as before if you'd rather
run things manually.
