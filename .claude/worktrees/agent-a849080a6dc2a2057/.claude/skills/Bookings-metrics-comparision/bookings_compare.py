#!/usr/bin/env python3
"""Bookings Calculation Comparison Tool — validates Booking Line Item field values against formulas."""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter

# ── Excel fills ─────────────────────────────────────────────────────────────────
FILL_PASS  = PatternFill(start_color="92D050", end_color="92D050", fill_type="solid")
FILL_FAIL  = PatternFill(start_color="FF6666", end_color="FF6666", fill_type="solid")
FILL_NA    = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
FILL_SKIP  = PatternFill(start_color="BFBFBF", end_color="BFBFBF", fill_type="solid")
FILL_ERROR = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
FILL_HDR   = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
FILL_SUBHDR= PatternFill(start_color="2E75B6", end_color="2E75B6", fill_type="solid")
WHITE_FONT = Font(color="FFFFFF", bold=True)

NUMERIC_TOL = 0.10


# ── Helpers ──────────────────────────────────────────────────────────────────────
def sf_alias(sandbox: str) -> str:
    return "rbkqa" if sandbox.upper() == "QA" else "rbkuat"


def safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def safe_div(a, b) -> Optional[float]:
    if b is None or b == 0 or a is None:
        return None
    return a / b


