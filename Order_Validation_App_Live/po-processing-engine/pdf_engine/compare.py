"""Compares a parsed purchase-order PDF against a JSON file.

The PDF side is the {fields, line_items} dict a distributor parser returns. The
JSON side is read tolerantly: the line items are the first list of objects that
carries a SKU-like key, and each value is looked up under a few common key names.
Lines are matched by SKU (the Nth occurrence of a SKU in the PDF is paired with
the Nth in the JSON), then qty, unit price, term and amount are compared.
"""

import json
import re
from decimal import Decimal, InvalidOperation

# Canonical field -> key names accepted in the JSON, compared case-insensitively
# with spaces, dashes and underscores ignored.
KEY_ALIASES = {
    "sku": ("partnumber", "sku", "productcode", "productname", "product", "itemnumber", "item", "material", "part"),
    "qty": ("qty", "quantity"),
    "unit_cost": ("unitcost", "unitprice", "price", "netprice", "unitnetprice"),
    "terms": ("terms", "term", "subscriptionterm", "termmonths", "termsmonths"),
    "amount": ("amount", "total", "totalprice", "linetotal", "nettotal", "extendedprice"),
}
# PDF header field -> JSON key names that mean the same thing, for header comparison.
# A PDF field is also matched against the JSON key of the same name.
HEADER_ALIASES = {
    "po_number": ("ponumber", "purchaseordernumber", "pono"),
    "order_date": ("podate", "orderdate", "date"),
    "po_date": ("podate", "orderdate"),
    "total": ("totalamount", "total", "grandtotal"),
    "total_price": ("totalexclvathstgst", "subtotal", "totalexcltax", "totalprice"),
    "tax": ("vathstgst", "vat", "tax"),
    "currency": ("currency", "currencycode"),
    "payment_terms": ("paymentterm", "paymentterms"),
    "end_user": ("accountname", "enduser", "endusername"),
    "customer_po": ("enduserponumber", "customerpo", "endcustomerpo"),
    "reseller_name": ("partnername", "resellername", "reseller"),
    "quote_number": ("quotenumber", "quote", "quoteno"),
    "contact_name": ("shiptocontactname",),
    "contact_phone": ("shiptophonenumber",),
    "contact_email": ("shiptoemail",),
    "incoterms": ("shippingmethod",),
    "delivery_terms": ("shippingmethod",),
    "contingency_note": ("noteoncontingencyandspeciallanguage",),
    "distributor_name": ("distributorname",),
    "bill_to_name": ("billtoname",),
    "goods_value": ("totalexclvathstgst",),
    "vat_amount": ("vathstgst",),
    "ship_to_company": ("shiptoname",),
    "ship_to_contact": ("shiptocontactname",),
    "ship_to_email": ("shiptoemail",),
    "ship_to_street": ("shippingstreet",),
    "ship_to_postcode": ("shippingpostalcode",),
    "ship_to_city": ("shippingcity",),
    "ship_to_country": ("shippingcountry",),
    "ship_to_phone": ("shiptophonenumber",),
    "enduser_po": ("endusernumber", "enduserponumber", "endcustomerpo"),
    "licensee_company": ("accountname",),
}
HEADER_DATE_FIELDS = {"order_date", "po_date"}
HEADER_NUMBER_FIELDS = {"total", "total_price", "tax", "goods_value", "vat_amount"}
# Header fields compared as exact text. The ADN total prints as "101.340,00 USD", and a
# JSON that holds "101340.00" must not match it.
HEADER_EXACT_FIELDS = {"total"}
# Top-level JSON keys that describe the run, not the purchase order, so they are not header fields.
JSON_ENVELOPE_KEYS = {"correlationid", "status", "traceid"}
COMPARED_FIELDS = ("qty", "unit_cost", "terms", "amount")
NUMERIC_FIELDS = {"qty", "unit_cost", "amount"}
FIELD_LABELS = {"qty": "Quantity", "unit_cost": "Unit price", "terms": "Term", "amount": "Amount"}
HEADER_LABELS = {"po_number": "PO number", "po_date": "PO date", "order_date": "Order date", "customer_po": "Customer PO"}
NOT_IN_JSON = "SKU not found in the JSON"
NOT_IN_PDF = "SKU not found in the PDF"


