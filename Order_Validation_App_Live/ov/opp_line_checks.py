"""Opportunity Lineitem checks, ported from OpportunityLineItemTriggersHelper / OpportunityLineItemTriggerHandler
in the Salesforce repo, plus line consistency checks against the Quote Line and Order Product. No Streamlit.

Each check is one row, aggregated over all lines of the Order's Opportunity; the Details column names the lines
that fail. Rows use the same shape as ov.opp_header_checks so the tab, summary and downloads treat them alike.

Ported from Apex:
- Prod_Type__c / Support_type__c copy Product2 (updateProductType).
- Renewal_Timing__c on Renewal lines (populateRenewalTiming / getQuarter), replicated literally, including the
  Apex quirk that the year is only rolled back for a January close/renewal date.

Consistency checks (not Apex rules): TotalPrice = Quantity x UnitPrice; Quantity and Subscription Term equal the
Quote Line; Opportunity.Amount equals the sum of line totals; each Order Product links to a line and matches it.

Not ported:
- "You cannot update quote in stage 6 or above" (before insert/update/delete). It blocks a change as it happens,
  so a saved record cannot show it.
- The header roll-up of line amounts lives in ov.opp_header_checks (SAL25-145).
"""

from datetime import date, datetime, timedelta

from ov.opp_header_checks import _money, _row, _shown

AMOUNT_TOLERANCE = 0.01


def _label(line: dict) -> str:
    name = (line.get("Product2") or {}).get("Name") or "(no product)"
    return f"{name} [{str(line.get('Id') or '')[-6:]}]"


def _num(value):
    return float(value) if value is not None else None


def _parse_date(value):
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date() if value else None


def _fiscal_quarter(d: date) -> int:
    """OpportunityLineItemTriggersHelper.getQuarter: Feb-Apr Q1, May-Jul Q2, Aug-Oct Q3, else Q4."""
    if 2 <= d.month <= 4:
        return 1
    if 5 <= d.month <= 7:
        return 2
    if 8 <= d.month <= 10:
        return 3
    return 4


def expected_renewal_timing(close_date, renewal_due_date):
    """OpportunityLineItemTriggersHelper.populateRenewalTiming: 'On-Time' / 'Early' / 'Late'."""
    close = _parse_date(close_date)
    renewal = _parse_date(renewal_due_date)
    if close is None or renewal is None:
        return None
    renewal = renewal + timedelta(days=1)  # RNWL-223
    close_q, renewal_q = _fiscal_quarter(close), _fiscal_quarter(renewal)
    close_year, renewal_year = close.year % 100, renewal.year % 100
    if close_q == 4 and close.month == 1:
        close_year -= 1
    if renewal_q == 4 and renewal.month == 1:
        renewal_year -= 1
    if renewal_year == close_year:
        if renewal_q == close_q:
            return "On-Time"
        return "Early" if renewal_q > close_q else "Late"
    return "Early" if renewal_year > close_year else "Late"


def _line_check(name, lines, applies, is_bad, describe, error_msg, expected, ok_text):
    """One aggregated row: FAIL names every line for which is_bad(line) is true."""
    bad = [line for line in lines if is_bad(line)] if applies else []
    if bad:
        detail = "; ".join(f"{_label(line)}: {describe(line)}" for line in bad)
        actual = f"{len(bad)} of {len(lines)} line(s) differ"
    else:
        detail = f"{len(lines)} line(s) checked — {ok_text}"
        actual = "All lines OK"
    return _row(name, applies=applies, violated=bool(bad), error_msg=error_msg,
                details=detail, expected=expected, actual=actual)


