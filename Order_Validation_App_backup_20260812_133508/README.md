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

Make the launcher executable (one-time only):

```bash
chmod +x /Users/Amara.Maheshkumar/Documents/EDI_850_Implementation/Order_Validation_App/launch.sh
```

Then run from anywhere:
```bash
/Users/Amara.Maheshkumar/Documents/EDI_850_Implementation/Order_Validation_App/launch.sh
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
