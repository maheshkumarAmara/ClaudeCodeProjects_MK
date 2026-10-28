"""Booking Header / Booking Line Item comparison against formula-calculated values (ported from the Bookings-metrics-comparision skill). No Streamlit."""

from ov.sf_client import run_sf_query

BK_NUMERIC_TOL = 0.10

BK_BOOKING_FIELDS = [
    "Id", "Name", "Order__c", "Opportunity__c", "Status__c",
    "Order_Type__c", "Opportunity_Type__c",
    "Gross_Bookings_Total__c", "Gross_ACV_Total__c",
    "New_Expansion_TCV__c", "Gross_New_Expansion_ACV__c",
    "Subsumed_Renewal_TCV__c", "Gross_Subsumed_Renewal_ACV__c",
    "Net_Bookings_Total__c", "Net_ACV_Total__c",
    "Net_New_Expansion_TCV__c", "Net_New_Expansion_ACV__c",
    "Net_Subsumed_Renewal_TCV__c", "Net_Subsumed_Renewal_ACV__c",
]

BK_BOOKING_HEADER_CHECKS = [
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

BK_BLI_FIELDS = [
    "Id", "Name", "Booking__c", "OrderProduct__c", "CCR__c", "Type__c", "Rebate__c",
    "Total_Price__c", "New_Expansion_TCV__c", "Subsumed_Renewal_TCV__c",
    "Net_TCV_Amount__c", "Net_New_Expansion_TCV__c", "Net_Subsumed_Renewal_TCV__c",
    "Gross_ACV_Amount__c", "Gross_New_Expansion_ACV__c", "Gross_Subsumed_Renewal_ACV__c",
    "Net_ACV_Amount__c", "Net_New_Expansion_ACV__c", "Net_Subsumed_Renewal_ACV__c",
    "PromoDiscTCV__c", "Oppty_Trade_Up_Discount__c", "Prepayment_Credit__c",
    "Partner_Referral_Fee__c", "Product_Name__c", "Product_Code__c",
    "Commission_Impact__c", "Impacts_Gross_Bookings__c", "Impacts_Net_Bookings__c",
]

BK_ORDER_ITEM_FIELDS = [
    "Id", "OrderId", "Quantity", "TotalPrice", "UnitPrice", "oliID__c",
    "SBQQ__QuoteLine__c", "PromoDiscTCV__c", "Oppty_Trade_Up_Discount__c",
    "Prepaid_Credit__c", "SBQQ__ProrateMultiplier__c", "Product2Id",
    "ProductID__c", "Product_Name__c",
]

BK_OLI_FIELDS = [
    "Id", "TotalPrice", "Quantity", "ACV_Amount__c", "New_Expansion_TCV__c",
    "Subsumed_Renewal_TCV__c", "New_Expansion_ACV__c", "Subsumed_Renewal_Amount__c",
    "PromoDiscTCV__c", "Oppty_Trade_Up_Discount__c", "Prepayment_Credit__c",
    "OpportunityId", "Product2Id", "SBQQ__QuoteLine__c",
]

BK_OPP_FIELDS = [
    "Id", "Name", "Amount", "ACV_Amount__c", "New_Expansion_ACV__c",
    "New_Expansion_TCV__c", "Renewal_Subsumed_TCV__c", "Renewal_ACV__c",
    "Referral_Fee_Amount__c", "CCR_Type__c",
]


def bk_safe_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def bk_safe_div(a, b):
    if b is None or b == 0 or a is None:
        return None
    return a / b


def bk_soql_in(fields, sobject, in_field, ids, alias):
    """Batch an IN(...) query at 200 ids/batch using the app's own run_sf_query."""
    out = []
    field_list = ", ".join(fields)
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        quoted = ", ".join(f"'{_id}'" for _id in batch)
        soql = f"SELECT {field_list} FROM {sobject} WHERE {in_field} IN ({quoted})"
        try:
            result = run_sf_query(alias, soql)
        except Exception:
            continue
        out.extend(result.get("records", []))
    return out


def bk_fetch_booking_data(order_id, alias):
    """Fetch Booking__c → Booking_Line_Item__c → OrderItem → OpportunityLineItem/Opportunity
    chain for a given Order Id, using entirely independent queries (no reliance on any
    data already prefetched elsewhere in the app)."""
    bk_fields = ", ".join(BK_BOOKING_FIELDS)
    bookings = run_sf_query(
        alias, f"SELECT {bk_fields} FROM Booking__c WHERE Order__c = '{order_id}'"
    ).get("records", [])
    if not bookings:
        return None

    booking = bookings[0]
    bli_fields = ", ".join(BK_BLI_FIELDS)
    blis = run_sf_query(
        alias, f"SELECT {bli_fields} FROM Booking_Line_Item__c WHERE Booking__c = '{booking['Id']}'"
    ).get("records", [])

    op_ids = [b["OrderProduct__c"] for b in blis if b.get("OrderProduct__c")]
    oi_map = {}
    if op_ids:
        ois = bk_soql_in(BK_ORDER_ITEM_FIELDS, "OrderItem", "Id", op_ids, alias)
        oi_map = {oi["Id"]: oi for oi in ois}

    oli_ids = [oi["oliID__c"] for oi in oi_map.values() if oi.get("oliID__c")]
    oli_map = {}
    ql_to_oli_map = {}
    if oli_ids:
        olis = bk_soql_in(BK_OLI_FIELDS, "OpportunityLineItem", "Id", oli_ids, alias)
        oli_map = {oli["Id"]: oli for oli in olis}

    ql_ids = [oi["SBQQ__QuoteLine__c"] for oi in oi_map.values()
              if not oi.get("oliID__c") and oi.get("SBQQ__QuoteLine__c")]
    if ql_ids:
        olis_fb = bk_soql_in(BK_OLI_FIELDS, "OpportunityLineItem", "SBQQ__QuoteLine__c", ql_ids, alias)
        for oli in olis_fb:
            ql = oli.get("SBQQ__QuoteLine__c")
            if ql:
                ql_to_oli_map[ql] = oli
            oli_map[oli["Id"]] = oli

    opp_map = {}
    opp_id = booking.get("Opportunity__c")
    if opp_id:
        opps = bk_soql_in(BK_OPP_FIELDS, "Opportunity", "Id", [opp_id], alias)
        opp_map = {o["Id"]: o for o in opps}

    return {
        "booking": booking, "blis": blis, "oi_map": oi_map,
        "oli_map": oli_map, "ql_to_oli_map": ql_to_oli_map, "opp_map": opp_map,
    }


def bk_compare_vals(sf_val, expected, label=""):
    if expected is None:
        return "ERROR", f"Cannot calculate expected value{(' for ' + label) if label else ''}"
    sf_n = bk_safe_float(sf_val)
    ex_n = bk_safe_float(expected)
    if ex_n is not None:
        sf_num = sf_n if sf_n is not None else 0.0
        diff = abs(sf_num - ex_n)
        if diff <= BK_NUMERIC_TOL:
            note = "" if sf_n is not None else "(SF null treated as 0)"
            return "PASS", note
        sf_label = f"{sf_n:.4f}" if sf_n is not None else "null"
        return "FAIL", f"SF={sf_label}  Expected={ex_n:.4f}  Δ={diff:.4f}"
    sf_s = str(sf_val) if sf_val is not None else ""
    ex_s = str(expected)
    return ("PASS", "") if sf_s == ex_s else ("FAIL", f"SF='{sf_s}'  Expected='{ex_s}'")


def bk_row(fname, api, vtype, formula, sf_val, expected, status, note):
    return dict(field_name=fname, api_name=api, validation_type=vtype, formula=formula,
                sf_value=sf_val, expected_value=expected, status=status, note=note)


def bk_compare_revenue_bli(bli, oi, oli, dist_rebate=0.0):
    # Revenue BLIs inherit the rebate from the sibling Distributor Fee BLI (their own Rebate__c is null)
    rebate = bk_safe_float(bli.get("Rebate__c")) or dist_rebate
    net_factor = (100 - rebate) * 0.01
    results = []

    def src(fname, api, oli_api):
        sf_val = bli.get(api)
        if oli is None:
            status, note = "ERROR", "OLI not found"
            expected = None
        else:
            oli_val = bk_safe_float(oli.get(oli_api))
            expected = oli_val if oli_val is not None else 0.0
            status, note = bk_compare_vals(sf_val, expected, fname)
            if oli_val is None and status == "PASS":
                note = "(OLI field null, treated as 0)"
        results.append(bk_row(fname, api, "Source", f"OLI.{oli_api}", sf_val, expected, status, note))

    def fml(fname, api, base_api):
        sf_val = bli.get(api)
        base = bk_safe_float(bli.get(base_api))
        expected = base * net_factor if base is not None else None
        status, note = bk_compare_vals(sf_val, expected, fname)
        results.append(bk_row(fname, api, "Formula", f"{base_api} * ((100 - Rebate__c) * 0.01)",
                               sf_val, expected, status, note))

    src("Gross TCV Amount",            "Total_Price__c",              "TotalPrice")
    src("Gross New/Expansion TCV",     "New_Expansion_TCV__c",        "New_Expansion_TCV__c")
    src("Gross Subsumed Renewal TCV",  "Subsumed_Renewal_TCV__c",     "Subsumed_Renewal_TCV__c")
    fml("Net TCV Amount",              "Net_TCV_Amount__c",           "Total_Price__c")
    fml("Net New/Expansion TCV",       "Net_New_Expansion_TCV__c",    "New_Expansion_TCV__c")
    fml("Net Subsumed Renewal TCV",    "Net_Subsumed_Renewal_TCV__c", "Subsumed_Renewal_TCV__c")

    src("Gross ACV Amount",            "Gross_ACV_Amount__c",            "ACV_Amount__c")
    src("Gross New/Expansion ACV",     "Gross_New_Expansion_ACV__c",     "New_Expansion_ACV__c")
    src("Gross Subsumed Renewal ACV",  "Gross_Subsumed_Renewal_ACV__c",  "Subsumed_Renewal_Amount__c")
    fml("Net ACV Amount",              "Net_ACV_Amount__c",              "Gross_ACV_Amount__c")
    fml("Net New/Expansion ACV",       "Net_New_Expansion_ACV__c",       "Gross_New_Expansion_ACV__c")
    fml("Net Subsumed Renewal ACV",    "Net_Subsumed_Renewal_ACV__c",    "Gross_Subsumed_Renewal_ACV__c")

    def prorated(fname, api, oli_api):
        sf_val = bli.get(api)
        if oli is None or oi is None:
            status, note = "ERROR", "OLI/OI not linked"
            expected = None
        else:
            oli_val = bk_safe_float(oli.get(oli_api))
            oli_num = oli_val if oli_val is not None else 0.0
            oi_qty = bk_safe_float(oi.get("Quantity"))
            oli_qty = bk_safe_float(oli.get("Quantity"))
            ratio = bk_safe_div(oi_qty, oli_qty)
            expected = oli_num * ratio if ratio is not None else 0.0
            status, note = bk_compare_vals(sf_val, expected, fname)
        results.append(bk_row(fname, api, "Formula",
                               f"OLI.{oli_api} * (OrderItem.Quantity / OLI.Quantity)",
                               sf_val, expected, status, note))

    prorated("Promo Discount TCV",     "PromoDiscTCV__c",             "PromoDiscTCV__c")
    prorated("Trade-up Credit TCV",    "Oppty_Trade_Up_Discount__c",  "Oppty_Trade_Up_Discount__c")
    prorated("Prepayment Credit TCV",  "Prepayment_Credit__c",        "Prepayment_Credit__c")

    return results


def bk_compare_prf_bli(bli, all_rev_blis):
    def rev_sum(api):
        return sum(bk_safe_float(b.get(api)) or 0.0 for b in all_rev_blis)

    results = []

    sf_val = bli.get("Total_Price__c")
    results.append(bk_row("Gross TCV Amount", "Total_Price__c", "Source",
                           "Referral_Fee_Amount__c from Opportunity (CCR Type=PRF)",
                           sf_val, "—", "NA", "Manual verification required"))

    def gross_na(fname, api):
        sf_val = bli.get(api)
        results.append(bk_row(fname, api, "Source",
                               "Proportional allocation from Revenue BLI/Opportunity ratios (BookingLineItemBatch.cls)",
                               sf_val, "—", "NA", "Manual verification required"))

    gross_na("Gross New/Expansion TCV",    "New_Expansion_TCV__c")
    gross_na("Gross Subsumed Renewal TCV", "Subsumed_Renewal_TCV__c")

    gross_map = {
        "Net TCV Amount":            ("Net_TCV_Amount__c",             "Total_Price__c"),
        "Net New/Expansion TCV":     ("Net_New_Expansion_TCV__c",      "New_Expansion_TCV__c"),
        "Net Subsumed Renewal TCV":  ("Net_Subsumed_Renewal_TCV__c",   "Subsumed_Renewal_TCV__c"),
        "Net ACV Amount":            ("Net_ACV_Amount__c",             "Gross_ACV_Amount__c"),
        "Net New/Expansion ACV":     ("Net_New_Expansion_ACV__c",      "Gross_New_Expansion_ACV__c"),
        "Net Subsumed Renewal ACV":  ("Net_Subsumed_Renewal_ACV__c",   "Gross_Subsumed_Renewal_ACV__c"),
    }

    def gross_eq_net(fname, api, gross_api):
        sf_val = bli.get(api)
        expected = bk_safe_float(bli.get(gross_api))
        status, note = bk_compare_vals(sf_val, expected, fname)
        results.append(bk_row(fname, api, "Source", gross_api, sf_val, expected, status, note))

    gross_eq_net("Net TCV Amount",           *gross_map["Net TCV Amount"])
    gross_eq_net("Net New/Expansion TCV",    *gross_map["Net New/Expansion TCV"])
    gross_eq_net("Net Subsumed Renewal TCV", *gross_map["Net Subsumed Renewal TCV"])

    oli_tcv = None
    ratio_acv = bk_safe_div(rev_sum("Gross_ACV_Amount__c"), oli_tcv)
    sf_val = bli.get("Gross_ACV_Amount__c")
    results.append(bk_row("Gross ACV Amount", "Gross_ACV_Amount__c", "Formula",
                           "Total_Price__c * (SUM Revenue BLI Gross ACV / OLI TCV Amount)",
                           sf_val, "—", "NA", "Requires OLI TCV Amount — manual verification"))

    gross_eq_net("Net ACV Amount",           *gross_map["Net ACV Amount"])
    gross_eq_net("Net New/Expansion ACV",    *gross_map["Net New/Expansion ACV"])
    gross_eq_net("Net Subsumed Renewal ACV", *gross_map["Net Subsumed Renewal ACV"])

    return results


def bk_compare_distributor_fee_bli(bli, all_rev_blis):
    rebate = bk_safe_float(bli.get("Rebate__c")) or 0.0
    factor = rebate * -0.01
    results = []

    def rev_sum(api):
        return sum(bk_safe_float(b.get(api)) or 0.0 for b in all_rev_blis)

    def gross_fml(fname, api, rev_api):
        sf_val = bli.get(api)
        base = rev_sum(rev_api)
        expected = base * factor
        status, note = bk_compare_vals(sf_val, expected, fname)
        results.append(bk_row(fname, api, "Formula", f"SUM(Revenue BLI {rev_api}) * (Rebate__c * -0.01)",
                               sf_val, expected, status, note))

    gross_fml("Gross TCV Amount",            "Total_Price__c",              "Total_Price__c")
    gross_fml("Gross New/Expansion TCV",     "New_Expansion_TCV__c",        "New_Expansion_TCV__c")
    gross_fml("Gross Subsumed Renewal TCV",  "Subsumed_Renewal_TCV__c",     "Subsumed_Renewal_TCV__c")
    gross_fml("Gross ACV Amount",            "Gross_ACV_Amount__c",         "Gross_ACV_Amount__c")
    gross_fml("Gross New/Expansion ACV",     "Gross_New_Expansion_ACV__c",  "Gross_New_Expansion_ACV__c")
    gross_fml("Gross Subsumed Renewal ACV",  "Gross_Subsumed_Renewal_ACV__c", "Gross_Subsumed_Renewal_ACV__c")

    for fname, api in [
        ("Net TCV Amount", "Net_TCV_Amount__c"),
        ("Net New/Expansion TCV", "Net_New_Expansion_TCV__c"),
        ("Net Subsumed Renewal TCV", "Net_Subsumed_Renewal_TCV__c"),
        ("Net ACV Amount", "Net_ACV_Amount__c"),
        ("Net New/Expansion ACV", "Net_New_Expansion_ACV__c"),
        ("Net Subsumed Renewal ACV", "Net_Subsumed_Renewal_ACV__c"),
    ]:
        sf_val = bli.get(api)
        results.append(bk_row(fname, api, "NA", "Not applicable for Distributor Fee BLI",
                               sf_val, "—", "NA", "Not applicable for Distributor Fee BLI"))

    return results


def bk_compare_debooking_bli(bli, oi, oli, opp):
    rebate = bk_safe_float(bli.get("Rebate__c")) or 0.0
    net_factor = (100 - rebate) * 0.01
    bli_type = (bli.get("Type__c") or "")
    is_line_based = "line" in bli_type.lower()
    results = []

    def src_or_note(fname, api, oli_api, opp_api):
        sf_val = bli.get(api)
        if is_line_based:
            raw = bk_safe_float(oli.get(oli_api)) if oli else None
            expected = -raw if raw is not None else None
            source_label = f"-1 * OLI.{oli_api} (Line Based)"
            if oli is None:
                status, note = "ERROR", "Linked OpportunityLineItem not found"
                results.append(bk_row(fname, api, "Source", source_label, sf_val, "—", status, note))
                return
        else:
            raw = bk_safe_float(opp.get(opp_api)) if opp else None
            expected = -raw if raw is not None else None
            source_label = f"-1 * Debook_Opp.{opp_api} (Amount Based)"
            if opp is None:
                status, note = "ERROR", "Linked Debooking Opportunity not found"
                results.append(bk_row(fname, api, "Source", source_label, sf_val, "—", status, note))
                return
        status, note = bk_compare_vals(sf_val, expected, fname)
        results.append(bk_row(fname, api, "Source", source_label, sf_val, expected, status, note))

    src_or_note("Gross TCV Amount",           "Total_Price__c",             "TotalPrice",               "Amount")
    src_or_note("Gross New/Expansion TCV",    "New_Expansion_TCV__c",       "New_Expansion_TCV__c",     "New_Expansion_TCV__c")
    src_or_note("Gross Subsumed Renewal TCV", "Subsumed_Renewal_TCV__c",    "Subsumed_Renewal_TCV__c",  "Renewal_Subsumed_TCV__c")

    def fml(fname, api, base_api):
        sf_val = bli.get(api)
        base = bk_safe_float(bli.get(base_api))
        expected = base * net_factor if base is not None else None
        status, note = bk_compare_vals(sf_val, expected, fname)
        results.append(bk_row(fname, api, "Formula", f"{base_api} * ((100 - Rebate__c) * 0.01)",
                               sf_val, expected, status, note))

    fml("Net TCV Amount",              "Net_TCV_Amount__c",           "Total_Price__c")
    fml("Net New/Expansion TCV",       "Net_New_Expansion_TCV__c",    "New_Expansion_TCV__c")
    fml("Net Subsumed Renewal TCV",    "Net_Subsumed_Renewal_TCV__c", "Subsumed_Renewal_TCV__c")

    src_or_note("Gross ACV Amount",           "Gross_ACV_Amount__c",           "ACV_Amount__c",              "ACV_Amount__c")
    src_or_note("Gross New/Expansion ACV",    "Gross_New_Expansion_ACV__c",    "New_Expansion_ACV__c",       "New_Expansion_ACV__c")
    src_or_note("Gross Subsumed Renewal ACV", "Gross_Subsumed_Renewal_ACV__c", "Subsumed_Renewal_Amount__c", "Renewal_Subsumed_ACV__c")

    fml("Net ACV Amount",              "Net_ACV_Amount__c",              "Gross_ACV_Amount__c")
    fml("Net New/Expansion ACV",       "Net_New_Expansion_ACV__c",       "Gross_New_Expansion_ACV__c")
    fml("Net Subsumed Renewal ACV",    "Net_Subsumed_Renewal_ACV__c",    "Gross_Subsumed_Renewal_ACV__c")

    return results


def bk_compare_booking_header(booking, blis):
    gross_eligible = [b for b in blis if b.get("Impacts_Gross_Bookings__c")]
    net_eligible = [b for b in blis if b.get("Impacts_Net_Bookings__c")]
    results = []
    for fname, booking_api, bli_api in BK_BOOKING_HEADER_CHECKS:
        sf_val = booking.get(booking_api)
        is_gross = fname.startswith("Gross")
        eligible = gross_eligible if is_gross else net_eligible
        flag_api = "Impacts_Gross_Bookings__c" if is_gross else "Impacts_Net_Bookings__c"
        expected = sum(bk_safe_float(b.get(bli_api)) or 0.0 for b in eligible)
        formula = f"SUM(BLI.{bli_api} WHERE {flag_api} = true)"
        status, note = bk_compare_vals(sf_val, expected)
        results.append(bk_row(fname, booking_api, "Formula", formula, sf_val, expected, status, note))
    return results


def bk_compare_bli(bli, data):
    bli_type = (bli.get("Type__c") or "").strip()
    oi_id = bli.get("OrderProduct__c")
    oi = data["oi_map"].get(oi_id) if oi_id else None
    oli_id = oi.get("oliID__c") if oi else None
    if oli_id:
        oli = data["oli_map"].get(oli_id)
    else:
        ql_id = oi.get("SBQQ__QuoteLine__c") if oi else None
        oli = data["ql_to_oli_map"].get(ql_id) if ql_id else None
    opp = next(iter(data["opp_map"].values()), None)
    rev_blis = [b for b in data["blis"] if (b.get("Type__c") or "").strip() == "Revenue"]
    dist_fee_blis = [b for b in data["blis"] if "distributor" in (b.get("Type__c") or "").lower()]
    dist_rebate = bk_safe_float(dist_fee_blis[0].get("Rebate__c") if dist_fee_blis else None) or 0.0

    t = bli_type.lower()
    if t == "revenue":
        return bk_compare_revenue_bli(bli, oi, oli, dist_rebate)
    elif t == "prf":
        return bk_compare_prf_bli(bli, rev_blis)
    elif "distributor" in t or "dist" in t:
        return bk_compare_distributor_fee_bli(bli, rev_blis)
    elif "debook" in t or "return" in t or "refund" in t or "amount based" in t or "line based" in t:
        return bk_compare_debooking_bli(bli, oi, oli, opp)
    else:
        return [bk_row("(All fields)", "—", "UNKNOWN", f"Unknown BLI Type: {bli_type}",
                        "—", None, "ERROR", f"No comparator implemented for type '{bli_type}'")]


def bk_status_to_row_status(status):
    """Map skill status (PASS/FAIL/NA/ERROR) → app row Status string."""
    if status == "PASS":
        return "✅ PASS"
    elif status == "FAIL":
        return "❌ FAIL"
    elif status == "NA":
        return "ℹ️ NA"
    else:
        return "ℹ️ ERROR"


def bk_rows_to_app_rows(bk_rows_list, prefix=""):
    """Convert a list of bk_row(...) dicts into the app's row schema."""
    out = []
    for r in bk_rows_list:
        expected = r["expected_value"]
        expected_str = "—" if expected is None else (
            f"{expected:.4f}" if isinstance(expected, float) else str(expected)
        )
        status_str = bk_status_to_row_status(r["status"])
        note = r.get("note") or ""
        out.append({
            "#": "—",
            "Validation": f"{prefix}{r['field_name']}",
            "Details": f"{r['validation_type']}: {r['formula']}" + (f" | {note}" if note else ""),
            "Expected": expected_str,
            "Actual": "—" if r["sf_value"] is None else r["sf_value"],
            "Status": status_str,
        })
    return out
