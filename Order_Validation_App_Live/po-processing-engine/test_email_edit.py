"""Tests for the Email Editor (pdf_engine/email_edit.py + /api/email-editor/*).

Run from this folder:  python -m pytest test_email_edit.py -q
"""

import base64
import io
import json
from pathlib import Path

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from reportlab.pdfgen import canvas

import main
from pdf_engine import convert, email_edit
from pdf_engine.sandbox_pdf import sandbox_pdf_emails

client = TestClient(main.app)

SALES = "sales@distributor.example"
BILLING = "billing@distributor.example"


def _po_pdf() -> bytes:
    """Two pages: page 1 has two addresses (one also as a mailto: link) and other text; page 2
    repeats one address."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(612, 792))
    pdf.setFont("Helvetica", 11)
    pdf.drawString(72, 720, "PURCHASE ORDER 4500123  Total 1,250.00 USD")
    pdf.drawString(72, 700, f"Contact: {SALES}")
    pdf.drawString(72, 680, f"Invoices to {BILLING} please")
    pdf.linkURL(f"mailto:{SALES}", (72, 695, 250, 712))
    pdf.showPage()
    pdf.setFont("Helvetica", 11)
    pdf.drawString(72, 720, f"Questions: {SALES}")
    pdf.drawString(72, 700, "Terms: net 30")
    pdf.save()
    return buffer.getvalue()


def _text(pdf_bytes: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _links(pdf_bytes: bytes) -> list[str]:
    uris = []
    for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
        for annot in page.get("/Annots") or []:
            action = annot.get_object().get("/A")
            if action is not None and "/URI" in action.get_object():
                uris.append(str(action.get_object()["/URI"]))
    return uris


def test_find_emails_lists_each_address_once_with_pages_and_counts():
    found = {e["address"]: e for e in email_edit.find_emails(_po_pdf())}
    assert set(found) == {SALES, BILLING}
    assert found[SALES]["pages"] == [1, 2]
    assert found[SALES]["count"] >= 3  # two text lines + the mailto: link
    assert found[BILLING]["pages"] == [1]


def test_find_emails_keeps_first_seen_order():
    assert [e["address"] for e in email_edit.find_emails(_po_pdf())] == [SALES, BILLING]


def test_replace_changes_only_the_mapped_address():
    original = _po_pdf()
    result = email_edit.replace_emails(original, {SALES: "ops@new-domain.test"})
    before, after = _text(original), _text(result)
    assert "ops@new-domain.test" in after[0] and "ops@new-domain.test" in after[1]
    assert SALES not in after[0] and SALES not in after[1]
    # Everything that is not the swapped address reads the same, and the other address stays.
    assert BILLING in after[0]
    assert [t.replace(SALES, "X") for t in before] == [t.replace("ops@new-domain.test", "X") for t in after]


def test_replace_keeps_pages_and_page_size():
    original = _po_pdf()
    result = email_edit.replace_emails(original, {SALES: "ops@new-domain.test"})
    old_pages, new_pages = PdfReader(io.BytesIO(original)).pages, PdfReader(io.BytesIO(result)).pages
    assert len(old_pages) == len(new_pages) == 2
    assert [tuple(p.mediabox) for p in old_pages] == [tuple(p.mediabox) for p in new_pages]


def test_replace_also_updates_the_mailto_link():
    result = email_edit.replace_emails(_po_pdf(), {SALES: "ops@new-domain.test"})
    assert _links(result) == ["mailto:ops@new-domain.test"]


def test_new_address_is_written_as_typed_without_the_sandbox_rule():
    result = email_edit.replace_emails(_po_pdf(), {SALES: "Real.Person@acme.co.uk"})
    assert "Real.Person@acme.co.uk" in _text(result)[0]
    assert "sandbox.com" not in "".join(_text(result))


def test_the_sandbox_rewrite_still_forces_sandbox_com():
    # The refactor must not change what the PO pages do.
    result = sandbox_pdf_emails(_po_pdf())
    assert "sales@sandbox.com" in _text(result)[0]
    assert SALES not in "".join(_text(result))


def test_unchanged_entry_is_not_a_change():
    with pytest.raises(ValueError, match="No address was changed"):
        email_edit.replace_emails(_po_pdf(), {SALES: SALES})


@pytest.mark.parametrize("bad", ["", "   ", "not-an-email", "a@b", "two@x.com three@y.com", "a b@c.com"])
def test_blank_or_malformed_new_address_is_rejected(bad):
    with pytest.raises(ValueError):
        email_edit.replace_emails(_po_pdf(), {SALES: bad})


def test_scan_endpoint():
    res = client.post("/api/email-editor/scan", files={"pdf": ("po.pdf", _po_pdf(), "application/pdf")})
    assert res.status_code == 200
    assert [e["address"] for e in res.json()["emails"]] == [SALES, BILLING]


def test_apply_endpoint_returns_the_edited_pdf():
    res = client.post(
        "/api/email-editor/apply",
        files={"pdf": ("My PO.pdf", _po_pdf(), "application/pdf")},
        data={"mapping": json.dumps({SALES: "ops@new-domain.test"})},
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert 'filename="My PO_emails.pdf"' in res.headers["content-disposition"]
    assert "ops@new-domain.test" in _text(res.content)[0]


def test_preview_endpoint_returns_one_png_per_page():
    res = client.post(
        "/api/email-editor/preview",
        files={"pdf": ("po.pdf", _po_pdf(), "application/pdf")},
        data={"mapping": json.dumps({SALES: "ops@new-domain.test"})},
    )
    assert res.status_code == 200
    pages = res.json()["pages"]
    assert len(pages) == 2
    for data in pages:
        assert base64.b64decode(data).startswith(b"\x89PNG")


def test_preview_shows_the_same_pdf_the_download_delivers():
    """The preview must be a render of exactly the PDF /apply returns, not a separate edit."""
    pdf = ("po.pdf", _po_pdf(), "application/pdf")
    data = {"mapping": json.dumps({SALES: "ops@new-domain.test"})}
    shown = client.post("/api/email-editor/preview", files={"pdf": pdf}, data=data).json()["pages"]
    downloaded = client.post("/api/email-editor/apply", files={"pdf": pdf}, data=data).content
    assert [base64.b64decode(p) for p in shown] == convert._render_pages(downloaded, "PNG")


def test_preview_differs_from_the_original_only_after_a_change():
    original = _po_pdf()
    before = convert._render_pages(original, "PNG")
    res = client.post(
        "/api/email-editor/preview",
        files={"pdf": ("po.pdf", original, "application/pdf")},
        data={"mapping": json.dumps({BILLING: "ap@new-domain.test"})},
    )
    after = [base64.b64decode(p) for p in res.json()["pages"]]
    assert after[0] != before[0]  # page 1 holds the changed address
    assert after[1] == before[1]  # page 2 has no BILLING address, so it is pixel-identical


@pytest.mark.parametrize("route", ["scan", "apply", "preview"])
def test_endpoints_reject_a_non_pdf(route):
    res = client.post(
        f"/api/email-editor/{route}",
        files={"pdf": ("po.pdf", b"hello", "application/pdf")},
        data={"mapping": json.dumps({SALES: "a@b.co"})} if route != "scan" else None,
    )
    assert res.status_code == 400


@pytest.mark.parametrize("route", ["apply", "preview"])
def test_apply_and_preview_reject_bad_input(route):
    pdf = ("po.pdf", _po_pdf(), "application/pdf")
    for mapping in ["not json", json.dumps([1, 2]), json.dumps({SALES: 5}), json.dumps({SALES: "nope"}), json.dumps({SALES: ""})]:
        res = client.post(f"/api/email-editor/{route}", files={"pdf": pdf}, data={"mapping": mapping})
        assert res.status_code == 400, (route, mapping)


def test_page_is_served():
    res = client.get("/email-editor")
    assert res.status_code == 200
    assert "Email Editor" in res.text


TEMPLATES = Path(__file__).parent / "data" / "templates"


def test_real_template_pdf_round_trip():
    """Smoke test on a real distributor PDF: scan, change one address, nothing else moves."""
    pdfs = sorted(p for p in TEMPLATES.glob("*/*.pdf") if p.parent.name != "Old")
    for path in pdfs:
        original = path.read_bytes()
        emails = email_edit.find_emails(original)
        if not emails:
            continue
        target = emails[0]["address"]
        result = email_edit.replace_emails(original, {target: "edited.address@example.test"})
        old_pages, new_pages = PdfReader(io.BytesIO(original)).pages, PdfReader(io.BytesIO(result)).pages
        assert len(old_pages) == len(new_pages)
        assert [tuple(p.mediabox) for p in old_pages] == [tuple(p.mediabox) for p in new_pages]
        assert target not in "".join(_text(result))
        assert "edited.address@example.test" in "".join(_text(result))
        return
    pytest.skip("no template PDF with an email address found")
