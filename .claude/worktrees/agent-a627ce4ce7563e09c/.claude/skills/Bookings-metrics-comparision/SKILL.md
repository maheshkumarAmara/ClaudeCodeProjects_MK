---
name: Bookings-metrics-comparision
description: Compare Salesforce Booking Line Item field values against formula-calculated expected values. Generates an Excel report with pass/fail/NA status. Use when asked to validate bookings calculation, check booking line item accuracy, verify bookings formulas, or compare booking metrics for an order.
argument-hint: "<OrderNumber> <QA|UAT> [--verbose]"
allowed-tools: Bash(python3 *), Bash(pip *), Bash(sf *), Bash(npm *), Bash(mkdir *), Bash(ls *)
---

You are running the **Bookings Calculation Comparison Tool** — it compares Salesforce Booking Line Item (BLI) field values against formula-calculated expected values and generates an Excel report.

**Skill assets directory:** this skill's Python files are located in the same directory as this SKILL.md file.

> **One-time setup required** — each user must authenticate their Salesforce CLI with these aliases before first use:
> ```
> sf org login web --alias rbkqa --instance-url https://rubrikinc--rbkqa.sandbox.my.salesforce.com
> sf org login web --alias rbkuat --instance-url https://rubrikinc--rbkuat.sandbox.my.salesforce.com
> ```

User provided arguments: **$ARGUMENTS**

---

## STEP 1 — Parse Arguments

Parse `$ARGUMENTS` to extract:

| Parameter | Values | Required |
|-----------|--------|----------|
| **order_number** | The order number (e.g., `W-12345` or `00001234`) | Yes |
| **sandbox** | `QA` or `UAT` (case-insensitive) | Yes |
| **--verbose** | Include formula column in output (optional) | No |

**Parsing rules:**
- Look for `QA` or `UAT` token (case-insensitive) → sandbox
- The remaining token is the order number
- `--verbose` flag if present

**If arguments are missing or ambiguous**, prompt the user with AskUserQuestion.

---

## STEP 2 — Locate Paths

```bash
git rev-parse --show-toplevel
```

- **Script directory:** `{project_root}/.claude/skills/bookings-calculation`
- **Output directory:** `{project_root}/claude_outputs/bookings`

```bash
mkdir -p "{project_root}/claude_outputs/bookings"
```

---

## STEP 3 — Check Prerequisites

Same as cpq-metrics-compare: verify `sf` CLI and Python packages (`openpyxl`).
Sandbox aliases: `rbkqa` for QA, `rbkuat` for UAT.

---

## STEP 4 — Run Comparison

```bash
python3 "{script_dir}/bookings_compare.py" \
  --order-number "{order_number}" \
  --sandbox {sandbox} \
  --output-dir "{output_dir}" \
  {--verbose if specified}
```

The script will:
1. Find the Order by order number (searches Name and OrderNumber fields)
2. Find the linked Booking__c record
3. Fetch all Booking_Line_Item__c records
4. For each BLI, resolve the linked OrderItem → OpportunityLineItem chain
5. Compare BLI field values against formulas defined in field_config.csv
6. Generate a color-coded Excel workbook

---

## STEP 5 — Display Summary

```
Bookings Calculation Comparison Complete!
==========================================
Order: {order_number} | Sandbox: {sandbox}
Booking: {booking_name}

Results:
  BLI {name} ({type}): {pass}/{total} fields match ({rate}%)
  ...

==========================================
Excel Report: {full file path}
==========================================
```

---

## Field Configuration

Loaded from `field_config.csv` in this skill directory.
**Google Sheet:** https://docs.google.com/spreadsheets/d/1clLLkPDNRrYi_WYmHEu3uZxAMOaoZXpqGIlO6bT7xMg/

To update: download the sheet as CSV and replace `field_config.csv`.

---

## Object Hierarchy

```
Order (OrderNumber)
  └── Booking__c (Order__c)
        └── Booking_Line_Item__c (Booking__c)
              └── OrderItem (OrderProduct__c)
                    └── OpportunityLineItem (oliID__c)
```

## BLI Types

| Type__c Value | Description | Net multiplier |
|---|---|---|
| Revenue | Standard booking line | (100 - Rebate%) × 0.01 |
| PRF | Partner Referral Fee | N/A (Net = Gross) |
| Distributor Fee | Distributor rebate offset | Gross = negative values |
| Debooking | Reversal/return | (100 - Rebate%) × −0.01 |

## Rules

- Numeric tolerance: 0.10
- Excel: Green=Pass, Red=Fail, Grey=NA, Yellow=Error
- File naming: `bookings_comparison_{sandbox}_{OrderNumber}_{YYYYMMDD_HHMMSS}.xlsx`