def run_soql(query: str, alias: str) -> list[dict]:
    cmd = ["sf", "data", "query", "--query", query, "--target-org", alias, "--json"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    raw = res.stdout
    json_start = raw.find("{")
    if json_start == -1:
        raise RuntimeError(f"SOQL failed: {res.stderr or raw}")
    try:
        data = json.loads(raw[json_start:])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON parse error: {exc}\nRaw: {raw[:500]}")
    if data.get("status") != 0:
        msg = data.get("message") or data.get("name") or str(data)
        raise RuntimeError(f"SOQL error: {msg}")
    return data.get("result", {}).get("records", [])


def soql_with_fallback(fields: list[str], sobject: str, where: str, alias: str) -> list[dict]:
    remaining = list(fields)
    while remaining:
        q = f"SELECT {', '.join(remaining)} FROM {sobject} WHERE {where}"
        try:
            return run_soql(q, alias)
        except RuntimeError as e:
            err = str(e)
            if "INVALID_FIELD" in err or "No such column" in err:
                m = re.search(r"No such column ['\"]?(\w+)['\"]?", err)
                bad = m.group(1) if m else None
                if bad and bad in remaining:
                    print(f"    [warn] Field not in org, skipping: {bad}", file=sys.stderr)
                    remaining.remove(bad)
                    continue
            raise
    return []


def soql_in(fields: list[str], sobject: str, id_field: str, ids: list[str], alias: str) -> list[dict]:
    """Query with IN clause, batching if needed (max 200 IDs per batch)."""
    if not ids:
        return []
    all_recs = []
    batch_size = 200
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        id_list = ", ".join(f"'{x}'" for x in batch)
        recs = soql_with_fallback(fields, sobject, f"{id_field} IN ({id_list})", alias)
        all_recs.extend(recs)
    return all_recs


# ── Field config ─────────────────────────────────────────────────────────────────
def load_field_config(script_dir: str) -> list[dict]:
    path = os.path.join(script_dir, "field_config.csv")
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("Active", "").strip().lower() == "yes":
                rows.append(row)
    return rows


# ── Data fetch ────────────────────────────────────────────────────────────────────
BOOKING_FIELDS = [
    "Id", "Name", "Order__c", "Opportunity__c", "Status__c",
    "Order_Type__c", "Opportunity_Type__c",
    # Header roll-up fields
    "Gross_Bookings_Total__c", "Gross_ACV_Total__c",
    "New_Expansion_TCV__c", "Gross_New_Expansion_ACV__c",
    "Subsumed_Renewal_TCV__c", "Gross_Subsumed_Renewal_ACV__c",
    "Net_Bookings_Total__c", "Net_ACV_Total__c",
    "Net_New_Expansion_TCV__c", "Net_New_Expansion_ACV__c",
    "Net_Subsumed_Renewal_TCV__c", "Net_Subsumed_Renewal_ACV__c",
]

# (display name, Booking__c API field, BLI API field to sum — ALL BLI types)
BOOKING_HEADER_CHECKS = [
    ("Gross TCV Total",            "Gross_Bookings_Total__c",       "Total_Price__c"),
    ("Gross New/Expansion TCV",    "New_Expansion_TCV__c",          "New_Expansion_TCV__c"),
    ("Gross Subsumed Renewal TCV", "Subsumed_Renewal_TCV__c",       "Subsumed_Renewal_TCV__c"),
    ("Net TCV Total",              "Net_Bookings_Total__c",         "Net_TCV_Amount__c"),
    ("Net New/Expansion TCV",      "Net_New_Expansion_TCV__c",      "Net_New_Expansion_TCV__c"),
    ("Net Renewal Subsumed TCV",   "Net_Subsumed_Renewal_TCV__c",   "Net_Subsumed_Renewal_TCV__c"),
    ("Gross ACV Total",            "Gross_ACV_Total__c",            "Gross_ACV_Amount__c"),
    ("Gross New/Expansion ACV",    "Gross_New_Expansion_ACV__c",    "Gross_New_Expansion_ACV__c"),
    ("Gross Subsumed Renewal ACV", "Gross_Subsumed_Renewal_ACV__c", "Gross_Subsumed_Renewal_ACV__c"),
    ("Net ACV Total",              "Net_ACV_Total__c",              "Net_ACV_Amount__c"),
    ("Net New/Expansion ACV",      "Net_New_Expansion_ACV__c",      "Net_New_Expansion_ACV__c"),
    ("Net Renewal Subsumed ACV",   "Net_Subsumed_Renewal_ACV__c",   "Net_Subsumed_Renewal_ACV__c"),
]

BLI_FIELDS = [
    "Id", "Name", "Booking__c", "OrderProduct__c", "CCR__c",
    "Type__c", "Rebate__c",
    # Gross TCV / ACV
    "Total_Price__c", "New_Expansion_TCV__c", "Subsumed_Renewal_TCV__c",
    "Gross_ACV_Amount__c", "Gross_New_Expansion_ACV__c", "Gross_Subsumed_Renewal_ACV__c",
    "Gross_Renewal_ACV__c", "Gross_Renewal_TCV__c", "Gross_RBOB_ACV__c",
    # Net TCV / ACV
    "Net_TCV_Amount__c", "Net_New_Expansion_TCV__c", "Net_Subsumed_Renewal_TCV__c",
    "Net_ACV_Amount__c", "Net_New_Expansion_ACV__c", "Net_Subsumed_Renewal_ACV__c",
    "Net_Renewal_ACV__c", "Net_Renewal_TCV__c", "Net_RBOB_ACV__c",
    # Credits / discounts
    "PromoDiscTCV__c", "Oppty_Trade_Up_Discount__c", "Prepayment_Credit__c",
    # Other
    "Partner_Referral_Fee__c", "Product_Name__c", "Product_Code__c",
    "Commission_Impact__c", "Impacts_Gross_Bookings__c", "Impacts_Net_Bookings__c",
]

ORDER_ITEM_FIELDS = [
    "Id", "OrderId", "Quantity", "TotalPrice", "UnitPrice",
    "oliID__c", "SBQQ__QuoteLine__c",
    "PromoDiscTCV__c", "Oppty_Trade_Up_Discount__c", "Prepaid_Credit__c",
    "SBQQ__ProrateMultiplier__c", "Product2Id", "ProductID__c", "Product_Name__c",
]

OLI_FIELDS = [
    "Id", "TotalPrice", "Quantity",
    "ACV_Amount__c", "New_Expansion_TCV__c", "Subsumed_Renewal_TCV__c",
    "New_Expansion_ACV__c", "Subsumed_Renewal_Amount__c",
    "PromoDiscTCV__c", "Oppty_Trade_Up_Discount__c", "Prepayment_Credit__c",
    "OpportunityId", "Product2Id", "SBQQ__QuoteLine__c",
]

OPP_FIELDS = [
    "Id", "Name", "Amount", "ACV_Amount__c", "New_Expansion_ACV__c",
    "New_Expansion_TCV__c", "Renewal_Subsumed_TCV__c", "Renewal_ACV__c",
    "Referral_Fee_Amount__c", "CCR_Type__c",
]


def find_order(order_number: str, alias: str) -> dict:
    """Find Order by Name or OrderNumber (handles W- prefix or numeric format)."""
    for field in ["Name", "OrderNumber"]:
        try:
            recs = run_soql(
                f"SELECT Id, Name, OrderNumber, OpportunityId FROM Order "
                f"WHERE {field} = '{order_number}' LIMIT 1", alias
            )
            if recs:
                return recs[0]
        except RuntimeError:
            pass
    raise ValueError(f"Order '{order_number}' not found in {alias} (searched Name and OrderNumber)")


def fetch_all_data(order_number: str, alias: str) -> dict:
    """Fetch all data needed for the comparison."""
    # 1. Order
    print(f"  Fetching Order {order_number}...")
    order = find_order(order_number, alias)

    # 2. Booking
    print(f"  Fetching Booking...")
    bookings = soql_with_fallback(BOOKING_FIELDS, "Booking__c", f"Order__c = '{order['Id']}'", alias)
    if not bookings:
        raise ValueError(f"No Booking__c found for Order '{order_number}'")
    booking = bookings[0]

    # 3. Booking Line Items
    print(f"  Fetching Booking Line Items...")
    blis = soql_with_fallback(BLI_FIELDS, "Booking_Line_Item__c", f"Booking__c = '{booking['Id']}'", alias)
    print(f"  Found {len(blis)} BLIs")

    # 4. OrderItems for BLIs that have OrderProduct__c
    op_ids = [b["OrderProduct__c"] for b in blis if b.get("OrderProduct__c")]
    oi_map: dict[str, dict] = {}
    if op_ids:
        print(f"  Fetching {len(op_ids)} OrderItem(s)...")
        ois = soql_in(ORDER_ITEM_FIELDS, "OrderItem", "Id", op_ids, alias)
        oi_map = {oi["Id"]: oi for oi in ois}

    # 5. OLIs for OrderItems that have oliID__c (direct link)
    oli_ids = [oi["oliID__c"] for oi in oi_map.values() if oi.get("oliID__c")]
    oli_map: dict[str, dict] = {}
    ql_to_oli_map: dict[str, dict] = {}
    if oli_ids:
        print(f"  Fetching {len(oli_ids)} OpportunityLineItem(s) via oliID__c...")
        olis = soql_in(OLI_FIELDS, "OpportunityLineItem", "Id", oli_ids, alias)
        oli_map = {oli["Id"]: oli for oli in olis}

    # 5b. Fallback: OLIs via SBQQ__QuoteLine__c for OIs where oliID__c is null
    ql_ids = [oi["SBQQ__QuoteLine__c"] for oi in oi_map.values()
              if not oi.get("oliID__c") and oi.get("SBQQ__QuoteLine__c")]
    if ql_ids:
        print(f"  Fetching {len(ql_ids)} OLI(s) via SBQQ__QuoteLine__c fallback...")
        olis_fb = soql_in(OLI_FIELDS, "OpportunityLineItem", "SBQQ__QuoteLine__c", ql_ids, alias)
        for oli in olis_fb:
            ql = oli.get("SBQQ__QuoteLine__c")
            if ql:
                ql_to_oli_map[ql] = oli
            oli_map[oli["Id"]] = oli

    # 6. Opportunity (for PRF / Debook cross-validation)
    opp_map: dict[str, dict] = {}
    opp_ids = {booking.get("Opportunity__c"), order.get("OpportunityId")}
    opp_ids.discard(None)
    if opp_ids:
        print(f"  Fetching Opportunity...")
        opps = soql_in(OPP_FIELDS, "Opportunity", "Id", list(opp_ids), alias)
        opp_map = {o["Id"]: o for o in opps}

    return {
        "order": order,
        "booking": booking,
        "blis": blis,
        "oi_map": oi_map,
        "oli_map": oli_map,
        "ql_to_oli_map": ql_to_oli_map,
        "opp_map": opp_map,
    }


# ── Comparison logic ──────────────────────────────────────────────────────────────
def compare_vals(sf_val, expected, label: str = "") -> tuple[str, str]:
    if expected is None:
        return "ERROR", f"Cannot calculate expected value{(' for ' + label) if label else ''}"
    sf_n = safe_float(sf_val)
    ex_n = safe_float(expected)
    if ex_n is not None:
        sf_num = sf_n if sf_n is not None else 0.0
        diff = abs(sf_num - ex_n)
        if diff <= NUMERIC_TOL:
            note = "" if sf_n is not None else "(SF null treated as 0)"
            return "PASS", note
        sf_label = f"{sf_n:.4f}" if sf_n is not None else "null"
        return "FAIL", f"SF={sf_label}  Expected={ex_n:.4f}  Δ={diff:.4f}"
    # String comparison
    sf_s = str(sf_val) if sf_val is not None else ""
    ex_s = str(expected)
    return ("PASS", "") if sf_s == ex_s else ("FAIL", f"SF='{sf_s}'  Expected='{ex_s}'")


def row(fname, api, vtype, formula, sf_val, expected, status, note):
    return dict(field_name=fname, api_name=api, validation_type=vtype, formula=formula,
                sf_value=sf_val, expected_value=expected, status=status, note=note)


def compare_revenue_bli(bli: dict, oi: Optional[dict], oli: Optional[dict], dist_rebate: float = 0.0) -> list[dict]:
    results = []
    # Revenue BLIs inherit the rebate from the sibling Distributor Fee BLI (their own Rebate__c is null)
    rebate = safe_float(bli.get("Rebate__c")) or dist_rebate
    net_factor = (100 - rebate) * 0.01

    def src(fname, api, formula, sf_val, oli_val):
        """Source comparison: BLI field vs OLI field."""
        if oli is None:
            return row(fname, api, "Source", formula, sf_val, None, "ERROR", "OLI not found")
        # Treat OLI null as 0 for numeric source comparisons
        expected = oli_val if oli_val is not None else 0.0
        status, note = compare_vals(sf_val, expected)
        if oli_val is None and status == "PASS":
            note = "(OLI field null, treated as 0)"
        return row(fname, api, "Source", formula, sf_val, expected, status, note)

    def fml(fname, api, formula, sf_val, expected):
        """Formula validation: BLI field vs calculated value."""
        status, note = compare_vals(sf_val, expected)
        return row(fname, api, "Formula", formula, sf_val, expected, status, note)

    # ── Gross TCV fields (source from OLI) ──────────────────────────────────────
    results.append(src(
        "Gross TCV Amount", "Total_Price__c",
        "OLI.TotalPrice",
        bli.get("Total_Price__c"),
        oli.get("TotalPrice") if oli else None,
    ))
    results.append(src(
        "Gross New/Expansion TCV", "New_Expansion_TCV__c",
        "OLI.New_Expansion_TCV__c",
        bli.get("New_Expansion_TCV__c"),
        oli.get("New_Expansion_TCV__c") if oli else None,
    ))
    results.append(src(
        "Gross Subsumed Renewal TCV", "Subsumed_Renewal_TCV__c",
        "OLI.Subsumed_Renewal_TCV__c",
        bli.get("Subsumed_Renewal_TCV__c"),
        oli.get("Subsumed_Renewal_TCV__c") if oli else None,
    ))

    # ── Net TCV fields (formula from BLI Gross) ─────────────────────────────────
    gross_tcv = safe_float(bli.get("Total_Price__c"))
    gross_exp_tcv = safe_float(bli.get("New_Expansion_TCV__c"))
    gross_sub_tcv = safe_float(bli.get("Subsumed_Renewal_TCV__c"))

    results.append(fml(
        "Net TCV Amount", "Net_TCV_Amount__c",
        f"Total_Price__c × ((100 - {rebate}) × 0.01) = × {net_factor:.4f}",
        bli.get("Net_TCV_Amount__c"),
        gross_tcv * net_factor if gross_tcv is not None else None,
    ))
    results.append(fml(
        "Net New/Expansion TCV", "Net_New_Expansion_TCV__c",
        f"New_Expansion_TCV__c × {net_factor:.4f}",
        bli.get("Net_New_Expansion_TCV__c"),
        gross_exp_tcv * net_factor if gross_exp_tcv is not None else None,
    ))
    results.append(fml(
        "Net Subsumed Renewal TCV", "Net_Subsumed_Renewal_TCV__c",
        f"Subsumed_Renewal_TCV__c × {net_factor:.4f}",
        bli.get("Net_Subsumed_Renewal_TCV__c"),
        gross_sub_tcv * net_factor if gross_sub_tcv is not None else None,
    ))

    # ── Gross ACV fields (source from OLI) ──────────────────────────────────────
    results.append(src(
        "Gross ACV Amount", "Gross_ACV_Amount__c",
        "OLI.ACV_Amount__c",
        bli.get("Gross_ACV_Amount__c"),
        oli.get("ACV_Amount__c") if oli else None,
    ))
    results.append(src(
        "Gross New/Expansion ACV", "Gross_New_Expansion_ACV__c",
        "OLI.New_Expansion_ACV__c",
        bli.get("Gross_New_Expansion_ACV__c"),
        oli.get("New_Expansion_ACV__c") if oli else None,
    ))
    results.append(src(
        "Gross Subsumed Renewal ACV", "Gross_Subsumed_Renewal_ACV__c",
        "OLI.Subsumed_Renewal_Amount__c",
        bli.get("Gross_Subsumed_Renewal_ACV__c"),
        oli.get("Subsumed_Renewal_Amount__c") if oli else None,
    ))

    # ── Net ACV fields (formula from BLI Gross ACV) ──────────────────────────────
    gross_acv = safe_float(bli.get("Gross_ACV_Amount__c"))
    gross_exp_acv = safe_float(bli.get("Gross_New_Expansion_ACV__c"))
    gross_sub_acv = safe_float(bli.get("Gross_Subsumed_Renewal_ACV__c"))

    results.append(fml(
        "Net ACV Amount", "Net_ACV_Amount__c",
        f"Gross_ACV_Amount__c × {net_factor:.4f}",
        bli.get("Net_ACV_Amount__c"),
        gross_acv * net_factor if gross_acv is not None else None,
    ))
    results.append(fml(
        "Net New/Expansion ACV", "Net_New_Expansion_ACV__c",
        f"Gross_New_Expansion_ACV__c × {net_factor:.4f}",
        bli.get("Net_New_Expansion_ACV__c"),
        gross_exp_acv * net_factor if gross_exp_acv is not None else None,
    ))
    results.append(fml(
        "Net Subsumed Renewal ACV", "Net_Subsumed_Renewal_ACV__c",
        f"Gross_Subsumed_Renewal_ACV__c × {net_factor:.4f}",
        bli.get("Net_Subsumed_Renewal_ACV__c"),
        gross_sub_acv * net_factor if gross_sub_acv is not None else None,
    ))

    # ── Prorated credits (OLI × qty ratio) ───────────────────────────────────────
    oi_qty = safe_float(oi.get("Quantity") if oi else None)
    oli_qty = safe_float(oli.get("Quantity") if oli else None)
    qty_ratio = safe_div(oi_qty, oli_qty)
    qty_note = f"OI.Qty={oi_qty}, OLI.Qty={oli_qty}, ratio={qty_ratio:.4f}" if qty_ratio else "Cannot compute qty ratio"

    def prorated(fname, api, formula_name, bli_val, oli_val):
        if oli is None or oi is None:
            return row(fname, api, "Formula", formula_name, bli_val, None, "ERROR", "OLI/OI not linked")
        # Treat OLI null as 0 for proration
        oli_num = oli_val if oli_val is not None else 0.0
        expected = oli_num * qty_ratio if qty_ratio is not None else 0.0
        formula = f"OLI.{api} × (OI.Qty/OLI.Qty) — {qty_note}"
        status, note = compare_vals(bli_val, expected)
        if oli_val is None and status == "PASS":
            note = "(OLI field null, treated as 0)"
        return row(fname, api, "Formula", formula, bli_val, expected, status, note)

    results.append(prorated(
        "Promo Discount TCV", "PromoDiscTCV__c", "OLI.PromoDiscTCV__c × qty_ratio",
        bli.get("PromoDiscTCV__c"), safe_float(oli.get("PromoDiscTCV__c") if oli else None)
    ))
    results.append(prorated(
        "Trade-up Credit TCV", "Oppty_Trade_Up_Discount__c", "OLI.Oppty_Trade_Up_Discount__c × qty_ratio",
        bli.get("Oppty_Trade_Up_Discount__c"), safe_float(oli.get("Oppty_Trade_Up_Discount__c") if oli else None)
    ))
    results.append(prorated(
        "Prepayment Credit TCV", "Prepayment_Credit__c", "OLI.Prepayment_Credit__c × qty_ratio",
        bli.get("Prepayment_Credit__c"), safe_float(oli.get("Prepayment_Credit__c") if oli else None)
    ))

    return results


def compare_prf_bli(bli: dict, all_rev_blis: list[dict]) -> list[dict]:
    """PRF BLI: validate gross fields against referral-fee proportional logic, net = gross."""
    results = []

    # Sum Revenue BLI totals for proportional calculations
    rev_gross_tcv = sum(safe_float(b.get("Total_Price__c")) or 0 for b in all_rev_blis)
    rev_gross_exp_tcv = sum(safe_float(b.get("New_Expansion_TCV__c")) or 0 for b in all_rev_blis)
    rev_gross_sub_tcv = sum(safe_float(b.get("Subsumed_Renewal_TCV__c")) or 0 for b in all_rev_blis)
    rev_gross_acv = sum(safe_float(b.get("Gross_ACV_Amount__c")) or 0 for b in all_rev_blis)
    rev_gross_exp_acv = sum(safe_float(b.get("Gross_New_Expansion_ACV__c")) or 0 for b in all_rev_blis)
    rev_gross_sub_acv = sum(safe_float(b.get("Gross_Subsumed_Renewal_ACV__c")) or 0 for b in all_rev_blis)

    prf_gross_tcv = safe_float(bli.get("Total_Price__c"))

    # Gross New/Expansion TCV = PRF Gross TCV × (Rev New/Exp TCV / Rev Gross TCV)
    exp_ratio = safe_div(rev_gross_exp_tcv, rev_gross_tcv)
    sub_ratio = safe_div(rev_gross_sub_tcv, rev_gross_tcv)
    acv_ratio = safe_div(rev_gross_acv, rev_gross_tcv) if rev_gross_tcv else None

    def fml(fname, api, formula, sf_val, expected):
        status, note = compare_vals(sf_val, expected)
        return row(fname, api, "Formula", formula, sf_val, expected, status, note)

    results.append(row(
        "Gross TCV Amount", "Total_Price__c", "Source",
        "Referral Fee Amount from Opportunity",
        prf_gross_tcv, None, "NA",
        "Manual verification required — source is Referral Fee Amount on Opportunity"
    ))

    expected_exp_tcv = prf_gross_tcv * exp_ratio if (prf_gross_tcv is not None and exp_ratio is not None) else None
    results.append(fml(
        "Gross New/Expansion TCV", "New_Expansion_TCV__c",
        f"Total_Price__c × (RevNewExpTCV/RevGrossTCV) = × {exp_ratio:.4f}" if exp_ratio else "ratio unavailable",
        bli.get("New_Expansion_TCV__c"), expected_exp_tcv
    ))

    expected_sub_tcv = prf_gross_tcv * sub_ratio if (prf_gross_tcv is not None and sub_ratio is not None) else None
    results.append(fml(
        "Gross Subsumed Renewal TCV", "Subsumed_Renewal_TCV__c",
        f"Total_Price__c × (RevSubTCV/RevGrossTCV) = × {sub_ratio:.4f}" if sub_ratio else "ratio unavailable",
        bli.get("Subsumed_Renewal_TCV__c"), expected_sub_tcv
    ))

    # Net = Gross for PRF
    for fname, api in [
        ("Net TCV Amount", "Net_TCV_Amount__c"),
        ("Net New/Expansion TCV", "Net_New_Expansion_TCV__c"),
        ("Net Subsumed Renewal TCV", "Net_Subsumed_Renewal_TCV__c"),
    ]:
        gross_api = api.replace("Net_", "").replace("_Amount__c", "_Amount__c").replace("_TCV__c", "_TCV__c")
        gross_key = api.replace("Net_TCV_Amount__c", "Total_Price__c").replace("Net_", "")
        # Map net → gross field
        gross_map = {
            "Net_TCV_Amount__c": "Total_Price__c",
            "Net_New_Expansion_TCV__c": "New_Expansion_TCV__c",
            "Net_Subsumed_Renewal_TCV__c": "Subsumed_Renewal_TCV__c",
        }
        gross_val = safe_float(bli.get(gross_map.get(api, "")))
        results.append(fml(fname, api, "Net = Gross (PRF — no rebate)", bli.get(api), gross_val))

    # Gross ACV = PRF Gross TCV × (Rev Gross ACV / Rev TCV)
    expected_acv = prf_gross_tcv * acv_ratio if (prf_gross_tcv is not None and acv_ratio is not None) else None
    results.append(fml(
        "Gross ACV Amount", "Gross_ACV_Amount__c",
        f"Total_Price__c × (RevGrossACV/RevGrossTCV) = × {acv_ratio:.4f}" if acv_ratio else "ratio unavailable",
        bli.get("Gross_ACV_Amount__c"), expected_acv
    ))

    prf_gross_acv = safe_float(bli.get("Gross_ACV_Amount__c"))
    prf_total_acv = rev_gross_acv + (prf_gross_acv or 0)

    exp_acv_ratio = safe_div(rev_gross_exp_acv, rev_gross_acv)
    sub_acv_ratio = safe_div(rev_gross_sub_acv, rev_gross_acv)

    results.append(fml(
        "Gross New/Expansion ACV", "Gross_New_Expansion_ACV__c",
        f"Gross_ACV_Amount__c × (RevNewExpACV/RevGrossACV)",
        bli.get("Gross_New_Expansion_ACV__c"),
        prf_gross_acv * exp_acv_ratio if (prf_gross_acv is not None and exp_acv_ratio is not None) else None
    ))
    results.append(fml(
        "Gross Subsumed Renewal ACV", "Gross_Subsumed_Renewal_ACV__c",
        f"Gross_ACV_Amount__c × (RevSubACV/RevGrossACV)",
        bli.get("Gross_Subsumed_Renewal_ACV__c"),
        prf_gross_acv * sub_acv_ratio if (prf_gross_acv is not None and sub_acv_ratio is not None) else None
    ))

    # Net ACV = Gross ACV for PRF
    for fname, api, gross_api in [
        ("Net ACV Amount", "Net_ACV_Amount__c", "Gross_ACV_Amount__c"),
        ("Net New/Expansion ACV", "Net_New_Expansion_ACV__c", "Gross_New_Expansion_ACV__c"),
        ("Net Subsumed Renewal ACV", "Net_Subsumed_Renewal_ACV__c", "Gross_Subsumed_Renewal_ACV__c"),
    ]:
        results.append(fml(fname, api, "Net = Gross (PRF — no rebate)", bli.get(api), safe_float(bli.get(gross_api))))

    return results


def compare_distributor_fee_bli(bli: dict, all_rev_blis: list[dict]) -> list[dict]:
    """Distributor Fee BLI: Gross = SUM(Revenue Gross) × (Rebate% × -0.01)."""
    results = []
    rebate = safe_float(bli.get("Rebate__c")) or 0.0
    dist_factor = rebate * -0.01

    rev_sums = {
        "Total_Price__c": sum(safe_float(b.get("Total_Price__c")) or 0 for b in all_rev_blis),
        "New_Expansion_TCV__c": sum(safe_float(b.get("New_Expansion_TCV__c")) or 0 for b in all_rev_blis),
        "Subsumed_Renewal_TCV__c": sum(safe_float(b.get("Subsumed_Renewal_TCV__c")) or 0 for b in all_rev_blis),
        "Gross_ACV_Amount__c": sum(safe_float(b.get("Gross_ACV_Amount__c")) or 0 for b in all_rev_blis),
        "Gross_New_Expansion_ACV__c": sum(safe_float(b.get("Gross_New_Expansion_ACV__c")) or 0 for b in all_rev_blis),
        "Gross_Subsumed_Renewal_ACV__c": sum(safe_float(b.get("Gross_Subsumed_Renewal_ACV__c")) or 0 for b in all_rev_blis),
    }

    checks = [
        ("Gross TCV Amount", "Total_Price__c"),
        ("Gross New/Expansion TCV", "New_Expansion_TCV__c"),
        ("Gross Subsumed Renewal TCV", "Subsumed_Renewal_TCV__c"),
        ("Gross ACV Amount", "Gross_ACV_Amount__c"),
        ("Gross New/Expansion ACV", "Gross_New_Expansion_ACV__c"),
        ("Gross Subsumed Renewal ACV", "Gross_Subsumed_Renewal_ACV__c"),
    ]
    for fname, api in checks:
        expected = rev_sums[api] * dist_factor
        formula = f"SUM(Revenue BLI {api}) × (Rebate% × -0.01) = {rev_sums[api]:.2f} × {dist_factor:.4f}"
        status, note = compare_vals(bli.get(api), expected)
        results.append(row(fname, api, "Formula", formula, bli.get(api), expected, status, note))

    # Net values not calculated for Distributor Fee
    net_fields = [
        ("Net TCV Amount", "Net_TCV_Amount__c"),
        ("Net New/Expansion TCV", "Net_New_Expansion_TCV__c"),
        ("Net Subsumed Renewal TCV", "Net_Subsumed_Renewal_TCV__c"),
        ("Net ACV Amount", "Net_ACV_Amount__c"),
        ("Net New/Expansion ACV", "Net_New_Expansion_ACV__c"),
        ("Net Subsumed Renewal ACV", "Net_Subsumed_Renewal_ACV__c"),
    ]
    for fname, api in net_fields:
        results.append(row(fname, api, "NA", "Net values not calculated for Distributor Fee",
                           bli.get(api), "N/A", "NA", "Not applicable for Distributor Fee BLI"))

    return results


def compare_debooking_bli(bli: dict, oi: Optional[dict], oli: Optional[dict],
                          opp: Optional[dict]) -> list[dict]:
    """Debooking BLI: negative net factor; source depends on Amount vs Line Based."""
    results = []
    rebate = safe_float(bli.get("Rebate__c")) or 0.0
    net_factor = (100 - rebate) * -0.01
    bli_type = (bli.get("Type__c") or "").lower()
    is_line_based = "line" in bli_type

    def src_or_note(fname, api, sf_val, oli_val, opp_val):
        if is_line_based:
            expected = oli_val
            formula = f"OLI.{api} (Line Based)"
        else:
            expected = opp_val
            formula = f"Debook_Opp field (Amount Based)"
        if expected is None:
            return row(fname, api, "Source", formula, sf_val, None, "ERROR",
                       "Source record not linked or field missing")
        status, note = compare_vals(sf_val, expected)
        return row(fname, api, "Source", formula, sf_val, expected, status, note)

    results.append(src_or_note(
        "Gross TCV Amount", "Total_Price__c",
        bli.get("Total_Price__c"),
        safe_float(oli.get("TotalPrice") if oli else None),
        safe_float(opp.get("Amount") if opp else None),
    ))
    results.append(src_or_note(
        "Gross New/Expansion TCV", "New_Expansion_TCV__c",
        bli.get("New_Expansion_TCV__c"),
        safe_float(oli.get("New_Expansion_TCV__c") if oli else None),
        safe_float(opp.get("New_Expansion_TCV__c") if opp else None),
    ))
    results.append(src_or_note(
        "Gross Subsumed Renewal TCV", "Subsumed_Renewal_TCV__c",
        bli.get("Subsumed_Renewal_TCV__c"),
        safe_float(oli.get("Subsumed_Renewal_TCV__c") if oli else None),
        safe_float(opp.get("Renewal_Subsumed_TCV__c") if opp else None),
    ))

    gross_tcv = safe_float(bli.get("Total_Price__c"))
    gross_exp_tcv = safe_float(bli.get("New_Expansion_TCV__c"))
    gross_sub_tcv = safe_float(bli.get("Subsumed_Renewal_TCV__c"))

    for fname, api, g_val in [
        ("Net TCV Amount", "Net_TCV_Amount__c", gross_tcv),
        ("Net New/Expansion TCV", "Net_New_Expansion_TCV__c", gross_exp_tcv),
        ("Net Subsumed Renewal TCV", "Net_Subsumed_Renewal_TCV__c", gross_sub_tcv),
    ]:
        formula = f"Gross × ((100 - {rebate}) × -0.01) = × {net_factor:.4f}"
        status, note = compare_vals(bli.get(api), g_val * net_factor if g_val is not None else None)
        results.append(row(fname, api, "Formula", formula, bli.get(api),
                           g_val * net_factor if g_val is not None else None, status, note))

    results.append(src_or_note(
        "Gross ACV Amount", "Gross_ACV_Amount__c",
        bli.get("Gross_ACV_Amount__c"),
        safe_float(oli.get("ACV_Amount__c") if oli else None),
        safe_float(opp.get("ACV_Amount__c") if opp else None),
    ))
    results.append(src_or_note(
        "Gross New/Expansion ACV", "Gross_New_Expansion_ACV__c",
        bli.get("Gross_New_Expansion_ACV__c"),
        safe_float(oli.get("New_Expansion_ACV__c") if oli else None),
        safe_float(opp.get("New_Expansion_ACV__c") if opp else None),
    ))
    results.append(src_or_note(
        "Gross Subsumed Renewal ACV", "Gross_Subsumed_Renewal_ACV__c",
        bli.get("Gross_Subsumed_Renewal_ACV__c"),
        safe_float(oli.get("Subsumed_Renewal_Amount__c") if oli else None),
        safe_float(opp.get("Renewal_ACV__c") if opp else None),
    ))

    gross_acv = safe_float(bli.get("Gross_ACV_Amount__c"))
    gross_exp_acv = safe_float(bli.get("Gross_New_Expansion_ACV__c"))
    gross_sub_acv = safe_float(bli.get("Gross_Subsumed_Renewal_ACV__c"))

    for fname, api, g_val in [
        ("Net ACV Amount", "Net_ACV_Amount__c", gross_acv),
        ("Net New/Expansion ACV", "Net_New_Expansion_ACV__c", gross_exp_acv),
        ("Net Subsumed Renewal ACV", "Net_Subsumed_Renewal_ACV__c", gross_sub_acv),
    ]:
        formula = f"Gross × {net_factor:.4f}"
        status, note = compare_vals(bli.get(api), g_val * net_factor if g_val is not None else None)
        results.append(row(fname, api, "Formula", formula, bli.get(api),
                           g_val * net_factor if g_val is not None else None, status, note))

    return results


def compare_booking_header(booking: dict, blis: list[dict]) -> list[dict]:
    """Compare Booking header roll-up fields against SUM of BLI fields (Revenue + PRF only).
    Distributor Fee BLIs carry negative Gross values and are excluded from header roll-ups.
    """
    eligible = [b for b in blis if (b.get("Type__c") or "").strip() in ("Revenue", "PRF")]
    results = []
    for fname, booking_api, bli_api in BOOKING_HEADER_CHECKS:
        sf_val = booking.get(booking_api)
        expected = sum(safe_float(b.get(bli_api)) or 0.0 for b in eligible)
        formula = f"SUM(BLI.{bli_api} WHERE Type IN (Revenue, PRF))"
        status, note = compare_vals(sf_val, expected)
        results.append(row(fname, booking_api, "Formula", formula, sf_val, expected, status, note))
    return results


def compare_bli(bli: dict, data: dict) -> list[dict]:
    """Route BLI to the right comparator based on Type__c."""
    bli_type = (bli.get("Type__c") or "").strip()

    # Resolve linked objects
    oi_id = bli.get("OrderProduct__c")
    oi = data["oi_map"].get(oi_id) if oi_id else None
    oli_id = oi.get("oliID__c") if oi else None
    if oli_id:
        oli = data["oli_map"].get(oli_id)
    else:
        # Fallback: match via SBQQ__QuoteLine__c when oliID__c is not populated
        ql_id = oi.get("SBQQ__QuoteLine__c") if oi else None
        oli = data["ql_to_oli_map"].get(ql_id) if ql_id else None
    opp = next(iter(data["opp_map"].values()), None)

    # Revenue BLIs from the same booking (for PRF/DistFee ratio calculations)
    rev_blis = [b for b in data["blis"] if (b.get("Type__c") or "").strip() == "Revenue"]

    # Distributor Fee BLI rebate — Revenue BLI Net fields are reduced by this %
    dist_fee_blis = [b for b in data["blis"] if "distributor" in (b.get("Type__c") or "").lower()]
    dist_rebate = safe_float((dist_fee_blis[0].get("Rebate__c") if dist_fee_blis else None)) or 0.0

    t = bli_type.lower()
    if t == "revenue":
        return compare_revenue_bli(bli, oi, oli, dist_rebate)
    elif t == "prf":
        return compare_prf_bli(bli, rev_blis)
    elif "distributor" in t or "dist" in t:
        return compare_distributor_fee_bli(bli, rev_blis)
    elif "debook" in t or "return" in t or "refund" in t or "amount based" in t or "line based" in t:
        return compare_debooking_bli(bli, oi, oli, opp)
    else:
        return [row("(All fields)", "—", "UNKNOWN", f"Unknown BLI Type: {bli_type}",
                    "—", None, "ERROR", f"No comparator implemented for type '{bli_type}'")]


# ── Excel output ──────────────────────────────────────────────────────────────────
STATUS_FILL = {"PASS": FILL_PASS, "FAIL": FILL_FAIL, "NA": FILL_NA,
               "SKIP": FILL_SKIP, "ERROR": FILL_ERROR}

COLS = ["Field Name", "API Name", "Type", "SF Value", "Expected Value", "Status", "Note", "Formula"]


def autosize(ws):
    for col in ws.columns:
        w = max((len(str(c.value or "")) for c in col), default=10)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(w + 2, 55)


def write_bli_sheet(ws, results: list[dict], verbose: bool) -> dict:
    ws.append(COLS)
    for cell in ws[1]:
        cell.fill = FILL_HDR
        cell.font = WHITE_FONT
        cell.alignment = Alignment(horizontal="center")

    stats = {"PASS": 0, "FAIL": 0, "NA": 0, "SKIP": 0, "ERROR": 0}
    for r in results:
        status = r["status"]
        row_data = [r["field_name"], r["api_name"], r["validation_type"],
                    r["sf_value"], r["expected_value"], status, r["note"], r["formula"]]
        ws.append(row_data)
        fill = STATUS_FILL.get(status, FILL_ERROR)
        for cell in ws[ws.max_row]:
            cell.fill = fill
        stats[status] = stats.get(status, 0) + 1

    autosize(ws)
    comp = stats["PASS"] + stats["FAIL"]
    rate = (stats["PASS"] / comp * 100) if comp else 0.0
    return stats, comp, rate


def write_excel(all_order_results: list[tuple], sandbox: str, output_path: str, verbose: bool) -> dict:
    """Write a single workbook for one or more orders.
    all_order_results: list of (order_number, booking, header_results, bli_results)
    """
    multi = len(all_order_results) > 1
    wb = openpyxl.Workbook()
    ws_sum = wb.active
    ws_sum.title = "Summary"

    order_labels = ", ".join(r[0] for r in all_order_results)
    ws_sum.append(["Bookings Calculation Comparison Report"])
    ws_sum.append([f"Order(s): {order_labels}"])
    ws_sum.append([f"Sandbox: {sandbox}"])
    ws_sum.append([f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])
    ws_sum.append([])
    ws_sum.append(["Order", "Booking", "Section", "Type", "PASS", "FAIL", "NA", "SKIP", "ERROR", "Comparable", "Match %"])
    for cell in ws_sum[6]:
        cell.fill = FILL_HDR
        cell.font = WHITE_FONT

    grand = {"PASS": 0, "FAIL": 0, "NA": 0, "SKIP": 0, "ERROR": 0}

    for order_number, booking, header_results, bli_results in all_order_results:
        booking_name = booking.get("Name", "")
        # Sheet name prefix: only used when multiple orders to avoid name collisions
        pfx = f"{order_number[:6]}-" if multi else ""

        # ── Booking Header sheet ──────────────────────────────────────────────────
        hdr_title = f"{pfx}Booking Header"[:31]
        ws_hdr = wb.create_sheet(hdr_title)
        ws_hdr.append([f"Order: {order_number}", f"Booking: {booking_name}", "Booking Header Roll-up Field Validation"])
        for cell in ws_hdr[1]:
            cell.fill = FILL_HDR
            cell.font = WHITE_FONT
        ws_hdr.append([])
        hdr_stats, hdr_comp, hdr_rate = write_bli_sheet(ws_hdr, header_results, verbose)
        ws_sum.append([order_number, booking_name, "Booking Header", "Header Roll-up",
                       hdr_stats["PASS"], hdr_stats["FAIL"], hdr_stats["NA"],
                       hdr_stats["SKIP"], hdr_stats["ERROR"], hdr_comp, f"{hdr_rate:.1f}%"])
        for k in grand:
            grand[k] += hdr_stats.get(k, 0)

        # ── BLI sheets ────────────────────────────────────────────────────────────
        for bli_name, bli_type, results in bli_results:
            sheet_title = f"{pfx}{bli_name} ({bli_type})"[:31]
            ws = wb.create_sheet(sheet_title)
            ws.append([f"Order: {order_number}", f"BLI: {bli_name}", f"Type: {bli_type}"])
            for cell in ws[1]:
                cell.fill = FILL_SUBHDR
                cell.font = WHITE_FONT
            ws.append([])
            stats, comp, rate = write_bli_sheet(ws, results, verbose)
            ws_sum.append([order_number, booking_name, bli_name, bli_type,
                           stats["PASS"], stats["FAIL"], stats["NA"],
                           stats["SKIP"], stats["ERROR"], comp, f"{rate:.1f}%"])
            for k in grand:
                grand[k] += stats.get(k, 0)

        # Spacer row between orders in summary
        if multi:
            ws_sum.append([])

    all_comp = grand["PASS"] + grand["FAIL"]
    overall = (grand["PASS"] / all_comp * 100) if all_comp else 0.0
    ws_sum.append(["TOTAL", "", "", "", grand["PASS"], grand["FAIL"], grand["NA"],
                   grand["SKIP"], grand["ERROR"], all_comp, f"{overall:.1f}%"])
    autosize(ws_sum)

    wb.save(output_path)
    return {"pass": grand["PASS"], "fail": grand["FAIL"], "total": all_comp, "rate": overall}


# ── Main ──────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order-number", required=True,
                    help="Single order number or comma-separated list (e.g. 130593,130596)")
    ap.add_argument("--sandbox", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    alias = sf_alias(args.sandbox)
    order_numbers = [o.strip() for o in args.order_number.split(",") if o.strip()]

    # ── Process each order ───────────────────────────────────────────────────────
    all_order_results = []   # (order_number, booking, header_results, bli_results)
    order_stats = []

    for order_number in order_numbers:
        print(f"\nProcessing Order: {order_number} | Sandbox: {args.sandbox}")
        try:
            data = fetch_all_data(order_number, alias)
        except (ValueError, RuntimeError) as exc:
            print(f"  [ERROR] {exc}")
            continue

        booking = data["booking"]
        blis = data["blis"]
        print(f"  Booking: {booking.get('Name', '?')} | {len(blis)} BLI(s)")
        for b in blis:
            print(f"    BLI: {b.get('Name', '?')} | Type: {b.get('Type__c', '?')} | Rebate: {b.get('Rebate__c', 0)}%")

        header_results = compare_booking_header(booking, blis)
        bli_results = []
        for bli in blis:
            bli_name = bli.get("Name", bli["Id"])
            bli_type = bli.get("Type__c", "Unknown")
            results = compare_bli(bli, data)
            bli_results.append((bli_name, bli_type, results))

        all_order_results.append((order_number, booking, header_results, bli_results))

        # Per-order stats for console summary
        hdr_comp = sum(1 for r in header_results if r["status"] in ("PASS", "FAIL"))
        hdr_pass = sum(1 for r in header_results if r["status"] == "PASS")
        order_stats.append((order_number, booking.get("Name", "?"), header_results, bli_results))

    if not all_order_results:
        print("\n[ERROR] No orders could be processed. Exiting.")
        sys.exit(1)

    # ── Write single Excel file ──────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if len(order_numbers) == 1:
        order_label = order_numbers[0].replace("/", "-")
    elif len(order_numbers) <= 3:
        order_label = "_".join(o.replace("/", "-") for o in order_numbers)
    else:
        order_label = f"{len(order_numbers)}orders"

    out_path = os.path.join(args.output_dir,
                            f"bookings_comparison_{args.sandbox}_{order_label}_{ts}.xlsx")
    stats = write_excel(all_order_results, args.sandbox, out_path, args.verbose)

    # ── Console summary ──────────────────────────────────────────────────────────
    print("\n\nBookings Calculation Comparison Complete!")
    print("==========================================")
    print(f"Sandbox: {args.sandbox} | {len(all_order_results)} order(s) processed")
    print()
    for order_number, booking_name, header_results, bli_results in order_stats:
        print(f"Order: {order_number} | Booking: {booking_name}")
        hdr_comp = sum(1 for r in header_results if r["status"] in ("PASS", "FAIL"))
        hdr_pass = sum(1 for r in header_results if r["status"] == "PASS")
        hdr_rate = (hdr_pass / hdr_comp * 100) if hdr_comp else 0.0
        print(f"  Booking Header (Roll-up): {hdr_pass}/{hdr_comp} fields match ({hdr_rate:.1f}%)")
        for bli_name, bli_type, results in bli_results:
            comp = sum(1 for r in results if r["status"] in ("PASS", "FAIL"))
            passed = sum(1 for r in results if r["status"] == "PASS")
            rate = (passed / comp * 100) if comp else 0.0
            print(f"  {bli_name} ({bli_type}): {passed}/{comp} fields match ({rate:.1f}%)")
        print()
    print("==========================================")
    print(f"Excel Report: {out_path}")
    print("==========================================")

    print(json.dumps({"orders": order_numbers, **stats}), file=sys.stderr)


if __name__ == "__main__":
    main()
