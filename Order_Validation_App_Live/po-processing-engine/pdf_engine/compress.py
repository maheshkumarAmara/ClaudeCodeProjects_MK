"""Compresses any uploaded PDF for the PDF Compressor page.

  low     lossless: recompress content streams, merge identical objects, drop unreferenced ones
          (resize.shrink). Text, images and the way the pages look are unchanged.
  medium  low, plus embedded images re-encoded as JPEG (quality 75).
  high    low, plus embedded images re-encoded as JPEG (quality 50) and downscaled to at most
          1600 px on the long side.
  target  the caller names a size in bytes; settings get stronger step by step (_TARGET_STEPS)
          and the first result that fits is returned. If none fits, the smallest is returned
          and the note says so.

Every level first drops the engine's own "Larger: ~N MB" filler (see resize.PADDING_KEY).

Image re-encoding is best effort and per image: images with transparency or a mask, palette /
CMYK images, tiny images and images that would not get smaller are left alone, and an image
pypdf cannot decode (it refuses very large streams) is skipped without failing the file. The
result is never larger than the input.
"""

import io

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import EncodedStreamObject, NameObject, NumberObject

from pdf_engine import resize

LEVELS = ("low", "medium", "high")
MAX_TARGET_BYTES = 20 * 1024 * 1024

# level -> (JPEG quality, longest side in px or None for "don't resize")
_IMAGE_SETTINGS = {
    "medium": (75, None),
    "high": (50, 1600),
}
# Gentle to harsh, for a target size. (JPEG quality, longest side in px or None)
_TARGET_STEPS = [
    (85, None), (75, None), (65, 2000), (50, 1600), (40, 1400), (30, 1100), (25, 900),
]
_MIN_IMAGE_BYTES = 10 * 1024  # re-encoding a smaller image rarely pays off


def _open(pdf_bytes: bytes) -> PdfReader:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted:
            raise ValueError("This PDF is password-protected, so it cannot be compressed.")
        len(reader.pages)  # forces the page tree to parse
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"This file could not be read as a PDF: {exc}") from exc
    return reader


def _has_mask(image_object) -> bool:
    return any(key in image_object for key in ("/SMask", "/Mask"))


