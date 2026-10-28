"""Template parser for Innocom Ltd purchase orders.

The sample is a portrait, 2-page printout from Innocom's Priority ERP: every page
repeats a letterhead (logo, address, Tel/Fax, company number, withheld tax file,
website), a "To:" block with the order date, the title "Purchase Order <no> -
Authorized" and a ruled items table; the last page ends with the totals box and a
free-text block (barcode text, payment terms, project, vendor / sales order
numbers, end user, customer PO, reseller, quote, shipping instructions, contact).

Each table row is a main line (Line, Part Number, Part Description, Quantity +
"ea", "USD" + Unit Price, Extended Price) with a second line holding that row's
Exchange Rate and TERM (M), and a third line holding the rest of the description.
The source system truncates part descriptions to two short lines, so what is
printed ("... per usable BETB;" / "Prem") is loaded as is and nothing is invented.

Items carry the editor's six columns (`part_number`, `description`, `qty`,
`unit_cost`, `pct_disc`, `terms` -- `terms` is the TERM in months) plus the other
printed values so a loaded template round-trips: `unit` ("ea"), `currency`
("USD"), `exchange_rate`, `amount` (the printed Extended Price) and
`amount_basis` (the qty / unit cost / terms the amount was printed for, so the
generator can tell whether the row was edited and must be recomputed). The
description is the printed lines joined with a space; `description_lines` keeps
them as printed and `description_basis` records the joined text, so the
generator redraws the printed breaks while the description is untouched.
Text is normalised: the source's U+037E (Greek question mark) becomes ";".
"""

import re
from pathlib import Path

import pdfplumber

LINE_TOLERANCE = 2.0

# Items table columns (x ranges of a word's x0), measured from the sample.
COL_LINE = (0, 33)
COL_PART_NUMBER = (33, 112)
COL_DESCRIPTION = (112, 279)
COL_QTY = (279, 324)
COL_UNIT_PRICE = (324, 384)
COL_AMOUNT = (384, 499)
COL_EXCHANGE = (499, 550)
COL_TERM = (550, 590)

_NUMBER_RE = re.compile(r"^[\d,]+(?:\.\d+)?$")


def _plain_number(text: str) -> str:
    """"108,312.00" -> "108312.00" (the form holds plain numbers)."""
    return text.replace(",", "").strip()


def _text(words: list[dict]) -> str:
    # The source system prints U+037E (Greek question mark) where a ";" belongs;
    # normalise it so the form shows, and the generator draws, a real semicolon.
    return " ".join(w["text"] for w in sorted(words, key=lambda w: w["x0"])).replace(";", ";")


def _in_x(words: list[dict], x_range: tuple[float, float]) -> list[dict]:
    return [w for w in words if x_range[0] <= w["x0"] < x_range[1]]


def _cluster_lines(words: list[dict]) -> list[tuple[float, list[dict]]]:
    clusters: list[list] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if clusters and w["top"] - clusters[-1][0] <= LINE_TOLERANCE:
            clusters[-1][1].append(w)
        else:
            clusters.append([w["top"], [w]])
    return [(top, sorted(ws, key=lambda w: w["x0"])) for top, ws in clusters]


def _is_main_row(line: list[dict]) -> bool:
    first = _in_x(line, COL_LINE)
    return bool(first) and first[0]["text"].isdigit() and bool(_in_x(line, COL_PART_NUMBER))


def _parse_items_page(page, items: list[dict]) -> float:
    """Appends this page's items; returns the top of the first line below the table
    (the 'Total Price' line), or the page height when this page has no totals."""
    words = page.extract_words(keep_blank_chars=False)
    header = next((w for w in words if w["text"] == "Line" and w["x0"] < 33), None)
    if header is None:
        return page.height
    total_label = next((w for w in words if w["text"] == "Total" and w["x0"] > 340), None)
    end_top = total_label["top"] if total_label else page.height
    body = [w for w in words if header["top"] + 12.0 < w["top"] < end_top - 2.0]

    current: dict | None = None
    for _, line in _cluster_lines(body):
        if _is_main_row(line):
            qty_words = _in_x(line, COL_QTY)
            unit = qty_words[-1]["text"] if len(qty_words) > 1 else ""
            qty = _plain_number(qty_words[0]["text"]) if qty_words else ""
            price_words = _in_x(line, COL_UNIT_PRICE)
            currency = price_words[0]["text"] if len(price_words) > 1 else ""
            unit_cost = _plain_number(price_words[-1]["text"]) if price_words else ""
            current = {
                "part_number": _text(_in_x(line, COL_PART_NUMBER)),
                "description": _text(_in_x(line, COL_DESCRIPTION)),
                # The description as printed, line by line (the source cuts it by
                # characters, so the breaks are not word breaks); the generator
                # redraws these lines as is while "description" is unedited.
                "description_lines": [_text(_in_x(line, COL_DESCRIPTION))],
                "qty": qty,
                "unit_cost": unit_cost,
                "pct_disc": "",
                "terms": "",
                "line_no": _text(_in_x(line, COL_LINE)),
                "unit": unit,
                "currency": currency,
                "exchange_rate": "",
                "amount": _plain_number(_text(_in_x(line, COL_AMOUNT))),
            }
            items.append(current)
        elif current is not None:
            rate = _in_x(line, COL_EXCHANGE)
            term = _in_x(line, COL_TERM)
            if rate and _NUMBER_RE.match(rate[0]["text"]):
                current["exchange_rate"] = _plain_number(rate[0]["text"])
                current["terms"] = _plain_number(term[0]["text"]) if term else ""
            extra = _text(_in_x(line, COL_DESCRIPTION))
            if extra and not rate:
                current["description"] = f"{current['description']} {extra}".strip()
                current["description_lines"].append(extra)
    for item in items:
        item["amount_basis"] = f"{item['qty']}|{item['unit_cost']}|{item['terms']}"
        item["description_basis"] = item["description"]
    return end_top


