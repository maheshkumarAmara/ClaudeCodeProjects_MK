"""Tests for the PDF Compressor (pdf_engine/compress.py + /api/compress).

Run from this folder:  python -m pytest test_compress.py -q
"""

import io
import random

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import main
from pdf_engine import compress, extractor

client = TestClient(main.app)


def _photo_pdf(pages: int = 2) -> bytes:
    """A PDF with some text and a large, noisy RGB image per page (compresses well as JPEG)."""
    rng = random.Random(1)
    image = Image.new("RGB", (1800, 1200))
    image.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(1800 * 1200)])
    image = image.filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(2))
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(612, 792))
    for n in range(pages):
        pdf.drawString(72, 740, f"Scanned page {n + 1} PO-12345")
        pdf.drawImage(ImageReader(image), 36, 100, width=540, height=360)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _text(pdf_bytes: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


@pytest.fixture(scope="module")
def photo_pdf() -> bytes:
    return _photo_pdf()


@pytest.mark.parametrize("level", compress.LEVELS)
def test_each_level_keeps_pages_and_text(photo_pdf, level):
    result, info = compress.compress(photo_pdf, level)
    assert result.startswith(b"%PDF")
    assert len(PdfReader(io.BytesIO(result)).pages) == 2
    assert _text(result) == _text(photo_pdf)
    assert info["original"] == len(photo_pdf)
    assert info["final"] == len(result) <= len(photo_pdf)


def test_image_levels_shrink_more_than_lossless(photo_pdf):
    low, _ = compress.compress(photo_pdf, "low")
    medium, _ = compress.compress(photo_pdf, "medium")
    high, _ = compress.compress(photo_pdf, "high")
    assert len(medium) < len(low)
    assert len(high) < len(medium)


def test_never_larger_than_input():
    tiny = _photo_pdf(pages=1)
    once, _ = compress.compress(tiny, "high")
    twice, info = compress.compress(once, "high")
    assert len(twice) <= len(once)
    assert info["final"] <= info["original"]


def test_sample_pos_still_compress_without_error():
    # Includes the Networld template, where pypdf refuses to decode a stream (decode limit).
    for slug in ["Networld Corporation", "ADN Distribution GmbH", "Ingram Micro Canada"]:
        data = extractor.find_template_path(slug).read_bytes()
        for level in compress.LEVELS:
            result, _ = compress.compress(data, level)
            assert len(result) <= len(data)
            assert _text(result) == _text(data)


def test_unknown_level_rejected(photo_pdf):
    with pytest.raises(ValueError):
        compress.compress(photo_pdf, "extreme")


def test_garbage_and_encrypted_pdfs_rejected():
    with pytest.raises(ValueError):
        compress.compress(b"%PDF-1.4 this is not really a pdf", "low")
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    writer.encrypt("secret")
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(ValueError, match="password"):
        compress.compress(buffer.getvalue(), "low")


# ── HTTP endpoint ──


def _post(data: bytes, name: str = "My Order.pdf", level: str = "medium"):
    return client.post("/api/compress", files={"pdf": (name, data, "application/pdf")}, data={"level": level})


def test_endpoint_returns_compressed_pdf(photo_pdf):
    res = _post(photo_pdf)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["content-disposition"] == 'attachment; filename="My Order_compressed.pdf"'
    assert int(res.headers["x-pdf-original-bytes"]) == len(photo_pdf)
    assert int(res.headers["x-pdf-size-bytes"]) == len(res.content) < len(photo_pdf)


def test_endpoint_batch_of_several_files_is_independent(photo_pdf):
    results = [_post(photo_pdf, name=f"po{n}.pdf") for n in range(3)] + [_post(b"not a pdf", "bad.pdf")]
    assert [r.status_code for r in results] == [200, 200, 200, 400]


def test_endpoint_rejects_bad_input(photo_pdf):
    assert _post(b"").status_code == 400
    assert _post(b"hello world").status_code == 400
    assert _post(photo_pdf, level="extreme").status_code == 400
    assert _post(b"%PDF-1.4 broken").status_code == 422
    assert _post(b"%PDF" + b"0" * (main.MAX_UPLOAD_BYTES + 1)).status_code == 413


def test_filename_is_sanitised(photo_pdf):
    res = _post(photo_pdf, name='a"b\r\nX-Evil: 1.pdf', level="low")
    assert res.status_code == 200
    assert "\n" not in res.headers["content-disposition"]
    assert '"' not in res.headers["content-disposition"].split("filename=")[1].strip('"')


def test_pages_are_served():
    assert client.get("/compressor").status_code == 200
    assert "/compressor" in client.get("/").text


# ── Target size, padding and masked images ──

MB = 1024 * 1024


def _masked_pdf() -> bytes:
    """A PDF whose image has a soft mask (like the ADN template), which pypdf reports as RGBA."""
    rng = random.Random(2)
    image = Image.new("RGBA", (1600, 900))
    image.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256), 255) for _ in range(1600 * 900)])
    image = image.filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(2))
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(612, 792))
    pdf.drawString(72, 740, "Masked image PO-777")
    pdf.drawImage(ImageReader(image), 36, 100, width=540, height=300, mask="auto")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def test_masked_image_is_recompressed_and_still_renders():
    data = _masked_pdf()
    result, _ = compress.compress(data, "medium")
    assert len(result) < len(data) * 0.6
    assert _text(result) == _text(data)
    with pdfplumber.open(io.BytesIO(result)) as pdf:
        assert len(pdf.pages[0].images) == 1
        pdf.pages[0].to_image(resolution=40)  # raises if the image object is malformed


