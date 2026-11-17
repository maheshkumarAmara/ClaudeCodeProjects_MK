"""Lists the email addresses printed in a PDF and swaps chosen ones for addresses the user typed.

Both operations reuse the content-stream rewriter in sandbox_pdf.py, so a swap changes only the
text-showing operation (and mailto: link) that holds the address; layout, images, other text and
page count are untouched. Unlike the sandbox rewrite, nothing here forces a domain: the new
address is written exactly as given.

Known limitations (same as sandbox_pdf.py):
  - Replaced text is drawn in Helvetica, squeezed horizontally to the original's printed width.
  - An address split across two separate text operations is not detected.
  - A PDF with no text layer (a scan) has no addresses to find.
  - When a generated PO hid an old value under a white box, that hidden address is listed too:
    it is still in the file's text layer, and changing it removes it from there as well.
"""

import re

from pdf_engine.common import EMAIL_RE
from pdf_engine.sandbox_pdf import rewrite_pdf_text

# The shape the page accepts for a new address: one address, nothing else in the box.
_VALID_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")


def is_valid_email(address: str) -> bool:
    return bool(_VALID_RE.fullmatch(address))


def find_emails(pdf_bytes: bytes) -> list[dict]:
    """Every distinct address in the PDF, in first-seen order:
    [{"address", "pages": [1-based page numbers], "count"}]. Reads only; nothing is written."""
    found: dict[str, dict] = {}
    current = {"page": 0}

    def record(text: str) -> str:
        for match in EMAIL_RE.finditer(text):
            entry = found.setdefault(match.group(0), {"address": match.group(0), "pages": [], "count": 0})
            entry["count"] += 1
            if current["page"] not in entry["pages"]:
                entry["pages"].append(current["page"])
        return text

    rewrite_pdf_text(pdf_bytes, replace=record, on_page=lambda n: current.update(page=n), write=False)
    return list(found.values())


def replace_emails(pdf_bytes: bytes, mapping: dict[str, str]) -> bytes:
    """The same PDF with each address in `mapping` (old -> new) swapped for its new value.
    Addresses not in the mapping are left exactly as they are. Raises ValueError for a blank or
    malformed new address, or when there is nothing to change."""
    changes = {old: new.strip() for old, new in mapping.items() if new.strip() != old}
    if not changes:
        raise ValueError("No address was changed.")
    for old, new in changes.items():
        if not new:
            raise ValueError(f"The new address for {old} is blank.")
        if not is_valid_email(new):
            raise ValueError(f"'{new}' is not a valid email address.")

    def swap(text: str) -> str:
        return EMAIL_RE.sub(lambda m: changes.get(m.group(0), m.group(0)), text)

    return rewrite_pdf_text(pdf_bytes, replace=swap)