def _after(text: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}\s*(.*)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _left_column_text(page, x_max: float = 340.0) -> str:
    """The page's text with the totals box (x >= 355) and the signature block cut
    away, so a free-text line that shares a row with the totals isn't mixed up with
    them."""
    return (page.crop((0, 0, x_max, page.height)).extract_text() or "")


def parse_template(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        first = pdf.pages[0].extract_text() or ""
        last_full = pdf.pages[-1].extract_text() or ""
        last = _left_column_text(pdf.pages[-1])
        items: list[dict] = []
        for page in pdf.pages:
            _parse_items_page(page, items)

    fields: dict[str, str] = {}
    fields["order_date"] = (re.search(r"Order Date:\s*(\S+)", first) or [None, ""])[1]
    title = re.search(r"Purchase Order\s+(\S+)\s+-\s+(.+)$", first, re.MULTILINE)
    fields["po_number"] = title.group(1) if title else ""
    fields["po_status"] = title.group(2).strip() if title else ""
    to_block = re.search(r"To:.*?\n(.*?)\nPurchase Order", first, re.DOTALL)
    to_lines = [ln for ln in (to_block.group(1).splitlines() if to_block else []) if ln.strip()]
    fields["to_block"] = "\n".join(
        re.sub(r"^Order Date:.*$", "", ln).strip() for ln in to_lines
    ).strip()

    fields["total_price"] = (re.search(r"Total Price\s+([\d,]+\.\d{2})", last_full) or [None, ""])[1]
    fields["tax"] = (re.search(r"Tax\s+([\d,]+\.\d{2})", last_full) or [None, ""])[1]
    total = re.search(r"TOTAL\s+([A-Z]{3})\s+([\d,]+\.\d{2})", last_full)
    fields["currency"] = total.group(1) if total else ""
    fields["total"] = total.group(2) if total else ""
    fields["payment_terms"] = _after(last, "Payment Terms:")
    fields["project"] = _after(last, "Project:")
    fields["vendor_number"] = _after(last, "Vendor Number:")
    fields["sales_order"] = _after(last, "Sales Order:")
    fields["current_version"] = _after(last, "Current Version:")
    end_user_lines = re.findall(r"^End User:\s*(.*)$", last, re.MULTILINE)
    fields["end_user"] = end_user_lines[0].strip() if end_user_lines else ""
    fields["end_user_address"] = end_user_lines[1].strip() if len(end_user_lines) > 1 else ""
    fields["customer_po"] = _after(last, "Customer PO:")
    fields["reseller_name"] = _after(last, "Reseller Name:")
    quote = re.search(r"^Quote\s*:\s*(.+)$", last, re.MULTILINE)
    fields["quote_number"] = re.sub(r"\s+", "", quote.group(1)) if quote else ""
    fields["ship_to_instruction"] = _after(last, "Please ship to")
    if fields["ship_to_instruction"]:
        fields["ship_to_instruction"] = f"Please ship to {fields['ship_to_instruction']}"
    ship_with = _after(last, "Please ship with")
    fields["ship_with_instruction"] = f"Please ship with {ship_with}" if ship_with else ""
    incoterms = re.search(r"^(FCA ORIGIN.*)$", last, re.MULTILINE)
    fields["incoterms"] = incoterms.group(1).strip() if incoterms else ""
    after_inco = last.split(fields["incoterms"], 1)[1] if fields["incoterms"] and fields["incoterms"] in last else ""
    contact_lines = [ln.strip() for ln in after_inco.splitlines() if ln.strip()]
    fields["contact_name"] = contact_lines[0] if contact_lines else ""
    fields["contact_phone"] = _after("\n".join(contact_lines), "Phone:")
    fields["contact_email"] = _after("\n".join(contact_lines), "Email:")
    fields["contact_website"] = next((ln for ln in contact_lines if ln.startswith("www.")), "")
    # The signature block sits at the bottom right (x >= 430), below the totals box.
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[-1]
        sig_lines = [
            _text(ws) for _, ws in _cluster_lines([w for w in page.extract_words() if w["x0"] >= 430 and w["top"] > 300])
        ]
    fields["signer_name"] = sig_lines[0] if sig_lines else ""
    fields["signer_company"] = sig_lines[1] if len(sig_lines) > 1 else ""
    return {"fields": fields, "line_items": items}
