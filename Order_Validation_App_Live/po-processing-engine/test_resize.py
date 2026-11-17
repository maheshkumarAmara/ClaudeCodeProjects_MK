"""Tests for the PDF size option on "Generate & download PDF" (pdf_engine/resize.py + /generate).

Run from this folder:  python -m pytest test_resize.py -q
"""

import io
import tempfile
from pathlib import Path

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

import config
import history
import main
from pdf_engine import extractor, resize

SLUGS = ["Ingram Micro Canada", "Computer Gross spa", "ADN Distribution GmbH", "Networld Corporation"]


def _pdf(slug: str) -> bytes:
    """The stored sample PO for a distributor, as a realistic input PDF."""
    return extractor.find_template_path(slug).read_bytes()


def _text(pdf_bytes: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def test_default_returns_the_same_bytes():
    data = _pdf("Ingram Micro Canada")
    out, info = resize.apply(data, "default")
    assert out is data
    assert info == {"original": len(data), "final": len(data), "note": ""}


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        resize.apply(b"%PDF-1.4", "huge")


@pytest.mark.parametrize("slug", SLUGS)
def test_smaller_keeps_pages_and_text(slug):
    data = _pdf(slug)
    out, info = resize.apply(data, "smaller")
    assert len(out) <= len(data)
    assert info["final"] == len(out)
    assert len(PdfReader(io.BytesIO(out)).pages) == len(PdfReader(io.BytesIO(data)).pages)
    assert _text(out) == _text(data)


@pytest.mark.parametrize("mode,target", sorted(resize.LARGER_MODES.items()))
def test_larger_lands_on_target_and_keeps_text(mode, target):
    data = _pdf("Ingram Micro Canada")
    out, info = resize.apply(data, mode)
    assert abs(len(out) - target) <= target * 0.01
    assert info["note"] == ""
    assert len(PdfReader(io.BytesIO(out)).pages) == len(PdfReader(io.BytesIO(data)).pages)
    assert _text(out) == _text(data)


def test_larger_leaves_a_pdf_that_is_already_bigger_unchanged():
    data = resize.enlarge(_pdf("Ingram Micro Canada"), 2 * resize.MB)
    assert len(data) > resize.MB
    out, info = resize.apply(data, "larger_1mb")
    assert out is data
    assert "already larger than 1 MB" in info["note"]


@pytest.fixture
def client(monkeypatch):
    # /generate archives the PDF under data/generated/ and logs a history entry; keep both out of the real data.
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(config, "GENERATED_DIR", tmp)
    (tmp / "Ingram Micro Canada").mkdir()
    monkeypatch.setattr(history, "add", lambda *a, **k: None)
    return TestClient(main.app)


def _body(slug, **extra):
    template = extractor.parse_template(slug)
    return {"fields": template["fields"], "line_items": template["line_items"], **extra}


def test_endpoint_default_and_omitted_size_mode_are_the_same(client):
    slug = "Ingram Micro Canada"
    omitted = client.post(f"/api/distributors/{slug}/generate", json=_body(slug))
    explicit = client.post(f"/api/distributors/{slug}/generate", json=_body(slug, size_mode="default"))
    assert omitted.status_code == explicit.status_code == 200
    assert omitted.headers["X-PDF-Original-Bytes"] == omitted.headers["X-PDF-Size-Bytes"]
    assert _text(omitted.content) == _text(explicit.content)
    assert len(omitted.content) == len(explicit.content)


def test_endpoint_larger_and_header_sizes(client):
    slug = "Ingram Micro Canada"
    res = client.post(f"/api/distributors/{slug}/generate", json=_body(slug, size_mode="larger_5mb"))
    assert res.status_code == 200
    assert int(res.headers["X-PDF-Size-Bytes"]) == len(res.content)
    assert abs(len(res.content) - 5 * resize.MB) <= 5 * resize.MB * 0.01
    # The archived copy is the delivered file.
    archived = next((config.GENERATED_DIR / slug).glob("*.pdf"))
    assert archived.read_bytes() == res.content


def test_endpoint_rejects_unknown_size_mode(client):
    slug = "Ingram Micro Canada"
    res = client.post(f"/api/distributors/{slug}/generate", json=_body(slug, size_mode="huge"))
    assert res.status_code == 400