def opp_line_checks(order_record: dict, opp_line_items=None, order_items=None) -> list:
    """Return the Opportunity Lineitem rows for one Order record.

    opp_line_items: OpportunityLineItem records of the Order's Opportunity (the Q11 query).
    order_items: the Order's OrderItem records (needs Opportunity_Product__c, Quantity, UnitPrice).
    """
    opp = order_record.get("Opportunity") or {}
    if not opp:
        return [{"#": "—", "Validation": "Opportunity Lineitems",
                 "Details": "No Opportunity linked to this Order (OpportunityId is blank).",
                 "Expected": "—", "Actual": "(blank)", "Status": "ℹ️ N/A — no Opportunity"}]
    if opp_line_items is None:
        return [{"#": "—", "Validation": "Opportunity Lineitems",
                 "Details": "Opportunity line items were not fetched.",
                 "Expected": "—", "Actual": "(not fetched)", "Status": "ℹ️ N/A — line items not fetched"}]
    if not opp_line_items:
        return [{"#": "—", "Validation": "Opportunity Lineitems",
                 "Details": "The Opportunity has no line items.",
                 "Expected": "—", "Actual": "0 lines", "Status": "ℹ️ N/A — no line items"}]

    lines = opp_line_items
    rows = []

    # updateProductType — line Prod_Type__c / Support_type__c copy the Product2 values
    def _type_diff(line):
        product = line.get("Product2") or {}
        return (line.get("Prod_Type__c") != product.get("Product_Type__c")
                or line.get("Support_Type__c") != product.get("Support_Type__c"))

    rows.append(_line_check(
        "Product Type / Support Type copied from Product",
        lines, applies=True, is_bad=_type_diff,
        describe=lambda l: (f"Prod_Type {_shown(l.get('Prod_Type__c'))} vs Product "
                            f"{_shown((l.get('Product2') or {}).get('Product_Type__c'))}; Support_Type "
                            f"{_shown(l.get('Support_Type__c'))} vs Product "
                            f"{_shown((l.get('Product2') or {}).get('Support_Type__c'))}"),
        error_msg="Line Prod_Type__c / Support_type__c do not match the Product (updateProductType).",
        expected="Line values = Product2.Product_Type__c / Support_type__c",
        ok_text="Prod Type and Support Type match the Product",
    ))

    # populateRenewalTiming — Renewal lines with a Renewal Due Date
    close_date = opp.get("CloseDate")
    renewal_lines = [l for l in lines if l.get("Line_Type__c") == "Renewal" and l.get("Renewal_Due_Date__c")]
    timing_applies = bool(renewal_lines) and close_date is not None
    rows.append(_line_check(
        "Renewal Timing (On-Time / Early / Late)",
        renewal_lines, applies=timing_applies,
        is_bad=lambda l: l.get("Renewal_Timing__c") != expected_renewal_timing(close_date, l["Renewal_Due_Date__c"]),
        describe=lambda l: (f"Renewal Due {l['Renewal_Due_Date__c']}, Close {close_date}: expected "
                            f"{expected_renewal_timing(close_date, l['Renewal_Due_Date__c'])}, "
                            f"found {_shown(l.get('Renewal_Timing__c'))}"),
        error_msg="Renewal_Timing__c does not match the close date vs renewal due date quarter (populateRenewalTiming).",
        expected="Renewal_Timing__c per fiscal quarter of Close Date vs Renewal Due Date + 1",
        ok_text="Renewal Timing matches the quarter comparison",
    ))

    # TotalPrice = Quantity x UnitPrice
    def _total_bad(line):
        qty, unit, total = _num(line.get("Quantity")), _num(line.get("UnitPrice")), _num(line.get("TotalPrice"))
        return None in (qty, unit, total) or abs(qty * unit - total) > AMOUNT_TOLERANCE

    rows.append(_line_check(
        "Total Price = Quantity x Unit Price",
        lines, applies=True, is_bad=_total_bad,
        describe=lambda l: (f"{_shown(l.get('Quantity'))} x {_money(l.get('UnitPrice'))} = "
                            f"{_money(_num(l.get('Quantity')) * _num(l.get('UnitPrice'))) if None not in (_num(l.get('Quantity')), _num(l.get('UnitPrice'))) else '(blank)'}"
                            f" but TotalPrice is {_money(l.get('TotalPrice'))}"),
        error_msg="Line Total Price is not Quantity x Unit Price.",
        expected="TotalPrice = Quantity x UnitPrice (±0.01)",
        ok_text="Total Price equals Quantity x Unit Price",
    ))

    # Quantity and Subscription Term equal the Quote Line
    with_ql = [l for l in lines if l.get("SBQQ__QuoteLine__r")]

    def _ql_bad(line):
        ql = line["SBQQ__QuoteLine__r"]
        return (_num(line.get("Quantity")) != _num(ql.get("SBQQ__Quantity__c"))
                or _num(line.get("Subscription_Term__c")) != _num(ql.get("SBQQ__SubscriptionTerm__c")))

    rows.append(_line_check(
        "Quantity and Term match Quote Line",
        with_ql, applies=bool(with_ql), is_bad=_ql_bad,
        describe=lambda l: (f"Qty {_shown(l.get('Quantity'))} vs QL {_shown(l['SBQQ__QuoteLine__r'].get('SBQQ__Quantity__c'))}; "
                            f"Term {_shown(l.get('Subscription_Term__c'))} vs QL "
                            f"{_shown(l['SBQQ__QuoteLine__r'].get('SBQQ__SubscriptionTerm__c'))}"),
        error_msg="Line Quantity / Subscription Term differ from the Quote Line.",
        expected="Line Quantity and Subscription Term = Quote Line values",
        ok_text="Quantity and Subscription Term match the Quote Line",
    ))

    # Opportunity.Amount = sum of line TotalPrice
    amount = opp.get("Amount")
    lines_total = sum(_num(l.get("TotalPrice")) or 0.0 for l in lines)
    amount_bad = amount is not None and abs(float(amount) - lines_total) > AMOUNT_TOLERANCE
    rows.append(_row(
        "Opportunity Amount = sum of Line Total Prices",
        applies=amount is not None, violated=amount_bad,
        error_msg="Opportunity Amount is not the sum of its line total prices.",
        details=f"{len(lines)} line(s) | Sum of TotalPrice: {_money(lines_total)} | Opportunity.Amount: {_money(amount)}",
        expected=_money(lines_total), actual=_money(amount),
    ))

    # Order Product <-> Opportunity line link, quantity and unit price
    if order_items is not None:
        by_id = {l.get("Id"): l for l in lines}
        linked = [i for i in order_items if i.get("Opportunity_Product__c")]

        def _oi_bad(item):
            line = by_id.get(item["Opportunity_Product__c"])
            return (line is None or _num(item.get("Quantity")) != _num(line.get("Quantity"))
                    or abs((_num(item.get("UnitPrice")) or 0.0) - (_num(line.get("UnitPrice")) or 0.0)) > AMOUNT_TOLERANCE)

        def _oi_describe(item):
            line = by_id.get(item["Opportunity_Product__c"])
            if line is None:
                return "Opportunity_Product__c points to a line not on this Opportunity"
            return (f"Qty {_shown(item.get('Quantity'))} vs line {_shown(line.get('Quantity'))}; "
                    f"Unit {_money(item.get('UnitPrice'))} vs line {_money(line.get('UnitPrice'))}")

        item_name = lambda i: (i.get("Product2") or {}).get("Name") or str(i.get("Id") or "")[-6:]
        bad_items = [i for i in linked if _oi_bad(i)]
        rows.append(_row(
            "Order Products match their Opportunity line (Quantity, Unit Price)",
            applies=bool(linked), violated=bool(bad_items),
            error_msg="An Order Product differs from its Opportunity line item.",
            details=("; ".join(f"{item_name(i)}: {_oi_describe(i)}" for i in bad_items) if bad_items
                     else f"{len(linked)} Order Product(s) checked — Quantity and Unit Price match"),
            expected="OrderItem Quantity / UnitPrice = Opportunity line",
            actual="All match" if not bad_items else f"{len(bad_items)} of {len(linked)} differ",
        ))

        # Every line is carried onto the Order — only meaningful when the Order is not a split of the Opportunity
        is_split_order = _is_split_order(order_record.get("Order_Split_Type__c"))
        linked_ids = {i["Opportunity_Product__c"] for i in linked}
        missing = [l for l in lines if l.get("Id") not in linked_ids]
        rows.append(_row(
            "Every Opportunity line is on the Order",
            applies=not is_split_order, violated=bool(missing),
            error_msg="An Opportunity line has no matching Order Product.",
            details=(f"{len(lines)} line(s) | Not on Order: " + ", ".join(_label(l) for l in missing)) if missing
                    else f"{len(lines)} line(s) — each has an Order Product",
            expected="Each line linked via OrderItem.Opportunity_Product__c",
            actual="All linked" if not missing else f"{len(missing)} not linked",
        ))
    return rows


def _is_split_order(split_type):
    """Order_Split_Type__c is 'Not needed' (or blank) when the Order is not split; any other value is a split."""
    return not (split_type is None or str(split_type).strip() in ("", "Not needed"))
