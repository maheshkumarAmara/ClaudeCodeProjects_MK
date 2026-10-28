"""Date arithmetic and expected-metric calculations (no Streamlit)."""

import calendar
from datetime import datetime, timedelta

def _parse_sf_datetime(value):
    """Parse a Salesforce CreatedDate/DateTime string (with time-of-day) into a
    naive datetime for minute-precision diffs. Returns None if unparseable."""
    if not value:
        return None
    try:
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        return datetime.fromisoformat(v).replace(tzinfo=None)
    except ValueError:
        return None


def compute_expected_metrics(order_rec, history_records, sc_records, orderitem_gate_records, mdt_records) -> dict:
    """Independently recompute the 8 Order_Success_Metrics__c Auto/Manual fields
    from raw data, mirroring OrderCreationMetricsClass.createOrderSuccessMatrix
    field-for-field. Returns a dict of field name -> 'Auto'/'Manual'/None."""
    expected = {
        "Order_Creation_Metrics__c":       "Manual",
        "Order_Booking_Metrics__c":        "Manual",
        "Booking_Creation_Metrics__c":     "Manual",
        "Stage_PO_Submission_Metrics__c":  None,
        "Order_Provisioning_Metrics__c":   None,
        "SC_creation_Metrics__c":          None,
        "CLI_creation_Metrics__c":         None,
        "Entitlement_Creation_Metrics__c": None,
    }

    # ── Order_control__mdt lookups ──────────────────────────────────────────
    automation_users = set()
    polaris_user = ""
    ship_booked_diff_minutes = None
    sc_cli_entitlement_diff_minutes = 10
    for m in mdt_records:
        dev_name = m.get("DeveloperName")
        val = (m.get("Value__c") or "").strip()
        if dev_name in ("OrderAPIUser", "OrderAutomationUser") and val:
            automation_users.add(val.lower())
        elif dev_name == "PolarisAPIUser":
            polaris_user = val
        elif dev_name == "OrderShipBookedTimeDiff" and val:
            try:
                ship_booked_diff_minutes = int(val)
            except ValueError:
                ship_booked_diff_minutes = None
        elif dev_name == "OrderSCCLIEntitlementTimeDiff" and val:
            try:
                sc_cli_entitlement_diff_minutes = int(val)
            except ValueError:
                sc_cli_entitlement_diff_minutes = 10

    order_type = order_rec.get("Type")
    created_by_name = ((order_rec.get("CreatedBy") or {}).get("Name") or "")
    auto_manual_booked = order_rec.get("Auto_Manual_Booked__c")
    stage_po = order_rec.get("Stage_PO__c")
    booking_status = order_rec.get("BookingStatus__c")
    order_status = order_rec.get("Order_Status__c")

    # ── Order_Creation_Metrics__c ───────────────────────────────────────────
    if order_type == "Revenue":
        expected["Order_Creation_Metrics__c"] = "Auto" if created_by_name.lower() in automation_users else "Manual"

    # ── Stage_PO_Submission_Metrics__c ──────────────────────────────────────
    if stage_po is not None:
        expected["Stage_PO_Submission_Metrics__c"] = "Auto" if created_by_name.lower() in automation_users else "Manual"

    # ── Order_Booking_Metrics__c ────────────────────────────────────────────
    if auto_manual_booked == "Auto Booked":
        expected["Order_Booking_Metrics__c"] = "Auto"

    # ── OrderHistory map keyed by OrderId+Field+NewValue → list[rows] ASC ───
    history_map = {}
    for h in history_records:
        key = f"{h.get('OrderId')}{h.get('Field')}{h.get('NewValue')}"
        history_map.setdefault(key, []).append(h)

    order_id = order_rec.get("Id")

    # ── Order_Provisioning_Metrics__c (two-phase) ───────────────────────────
    completed_key = f"{order_id}Polaris_Fulfillment_Status__cCompleted"
    error_key = f"{order_id}Polaris_Fulfillment_Status__cError with Fulfillment"
    resync_key = f"{order_id}Polaris_Fulfillment_Status__cResync Dates Requested"
    if completed_key in history_map:
        provisioning_user = ((history_map[completed_key][0].get("CreatedBy") or {}).get("Name") or "")
        expected["Order_Provisioning_Metrics__c"] = (
            "Auto" if (provisioning_user.lower() in automation_users
                       or provisioning_user.lower() == polaris_user.lower())
            else "Manual"
        )
    if error_key in history_map:
        first_error_date = _parse_sf_datetime(history_map[error_key][0].get("CreatedDate"))
        has_error_before_resync = (
            resync_key not in history_map
            or (first_error_date is not None
                and (_parse_sf_datetime(history_map[resync_key][0].get("CreatedDate")) is None
                     or first_error_date < _parse_sf_datetime(history_map[resync_key][0].get("CreatedDate"))))
        )
        if has_error_before_resync:
            expected["Order_Provisioning_Metrics__c"] = "Manual"

    # ── Booking_Creation_Metrics__c ──────────────────────────────────────────
    booking_comp_key = f"{order_id}BookingStatus__cCompleted"
    accept_key = f"{order_id}Order_Status__cOrder Accepted"
    ship_key = f"{order_id}Order_Status__cShipped"

    # Apex's orderHistoryMap (used for these 3 dates) is a single-value map built by
    # repeated .put() while iterating CreatedDate ASC, so it ends up holding the LAST
    # (most recent) row per key — unlike orderProvisioningHistoryMap above, which keeps
    # the full list and reads [0] (earliest). Mirror that here with [-1].
    booking_date = (_parse_sf_datetime(history_map[booking_comp_key][-1].get("CreatedDate"))
                    if booking_status == "Completed" and booking_comp_key in history_map else None)
    shipping_date = (_parse_sf_datetime(history_map[ship_key][-1].get("CreatedDate"))
                      if order_status == "Shipped" and ship_key in history_map else None)
    order_accept_date = (_parse_sf_datetime(history_map[accept_key][-1].get("CreatedDate"))
                         if accept_key in history_map else None)

    if booking_date is not None and order_accept_date is not None and ship_booked_diff_minutes is not None:
        minutes_diff = (booking_date - order_accept_date).total_seconds() / 60
        expected["Booking_Creation_Metrics__c"] = "Manual"
        if 0 <= minutes_diff <= ship_booked_diff_minutes:
            expected["Booking_Creation_Metrics__c"] = "Auto"

    # ── SC/CLI/Entitlement gating from orderitem_gate_records ───────────────
    # has_cli_gap/has_entitlement_gap are computed unconditionally (any() over an
    # empty list is False), mirroring Apex's orderItemCLIMap/orderItemEntitlementMap
    # .containsKey() being False for orders with no matching OrderItem gate rows.
    has_cli_gap = any(r.get("SBQQSC__ContractLineItem__c") is None for r in orderitem_gate_records)
    has_entitlement_gap = any(
        (r.get("Entitlements__r") or {}).get("totalSize", 0) == 0 for r in orderitem_gate_records
    )

    if orderitem_gate_records:
        expected["SC_creation_Metrics__c"] = "Manual"
        expected["CLI_creation_Metrics__c"] = "Manual"
        expected["Entitlement_Creation_Metrics__c"] = "Manual"

    # Independent, non-nested check — in Apex this is a separate top-level `if`
    # (sibling to `if(orderProductOrderSet.contains(o.id))` above), so an order
    # without matching OrderItem gate rows can still be promoted to 'Auto' here
    # if a qualifying ServiceContract exists.
    if sc_records and shipping_date is not None:
        sc_created = _parse_sf_datetime(sc_records[0].get("CreatedDate"))
        if sc_created is not None:
            sc_diff_minutes = (sc_created - shipping_date).total_seconds() / 60
            if 0 <= sc_diff_minutes <= sc_cli_entitlement_diff_minutes:
                expected["SC_creation_Metrics__c"] = "Auto"
                expected["CLI_creation_Metrics__c"] = "Manual" if has_cli_gap else "Auto"
                expected["Entitlement_Creation_Metrics__c"] = "Manual" if has_entitlement_gap else "Auto"

    return expected


def fmt_amount(val):
    return f"{val:,.2f}" if val is not None else "(blank)"


def add_days(date_str, days):
    if not date_str:
        return ""
    try:
        return (datetime.strptime(date_str[:10], "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def parse_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        return None


def add_months(date_str, months):
    if not date_str or months is None:
        return ""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        m  = dt.month - 1 + int(months)
        y  = dt.year + m // 12
        m  = m % 12 + 1
        d  = min(dt.day, calendar.monthrange(y, m)[1])
        return datetime(y, m, d).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""


def end_of_month(date_str):
    if not date_str:
        return ""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        last_day = calendar.monthrange(dt.year, dt.month)[1]
        return dt.replace(day=last_day).strftime("%Y-%m-%d")
    except ValueError:
        return ""