def _norm_key(key: str) -> str:
    return re.sub(r"[\s_\-]", "", str(key)).lower()


def to_number(value) -> Decimal | None:
    """Parses '1,200.50', '1.200,50', 'USD 1,000.00' or 12 into a Decimal; None if it isn't a number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = re.sub(r"[^\d,.\-]", "", str(value))
    if not re.search(r"\d", text):
        return None
    if "," in text and "." in text:
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        text = text.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif "," in text:
        text = text.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+", text) else text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _term_months(value) -> Decimal | None:
    """The first number in a term such as '18 Months (2/01/2026 - 30/06/2027)'."""
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    match = re.search(r"\d+(?:[.,]\d+)?", str(value or ""))
    return Decimal(match.group(0).replace(",", ".")) if match else None


def _sku(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _pick(obj: dict, field: str):
    by_key = {_norm_key(k): v for k, v in obj.items()}
    for alias in KEY_ALIASES[field]:
        if alias in by_key and by_key[alias] not in (None, ""):
            return by_key[alias]
    return None


def load_json_lines(data) -> list[dict]:
    """The first list of objects in `data` that carries a SKU-like key."""
    stack = [data]
    while stack:
        node = stack.pop(0)
        if isinstance(node, list):
            objs = [o for o in node if isinstance(o, dict)]
            if objs and any(_pick(o, "sku") is not None for o in objs):
                return objs
            stack.extend(node)
        elif isinstance(node, dict):
            stack.extend(node.values())
    return []


def _json_header(data) -> dict:
    """Scalar top-level values, plus those one level down under a 'fields' / 'header' object."""
    header: dict = {}
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict) and _norm_key(key) in ("fields", "header", "headers", "purchaseorder", "order", "po"):
                header.update({k: v for k, v in value.items() if not isinstance(v, (dict, list))})
            elif not isinstance(value, (dict, list)):
                header[key] = value
    return header


def _pdf_value(item: dict, field: str):
    """The PDF side of a field. A parser that keeps the text exactly as printed
    (`<field>_as_printed`, set for ADN's unit price) has that text compared as it is,
    with no number conversion on either side."""
    return item.get(f"{field}_as_printed", item.get(field))


def _equal(field: str, pdf_value, json_value, tolerance: Decimal, exact: bool = False) -> bool:
    if exact:
        return str(pdf_value if pdf_value is not None else "").strip() == str(json_value if json_value is not None else "").strip()
    if field in NUMERIC_FIELDS:
        a, b = to_number(pdf_value), to_number(json_value)
        if a is None or b is None:
            return str(pdf_value or "").strip() == str(json_value or "").strip()
        return abs(a - b) <= tolerance
    if field == "terms":
        a, b = _term_months(pdf_value), _term_months(json_value)
        if a is not None and b is not None:
            return a == b
    return str(pdf_value or "").strip().lower() == str(json_value or "").strip().lower()


def _to_date(value):
    """A date from '2025-08-13', '10/27/26', '27.10.2026' or '13-Aug-2025'; None if it isn't one."""
    from datetime import datetime

    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y", "%d.%m.%Y", "%d/%m/%Y", "%d-%b-%Y", "%b %d %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _header_equal(field: str, pdf_value, json_value, tol: Decimal) -> bool:
    if field in HEADER_EXACT_FIELDS:
        # Compared as printed, with no number conversion on either side.
        return str(pdf_value if pdf_value is not None else "").strip() == str(json_value if json_value is not None else "").strip()
    if field in HEADER_DATE_FIELDS:
        a, b = _to_date(pdf_value), _to_date(json_value)
        if a is not None and b is not None:
            return a == b
    if field in HEADER_NUMBER_FIELDS:
        a, b = to_number(pdf_value), to_number(json_value)
        if a is not None and b is not None:
            return abs(a - b) <= tol
    if field == "payment_terms":
        a, b = re.findall(r"\d+", str(pdf_value or "")), re.findall(r"\d+", str(json_value or ""))
        if a and b:
            return a == b
    return re.sub(r"\s+", " ", str(pdf_value or "")).strip().lower() == re.sub(r"\s+", " ", str(json_value or "")).strip().lower()


def _show(value) -> str:
    return "" if value is None else str(value)


def _header_comment(field: str, pdf_value, json_value) -> str:
    """Why a header field differs; the same wording style as line comments."""
    label = HEADER_LABELS.get(field, field.replace("_", " ").capitalize())
    pdf_text, json_text = _show(pdf_value).strip(), _show(json_value).strip()
    if not json_text:
        return f"{label} is missing in the JSON (PDF has {pdf_text})"
    if field in HEADER_EXACT_FIELDS:
        return f'{label} differs as printed: PDF "{pdf_text}", JSON "{json_text}"'
    return f"{label} differs: PDF {pdf_text}, JSON {json_text}"


def _field_comment(field: str, pdf_value, json_value, tol: Decimal, exact: bool = False) -> str:
    """Why a compared field differs, in words a reviewer can act on."""
    label = FIELD_LABELS[field]
    pdf_text, json_text = _show(pdf_value).strip(), _show(json_value).strip()
    if not json_text:
        return f"{label} is missing in the JSON (PDF has {pdf_text})"
    if not pdf_text:
        return f"{label} is missing in the PDF (JSON has {json_text})"
    if exact:
        return f'{label} differs as printed: PDF "{pdf_text}", JSON "{json_text}"'
    if field in NUMERIC_FIELDS:
        a, b = to_number(pdf_value), to_number(json_value)
        if a is not None and b is not None:
            return f"{label} differs: PDF {pdf_text}, JSON {json_text} (difference {abs(a - b)}, tolerance {tol})"
    return f"{label} differs: PDF {pdf_text}, JSON {json_text}"


def compare(pdf_parsed: dict, json_text: str, tolerance: str = "0.01") -> dict:
    data = json.loads(json_text)
    tol = to_number(tolerance) or Decimal("0.01")

    pdf_lines = pdf_parsed.get("line_items", [])
    json_lines = load_json_lines(data)

    json_by_sku: dict[str, list[dict]] = {}
    for obj in json_lines:
        json_by_sku.setdefault(_sku(_pick(obj, "sku")), []).append(obj)

    def distance(item: dict, obj: dict) -> int:
        """How many compared fields differ; used to pair repeated SKUs with their closest line."""
        return sum(
            1
            for f in COMPARED_FIELDS
            if not (f == "amount" and (item.get(f) in (None, "") or _pick(obj, f) is None))
            and not _equal(f, _pdf_value(item, f), _pick(obj, f), tol, f"{f}_as_printed" in item)
        )

    # Pair repeated SKUs best-first, so one missing or reordered line doesn't shift
    # every later line of that SKU into a false mismatch.
    paired: dict[int, dict] = {}
    pdf_by_sku: dict[str, list[int]] = {}
    for index, item in enumerate(pdf_lines):
        pdf_by_sku.setdefault(_sku(item.get("part_number") or item.get("description")), []).append(index)
    for sku_key, indexes in pdf_by_sku.items():
        candidates = json_by_sku.get(sku_key, [])
        scored = sorted(
            ((distance(pdf_lines[i], obj), i, j) for i in indexes for j, obj in enumerate(candidates)),
            key=lambda t: (t[0], t[1], t[2]),
        )
        used_pdf, used_json = set(), set()
        for _, i, j in scored:
            if i in used_pdf or j in used_json:
                continue
            used_pdf.add(i)
            used_json.add(j)
            paired[i] = candidates[j]
        json_by_sku[sku_key] = [obj for j, obj in enumerate(candidates) if j not in used_json]

    lines = []
    for index, item in enumerate(pdf_lines):
        sku = item.get("part_number") or item.get("description") or ""
        obj = paired.get(index)
        if obj is None:
            lines.append({"sku": sku, "status": "only_pdf", "comments": [NOT_IN_JSON], "fields": {
                f: {"pdf": _show(item.get(f)), "json": "", "match": None, "comment": NOT_IN_JSON}
                for f in COMPARED_FIELDS}})
            continue
        fields = {}
        for f in COMPARED_FIELDS:
            exact = f"{f}_as_printed" in item
            pdf_value, json_value = _pdf_value(item, f), _pick(obj, f)
            if f == "amount" and (pdf_value in (None, "") or json_value is None):
                continue
            match = _equal(f, pdf_value, json_value, tol, exact)
            fields[f] = {"pdf": _show(pdf_value), "json": _show(json_value), "match": match,
                         "comment": "" if match else _field_comment(f, pdf_value, json_value, tol, exact)}
        status = "match" if all(v["match"] for v in fields.values()) else "mismatch"
        comments = [v["comment"] for v in fields.values() if v["comment"]]
        lines.append({"sku": sku, "status": status, "comments": comments, "fields": fields})

    for sku, leftover in json_by_sku.items():
        for obj in leftover:
            lines.append({"sku": _show(_pick(obj, "sku")), "status": "only_json", "comments": [NOT_IN_PDF], "fields": {
                f: {"pdf": "", "json": _show(_pick(obj, f)), "match": None, "comment": NOT_IN_PDF}
                for f in COMPARED_FIELDS}})

    header = []
    json_header = {_norm_key(k): (k, v) for k, v in _json_header(data).items()}
    for key, pdf_value in pdf_parsed.get("fields", {}).items():
        candidates = (_norm_key(key),) + HEADER_ALIASES.get(key, ())
        hit = next((json_header[c] for c in candidates if c in json_header), None)
        if hit is None or pdf_value in (None, ""):
            continue
        match = _header_equal(key, pdf_value, hit[1], tol)
        header.append({"field": key, "json_key": hit[0], "pdf": _show(pdf_value), "json": _show(hit[1]),
                       "match": match, "comment": "" if match else _header_comment(key, pdf_value, hit[1])})

    # Every other header field in the JSON is listed too, so a field the PDF does not carry
    # (or that is empty in the JSON) is visible rather than silently skipped. These rows
    # have no PDF value to compare, so they are not counted as matches or mismatches.
    compared_keys = {_norm_key(row["json_key"]) for row in header}
    for norm, (json_key, json_value) in json_header.items():
        if norm in compared_keys or norm in JSON_ENVELOPE_KEYS:
            continue
        empty = json_value in (None, "")
        header.append({
            "field": json_key, "json_key": json_key, "pdf": "", "json": _show(json_value),
            "match": None, "side": "only_json",
            "comment": "Empty in the JSON, and the PDF has no value for it" if empty
            else "In the JSON only: the PDF has no value for this field",
        })

    # PDF fields that have a value but no counterpart in the JSON: listed too, so "Only in
    # PDF" shows them. Like the rows above they have nothing to compare against.
    listed_fields = {row["field"] for row in header}
    for key, pdf_value in pdf_parsed.get("fields", {}).items():
        if key in listed_fields or pdf_value in (None, ""):
            continue
        header.append({
            "field": key, "json_key": "", "pdf": _show(pdf_value), "json": "",
            "match": None, "side": "only_pdf",
            "comment": "In the PDF only: the JSON has no field for this value",
        })

    count = lambda status: sum(1 for line in lines if line["status"] == status)
    return {
        "summary": {
            "pdf_lines": len(pdf_lines),
            "json_lines": len(json_lines),
            "matched": count("match"),
            "mismatched": count("mismatch"),
            "only_in_pdf": count("only_pdf"),
            "only_in_json": count("only_json"),
            "header_compared": sum(1 for h in header if h["match"] is not None),
            "header_mismatched": sum(1 for h in header if h["match"] is False),
            "header_not_compared": sum(1 for h in header if h["match"] is None),
            "header_only_in_pdf": sum(1 for h in header if h.get("side") == "only_pdf"),
            "header_only_in_json": sum(1 for h in header if h.get("side") == "only_json"),
        },
        "lines": lines,
        "header": header,
    }
