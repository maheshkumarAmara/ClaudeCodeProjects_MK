"""Read-only pull of Quote/QuoteLine data from Salesforce CPQ via the `sf` CLI.

Nothing here ever writes to Salesforce. Every query goes through the already
authenticated `sf` CLI (`sf data query --target-org <alias> --query "..." --json`)
the same way a developer would run it by hand, so no separate auth flow is
implemented or needed here.
"""

import json
import re
import subprocess
from decimal import Decimal

import config

SF_ORG = config.SALESFORCE_ORG_ALIAS
_QUERY_TIMEOUT_SECONDS = 30
_SF_ID_RE = re.compile(r"^[a-zA-Z0-9]{15}([a-zA-Z0-9]{3})?$")


def _escape_soql_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _run_sf_query(soql: str, org: str = SF_ORG) -> list[dict]:
    try:
        result = subprocess.run(
            ["sf", "data", "query", "--target-org", org, "--query", soql, "--json"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Salesforce CLI ('sf') not found on this machine.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Salesforce query timed out.") from exc

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Salesforce CLI returned unexpected output: {result.stderr or result.stdout}") from exc

    if result.returncode != 0 or payload.get("status") != 0:
        message = payload.get("message") or result.stderr or "Salesforce query failed."
        raise RuntimeError(f"Salesforce query failed ({org}): {message}")

    return payload.get("result", {}).get("records", [])


def search_quotes(term: str, org: str = SF_ORG) -> list[dict]:
    term = term.strip()
    if not term:
        return []
    escaped = _escape_soql_literal(term)
    soql = (
        "SELECT Id, Name, SBQQ__Account__r.Name, SBQQ__Opportunity2__r.Name "
        "FROM SBQQ__Quote__c "
        f"WHERE Name LIKE '%{escaped}%' "
        "ORDER BY LastModifiedDate DESC LIMIT 20"
    )
    records = _run_sf_query(soql, org)
    return [
        {
            "id": rec.get("Id"),
            "name": rec.get("Name"),
            "account_name": (rec.get("SBQQ__Account__r") or {}).get("Name"),
            "opportunity_name": (rec.get("SBQQ__Opportunity2__r") or {}).get("Name"),
        }
        for rec in records
    ]


def match_distributor(name: str | None) -> str | None:
    if not name:
        return None
    normalized = name.strip().lower()
    for slug, display_name in config.DISTRIBUTORS.items():
        if display_name.strip().lower() == normalized:
            return slug
    return None


def _map_fields_default(quote: dict, account: dict, order: dict) -> dict:
    return {
        "quote_number": quote.get("Name") or "",
        "buyer": account.get("Name") or "",
    }


def _get_order_data(opportunity_id: str | None, org: str) -> dict:
    """Best-effort lookup of the Order tied to this Quote's Opportunity.

    An Order (distinct from the Quote/Opportunity) is where this distributor's
    per-order PO number and shipping terms actually live -- see the field
    survey in the PR description. It may not exist yet if this PO is being
    generated ahead of the deal closing, so any failure or empty result here
    is swallowed and treated as "no Order data available" rather than as an
    error, since the rest of the pull is still useful without it.
    """
    if not opportunity_id:
        return {}
    escaped = _escape_soql_literal(opportunity_id)
    soql = (
        "SELECT End_User_PO__c, Shipping_Method__c, Payment_Terms__c "
        "FROM Order "
        f"WHERE OpportunityId = '{escaped}' "
        "ORDER BY CreatedDate DESC LIMIT 1"
    )
    try:
        records = _run_sf_query(soql, org)
    except RuntimeError:
        return {}
    return records[0] if records else {}


def _map_fields_exclusive_networks_south_africa(quote: dict, account: dict, order: dict) -> dict:
    # This distributor's layout has no separate label/value fields for these
    # lines -- each one is the *entire* printed line (static label text baked
    # in) modeled as a single FieldBox, see
    # pdf_engine/layouts/exclusive_networks_south_africa.py's TRAILER_FIELDS.
    fields: dict[str, str] = {}
    quote_name = quote.get("Name")
    if quote_name:
        fields["quote_number_line"] = f"Quote #:{quote_name}"
    account_name = account.get("Name")
    if account_name:
        fields["reseller_end_user_line"] = f"Reseller/ End User: {account_name}"

    # reseller_po_number_line / shipment_terms_line have no source on the
    # Quote/Account -- they only exist on the related Order (see
    # _get_order_data), and are left unset (unchanged/manual) if no Order
    # exists yet for this deal.
    end_user_po = order.get("End_User_PO__c")
    if end_user_po:
        fields["reseller_po_number_line"] = f"Reseller/ End User PO Number: {end_user_po}"
    shipping_method = order.get("Shipping_Method__c")
    if shipping_method:
        fields["shipment_terms_line"] = f"Shipment Terms: {shipping_method}"

    contact = quote.get("SBQQ__PrimaryContact__r") or {}
    contact_name = contact.get("Name")
    if contact_name:
        fields["contact_person_line"] = f"Contact Person: {contact_name}"
    contact_phone = contact.get("Phone")
    if contact_phone:
        fields["tel_nr_line"] = f"Tel Nr: {contact_phone}"
    contact_email = contact.get("Email")
    if contact_email:
        fields["email_line"] = f"Email: {contact_email}"

    # The address_block FieldBox only has room for 2 printed lines before it
    # collides with email_line below it -- so a multi-line street address is
    # joined onto a single line here rather than kept as separate lines.
    street = " ".join(
        part.strip()
        for part in (quote.get("SBQQ__ShippingStreet__c") or "").splitlines()
        if part.strip()
    )
    city_state = ", ".join(
        part
        for part in (quote.get("SBQQ__ShippingCity__c"), quote.get("SBQQ__ShippingState__c"))
        if part
    )
    if quote.get("SBQQ__ShippingPostalCode__c"):
        city_state = f"{city_state} {quote['SBQQ__ShippingPostalCode__c']}".strip()
    second_line = ", ".join(
        part for part in (city_state, quote.get("SBQQ__ShippingCountry__c")) if part
    )
    address_lines = [line for line in (street, second_line) if line]
    if address_lines:
        fields["address_block"] = "Address: " + "\n".join(address_lines)

    # Prefer the Order's own payment terms (the actual booked deal) and fall
    # back to the Quote's when no Order exists yet.
    payment_terms = order.get("Payment_Terms__c") or quote.get("SBQQ__PaymentTerms__c")
    if payment_terms:
        fields["payment_terms_line"] = f"Payment terms: {payment_terms}"

    return fields


def _map_fields_nextgen_distribution_pty_ltd(quote: dict, account: dict, order: dict) -> dict:
    # delivery_name and end_user are both the Quote's Account (SBQQ__Account__c)
    # name. The generator adds the "EU: " prefix to end_user itself.
    fields: dict[str, str] = {}
    account_name = account.get("Name")
    if account_name:
        fields["delivery_name"] = account_name
        fields["end_user"] = account_name
    quote_name = quote.get("Name")
    if quote_name:
        fields["quote_number"] = quote_name
    # total is the Quote's Net Amount, in the "USD 684,613.43" shape the
    # template prints (the generator reads the 3-letter currency off this
    # field and falls back to USD when it's absent).
    net_amount = quote.get("SBQQ__NetAmount__c")
    if net_amount is not None:
        fields["total"] = f"USD {float(net_amount):,.2f}"
    return fields


def _map_fields_computer_gross_spa(quote: dict, account: dict, order: dict) -> dict:
    # The End User column's Company Name (end_user_company) is the Quote's
    # Account (SBQQ__Account__c) name.
    fields = _map_fields_default(quote, account, order)
    account_name = account.get("Name")
    if account_name:
        fields["end_user_company"] = account_name
    return fields


_FIELD_MAPPERS = {
    "arrow-ecs-sau": _map_fields_default,
    "exclusive-networks-south-africa": _map_fields_exclusive_networks_south_africa,
    "NextGen Distribution Pty Ltd": _map_fields_nextgen_distribution_pty_ltd,
    "Computer Gross spa": _map_fields_computer_gross_spa,
}


_NEXTGEN_SLUG = "NextGen Distribution Pty Ltd"


def _apply_nextgen_pricing(item: dict, rec: dict) -> None:
    """Adapts a pulled line to NextGen's price convention.

    NextGen's PDF prints Unit Price as a *per-month* rate and computes
    amount = qty x unit price x term months, whereas Salesforce's
    SBQQ__NetPrice__c is already the whole-term price -- using it as-is
    multiplies the term in twice. So convert it to a monthly rate, and carry
    Salesforce's own line total (SBQQ__NetTotal__c) as the row's printed
    amount so the PDF's Order Total adds up to the Quote's Net Amount instead
    of drifting by the monthly rate's rounding. (amount_basis is what the
    generator compares to decide the amount is still valid for this
    qty/unit price/terms; editing any of them makes it recompute.)
    """
    term = rec.get("SBQQ__SubscriptionTerm__c")
    net_price = rec.get("SBQQ__NetPrice__c")
    if net_price is not None and term:
        item["unit_cost"] = f"{Decimal(str(net_price)) / Decimal(str(term)):.4f}"
    net_total = rec.get("SBQQ__NetTotal__c")
    if net_total is not None:
        item["amount"] = f"{Decimal(str(net_total)):.2f}"
        item["amount_basis"] = f"{item['qty']}|{item['unit_cost']}|{item['terms']}"


def get_quote_data(quote_id: str, org: str = SF_ORG, slug: str | None = None) -> dict:
    quote_id = quote_id.strip()
    if not _SF_ID_RE.match(quote_id):
        raise ValueError(f"'{quote_id}' is not a valid Salesforce record Id.")

    soql = (
        "select id,SBQQ__NetPrice__c,SBQQ__NetTotal__c,SBQQ__SubscriptionTerm__c,SBQQ__Product__r.Name,"
        "SBQQ__Product__r.ProductCode,Printable_Product__c,SBQQ__Description__c,"
        "SBQQ__Quantity__c,SBQQ__Quote__r.Name,SBQQ__Quote__r.SBQQ__NetAmount__c,"
        "SBQQ__Quote__r.SBQQ__Account__r.Name,"
        "SBQQ__Quote__r.SBQQ__Opportunity2__r.Distributor_Lookup__c,"
        "SBQQ__Quote__r.SBQQ__Opportunity2__r.Distributor_Lookup__r.Name,"
        "SBQQ__Quote__r.SBQQ__Opportunity2__r.ContractManufacturer__c,"
        "SBQQ__Quote__r.SBQQ__Opportunity2__r.Id,"
        "SBQQ__Quote__r.SBQQ__PrimaryContact__r.Name,"
        "SBQQ__Quote__r.SBQQ__PrimaryContact__r.Phone,"
        "SBQQ__Quote__r.SBQQ__PrimaryContact__r.Email,"
        "SBQQ__Quote__r.SBQQ__PaymentTerms__c,"
        "SBQQ__Quote__r.SBQQ__ShippingName__c,"
        "SBQQ__Quote__r.SBQQ__ShippingStreet__c,"
        "SBQQ__Quote__r.SBQQ__ShippingCity__c,"
        "SBQQ__Quote__r.SBQQ__ShippingState__c,"
        "SBQQ__Quote__r.SBQQ__ShippingPostalCode__c,"
        "SBQQ__Quote__r.SBQQ__ShippingCountry__c "
        "from SBQQ__QuoteLine__c "
        f"where SBQQ__Quote__r.Id ='{quote_id}' "
        "and SBQQ__Renewal__c!=true "
        "and (NOT (SBQQ__Product__r.Name Like 'RBK%')) "
        "and (NOT (SBQQ__Product__r.Name Like 'RHA%' or SBQQ__Product__r.Name Like 'RCA%')) "
        "and SBQQ__Optional__c=false"
    )
    records = _run_sf_query(soql, org)
    if not records:
        raise LookupError(f"No eligible Quote Line records found for Quote Id '{quote_id}'.")

    first = records[0]
    quote = first.get("SBQQ__Quote__r") or {}
    account = quote.get("SBQQ__Account__r") or {}
    opportunity = quote.get("SBQQ__Opportunity2__r") or {}
    distributor = (opportunity.get("Distributor_Lookup__r") or {}).get("Name")
    suggested_slug = match_distributor(distributor)
    effective_slug = slug or suggested_slug
    map_fields = _FIELD_MAPPERS.get(effective_slug, _map_fields_default)
    order = _get_order_data(opportunity.get("Id"), org)

    line_items = []
    for rec in records:
        product = rec.get("SBQQ__Product__r") or {}
        terms = rec.get("SBQQ__SubscriptionTerm__c")
        line_items.append(
            {
                "part_number": rec.get("Printable_Product__c") or product.get("ProductCode") or product.get("Name") or "",
                "description": rec.get("SBQQ__Description__c") or product.get("Name") or "",
                "qty": str(rec.get("SBQQ__Quantity__c") or ""),
                "unit_cost": str(rec.get("SBQQ__NetPrice__c") or ""),
                "pct_disc": "",
                "terms": str(terms) if terms is not None else "",
            }
        )
        if effective_slug == _NEXTGEN_SLUG:
            _apply_nextgen_pricing(line_items[-1], rec)

    return {
        "fields": map_fields(quote, account, order),
        "line_items": line_items,
        "distributor_name": distributor,
        "suggested_slug": suggested_slug,
    }