def test_engine_padding_is_removed():
    from pdf_engine import resize

    base = _photo_pdf(pages=1)
    padded = resize.enlarge(base, 3 * MB + len(base))
    assert len(padded) > 3 * MB
    result, _ = compress.compress(padded, "low")
    assert len(result) <= len(base)
    assert _text(result) == _text(base)


@pytest.mark.parametrize("target_mb", [3.0, 1.0, 0.3])
def test_target_size_is_met_when_images_allow_it(photo_pdf, target_mb):
    result, info = compress.compress(photo_pdf, "low", int(target_mb * MB))
    assert len(result) <= target_mb * MB
    assert info["note"] == ""
    assert _text(result) == _text(photo_pdf)


def test_target_not_reachable_returns_smallest_and_says_so():
    data = _photo_pdf(pages=1)
    result, info = compress.compress(data, "low", 1000)  # 1 KB is impossible
    assert len(result) < len(data)
    assert "Could not reach" in info["note"]


def test_text_only_pdf_cannot_reach_tiny_target():
    from pdf_engine import extractor

    data = extractor.find_template_path("Ingram Micro Canada").read_bytes()
    result, info = compress.compress(data, "low", 1000)
    assert len(result) <= len(data)
    assert "Could not reach" in info["note"]


def test_pdf_already_under_target_is_untouched(photo_pdf):
    result, info = compress.compress(photo_pdf, "low", compress.MAX_TARGET_BYTES)
    assert result == photo_pdf
    assert "Already under" in info["note"]


def test_bad_targets_rejected(photo_pdf):
    for bad in (0, -5, compress.MAX_TARGET_BYTES + 1):
        with pytest.raises(ValueError):
            compress.compress(photo_pdf, "low", bad)


def test_endpoint_target_mb(photo_pdf):
    res = client.post("/api/compress", files={"pdf": ("a.pdf", photo_pdf, "application/pdf")},
                      data={"level": "low", "target_mb": "1"})
    assert res.status_code == 200
    assert len(res.content) <= 1 * MB
    for bad in ("abc", "0", "-1", "21"):
        res = client.post("/api/compress", files={"pdf": ("a.pdf", photo_pdf, "application/pdf")},
                          data={"level": "low", "target_mb": bad})
        assert res.status_code == 400, bad
