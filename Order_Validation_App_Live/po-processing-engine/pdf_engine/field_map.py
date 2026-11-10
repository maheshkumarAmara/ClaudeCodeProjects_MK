"""Where each JSON output field lands on the Stage PO (PO_Stage__c).

Taken from the "Mapping Sheet" tab of the PO automation mapping spreadsheet. Each entry is
(JSON field, Stage PO field(s), type, requirement, note). Requirement is "Must", "Optional"
or "Not required", as the sheet's "Extraction Accuracy?" column has it.
"""

import re

REQ_MUST = "Must"
REQ_OPTIONAL = "Optional"
REQ_NOT_REQUIRED = "Not required"

_HW_NOTE = "Required only when the PO has a HW product (non-ASPEN, RH or RC)"

HEADER_MAP = (
    ("Distributor_Name", ("Distributor_Name__c",), "Text", REQ_MUST, ""),
    ("Bill_To_Name", (), "", REQ_MUST, "No Stage PO field in the mapping sheet"),
    ("Po_Number", ("PoNumber__c",), "Text", REQ_MUST, ""),
    ("Payment_Term", ("Payment_Terms__c",), "Picklist", REQ_MUST, ""),
    ("Po_Date", ("PoDate__c",), "Date", REQ_MUST, ""),
    ("Customer_Requested_Ship_Date", ("Customer_Requested_Ship_Date__c",), "Text", REQ_OPTIONAL, ""),
    ("Account_Name", ("Account_name__c",), "Text", REQ_MUST, ""),
    ("End_User_Po_Number", ("End_User_PO__c",), "Text", REQ_MUST, ""),
    ("Quote_Number", ("Quote_number__c",), "Text", REQ_MUST, ""),
    ("Partner_Name", ("Partner_Name__c",), "Text Area", REQ_OPTIONAL, ""),
    ("Ship_To_Name", ("Ship_to_Account_name__c",), "Text", REQ_MUST, ""),
    ("Ship_To_Contact_Name", ("Ship_To_Contact_Name__c",), "Text", REQ_MUST, ""),
    ("Ship_To_Email", ("Ship_to_Email__c",), "Email", REQ_MUST, ""),
    ("Ship_To_Phone_Number", ("Ship_To_Phone_Number__c",), "Phone", REQ_OPTIONAL, ""),
    ("Shipping_Carrier", ("Shipping_Carrier__c",), "Text Area", REQ_OPTIONAL, _HW_NOTE),
    ("Service_Level", ("Service_Level__c",), "Text Area", REQ_OPTIONAL, _HW_NOTE),
    ("Shipping_Account_Number", ("Shipping_Account_Number__c",), "Text Area", REQ_OPTIONAL, _HW_NOTE),
    ("Shipping_Method", ("Shipping_Method__c",), "Picklist", REQ_MUST, "Shown as Shipping Terms on the Stage PO"),
    ("Total_Excl_VAT_HST_GST", (), "", REQ_NOT_REQUIRED, ""),
    ("VAT_HST_GST", (), "", REQ_NOT_REQUIRED, ""),
    ("Total_Amount_Raw", ("TotalAmount__c",), "Number", REQ_MUST, ""),
    ("Currency", ("Currency_Code__c",), "Text", REQ_MUST, ""),
    ("Note_on_Contingency_and_Special_Language", ("Note_on_Contingency_and_Special_Language__c",), "Long Text Area", REQ_OPTIONAL, ""),
    ("ShippingCity", ("ShippingCity__c",), "Text", REQ_MUST, ""),
    # The sheet leaves the requirement blank here, but its own count (19 required header fields,
    # 18 marked Must) and the JSON's required_header list both include this field.
    ("ShippingState_Province", ("ShippingState__c", "ShippingStateCode__c"), "Text", REQ_MUST,
     "ShippingStateCode__c takes the first 2 characters (bug SMT2-316)"),
    ("ShippingPostalCode", ("ShippingPostalCode__c",), "Text", REQ_MUST, "Only exception is Dubai, with 0000"),
    ("ShippingCountry", ("ShippingCountry__c",), "Text", REQ_MUST, ""),
    ("ShippingStreet", ("ShippingStreet__c",), "Text", REQ_MUST, ""),
)

# Line-item JSON field -> mapping, in the same shape as above.
LINE_MAP = (
    ("Product_Name", ("ProductCode__c",), "Text Area", REQ_MUST, ""),
    ("Quantity_Raw", ("quantityPoItem__c",), "String", REQ_MUST, "Replaces Quantity__c (bug SMT2-315)"),
    ("Unit_Price_Raw", ("Item_Unit_Price__c",), "String", REQ_MUST, "Replaces UnitPrice__c (bug SMT2-315)"),
    ("Subscription_Term", ("Item_Subscription_Term__c",), "String", REQ_MUST,
     "Replaces SubscriptionTerm__c (bug SMT2-315). A null term is not counted as expected"),
    ("Total_Price", (), "", REQ_NOT_REQUIRED, "Never counted in the extraction totals"),
)

# The compared line column -> the JSON field it is read from.
LINE_FIELD_TO_JSON = {
    "sku": "Product_Name",
    "qty": "Quantity_Raw",
    "unit_cost": "Unit_Price_Raw",
    "terms": "Subscription_Term",
    "amount": "Total_Price",
}


def _norm(key) -> str:
    return re.sub(r"[\s_\-]", "", str(key or "")).lower()


def _entry(row) -> dict:
    json_field, stage_fields, type_, requirement, note = row
    return {"json_field": json_field, "stage_fields": list(stage_fields), "type": type_,
            "requirement": requirement, "note": note}


_HEADER_BY_KEY = {_norm(row[0]): _entry(row) for row in HEADER_MAP}
_LINE_BY_KEY = {_norm(row[0]): _entry(row) for row in LINE_MAP}


def header_mapping(*candidates) -> dict | None:
    """The mapping for a header field, trying each candidate key name in turn."""
    for candidate in candidates:
        hit = _HEADER_BY_KEY.get(_norm(candidate))
        if hit:
            return hit
    return None


def line_mapping() -> dict:
    """Compared line column (sku, qty, unit_cost, terms, amount) -> its mapping."""
    return {field: _LINE_BY_KEY[_norm(json_field)] for field, json_field in LINE_FIELD_TO_JSON.items()}