def _swap_in_jpeg(writer: PdfWriter, ref, old, rgb, quality: int) -> int:
    """Replace the colour data of the image object 'old' with a JPEG of 'rgb', keeping every other
    entry (notably /SMask, which may have a different size) as is. Returns the new stream size."""
    buffer = io.BytesIO()
    rgb.save(buffer, "JPEG", quality=quality, optimize=True)
    data = buffer.getvalue()
    new = EncodedStreamObject()
    new._data = data
    for key, value in old.items():
        if key not in ("/Length", "/Filter", "/DecodeParms", "/Width", "/Height", "/ColorSpace",
                       "/BitsPerComponent", "/Decode"):
            new[NameObject(key)] = value
    new[NameObject("/Filter")] = NameObject("/DCTDecode")
    new[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")
    new[NameObject("/BitsPerComponent")] = NumberObject(8)
    new[NameObject("/Width")] = NumberObject(rgb.width)
    new[NameObject("/Height")] = NumberObject(rgb.height)
    writer._objects[ref.idnum - 1] = new
    new.indirect_reference = ref
    return len(data)


def _recompress_images(pdf_bytes: bytes, quality: int, max_side: int | None) -> bytes:
    """pdf_bytes with its embedded images re-encoded; pdf_bytes itself if nothing improved."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    seen: set[int] = set()
    changed = 0
    for page in writer.pages:
        try:
            images = list(page.images)
        except Exception:
            continue
        for image in images:
            ref = image.indirect_reference
            if ref is None or image.is_inline or ref.idnum in seen:
                continue
            seen.add(ref.idnum)
            try:
                xobject = ref.get_object()
                if len(image.data) < _MIN_IMAGE_BYTES or "/Mask" in xobject:
                    continue  # /Mask (colour-key / stencil) can't be kept valid when re-encoding
                masked = "/SMask" in xobject
                pil = image.image
                # pypdf folds an /SMask into the picture and reports RGBA; the colour part is RGB.
                if pil is None or pil.mode not in (("RGB", "RGBA") if masked else ("RGB", "L")):
                    continue  # P/CMYK/1-bit: re-encoding would change colours
                if masked:
                    pil = pil.convert("RGB")
                if max_side and max(pil.size) > max_side:
                    pil = pil.copy()
                    pil.thumbnail((max_side, max_side), Image.LANCZOS)
                try:
                    before = len(xobject._data)  # the stored (already encoded) size
                except AttributeError:
                    before = len(image.data)
                trial = io.BytesIO()
                pil.save(trial, "JPEG", quality=quality, optimize=True)
                if len(trial.getvalue()) >= before:
                    continue  # the JPEG is not smaller than what is already there
                if masked:
                    _swap_in_jpeg(writer, ref, xobject, pil, quality)
                else:
                    image.replace(pil, quality=quality)
                changed += 1
            except Exception:
                continue  # one undecodable image must not fail the whole file
    if not changed:
        return pdf_bytes
    for page in writer.pages:
        page.compress_content_streams(level=9)
    try:
        resize._merge_identical_objects(writer)  # e.g. the same template image once per page
    except Exception:
        pass
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _without_padding(pdf_bytes: bytes) -> bytes:
    """The PDF minus the engine's own size-padding stream; the input itself if it has none."""
    try:
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
        key = NameObject(resize.PADDING_KEY)
        if key not in writer._root_object:
            return pdf_bytes
        del writer._root_object[key]
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()
    except Exception:
        return pdf_bytes


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.2f} MB"


def compress(pdf_bytes: bytes, level: str = "low", target_bytes: int | None = None) -> tuple[bytes, dict]:
    """(pdf, info) for a level, or for a target size when target_bytes is given (level is then
    ignored). info = {"original": bytes, "final": bytes, "note": text}.

    Raises ValueError for an unknown level, a target outside 1 byte..20 MB, or a file that is
    not a readable, unencrypted PDF."""
    if target_bytes is None and level not in LEVELS:
        raise ValueError(f"Unknown compression level '{level}'. Choose one of: {', '.join(LEVELS)}.")
    if target_bytes is not None and not 0 < target_bytes <= MAX_TARGET_BYTES:
        raise ValueError("The target size must be between 0 and 20 MB.")
    _open(pdf_bytes)
    original = len(pdf_bytes)
    base = resize.shrink(_without_padding(pdf_bytes))  # lossless; also what "low" returns
    note = ""

    if target_bytes is not None:
        if original <= target_bytes:
            return pdf_bytes, {"original": original, "final": original,
                               "note": f"Already under {_mb(target_bytes)}, so it was not changed."}
        best = base
        for step in [None, *_TARGET_STEPS]:
            if step is None:
                candidate = base
            else:
                try:
                    candidate = _recompress_images(base, *step)
                except Exception:
                    continue
            if len(candidate) < len(best):
                best = candidate
            if len(best) <= target_bytes:
                break
        result = best
        if len(result) > target_bytes:
            note = (f"Could not reach {_mb(target_bytes)}; {_mb(len(result))} is the smallest this PDF "
                    "can be made without removing content (it has little or no image data to reduce).")
    else:
        result = base
        if level in _IMAGE_SETTINGS:
            quality, max_side = _IMAGE_SETTINGS[level]
            try:
                candidate = _recompress_images(base, quality, max_side)
                if len(candidate) < len(result):
                    result = candidate
            except Exception:
                pass  # keep the lossless result
        if len(result) >= original:
            note = "This PDF is already as small as it can be made."

    if len(result) >= original:
        result = pdf_bytes
    return result, {"original": original, "final": len(result), "note": note}
