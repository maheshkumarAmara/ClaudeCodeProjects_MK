"""Makes a finished PO PDF smaller or larger for "Generate & download PDF".

  default  the PDF exactly as the generator produced it (nothing is touched).
  smaller  lossless: recompress content streams, merge identical objects (e.g. the template
           image ADN embeds once per page), drop unreferenced objects. Text, links and the
           way the pages look are unchanged.
  larger   pad the file up to about N MB with inert data, for testing upload / e-mail size
           limits. The padding is one stream hung off a private Catalog key that no page
           refers to, so viewers and text extraction ignore it.

Each mode returns the original bytes when it can't help (already bigger than the target, or
nothing to save), and `apply` reports what happened in `note`.
"""

import inspect
import io
import os

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

MB = 1024 * 1024
MAX_TARGET_BYTES = 100 * MB
PADDING_KEY = "/PO_Padding"

# size_mode value -> target size in bytes, for the "larger" options.
LARGER_MODES = {
    "larger_1mb": 1 * MB,
    "larger_5mb": 5 * MB,
    "larger_10mb": 10 * MB,
    "larger_25mb": 25 * MB,
}
MODES = ("default", "smaller", *LARGER_MODES)


def _serialize(writer: PdfWriter) -> bytes:
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _merge_identical_objects(writer: PdfWriter) -> None:
    """compress_identical_objects, whichever keyword names the installed pypdf uses
    (requirements.txt only asks for pypdf>=4.0.0, and 6.x renamed the arguments)."""
    params = inspect.signature(writer.compress_identical_objects).parameters
    if "remove_duplicates" in params:
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    else:
        writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)


def shrink(pdf_bytes: bytes) -> bytes:
    """A smaller, visually identical copy; the input itself if no smaller copy can be made."""
    try:
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
        for page in writer.pages:
            page.compress_content_streams(level=9)
        try:
            _merge_identical_objects(writer)
        except Exception:
            # pypdf decodes every stream to compare them and gives up on a very large one
            # (LimitReachedError on Networld's template). Keep the compressed streams and
            # skip only the merge, so a PO still gets part of the saving.
            writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
            for page in writer.pages:
                page.compress_content_streams(level=9)
        smaller = _serialize(writer)
    except Exception:
        return pdf_bytes
    return smaller if len(smaller) < len(pdf_bytes) else pdf_bytes


def _with_padding(pdf_bytes: bytes, pad_bytes: int) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    padding = DecodedStreamObject()
    # Random bytes, no /Filter: the size is exact and nothing on the way can compress it away.
    padding.set_data(os.urandom(pad_bytes))
    writer._root_object[NameObject(PADDING_KEY)] = writer._add_object(padding)
    return _serialize(writer)


def enlarge(pdf_bytes: bytes, target_bytes: int) -> bytes:
    """The PDF padded to within about 1% of target_bytes; the input itself if it is already that big."""
    target_bytes = min(target_bytes, MAX_TARGET_BYTES)
    if len(pdf_bytes) >= target_bytes:
        return pdf_bytes
    pad = target_bytes - len(pdf_bytes)
    result = pdf_bytes
    # The first pass leaves a few hundred bytes of stream/xref overhead; correct for it and
    # rebuild until the file lands on the target.
    for _ in range(3):
        result = _with_padding(pdf_bytes, max(pad, 1))
        miss = target_bytes - len(result)
        if abs(miss) <= target_bytes * 0.01:
            break
        pad += miss
        if pad < 1:
            break
    return result


def apply(pdf_bytes: bytes, mode: str) -> tuple[bytes, dict]:
    """(pdf, info) for a size_mode. info = {"original": bytes, "final": bytes, "note": text}.

    "default" returns the very same bytes object. Raises ValueError for an unknown mode."""
    if mode not in MODES:
        raise ValueError(f"Unknown PDF size option '{mode}'. Choose one of: {', '.join(MODES)}.")
    original = len(pdf_bytes)
    note = ""
    if mode == "default":
        return pdf_bytes, {"original": original, "final": original, "note": note}
    if mode == "smaller":
        result = shrink(pdf_bytes)
        if result is pdf_bytes:
            note = "The PDF could not be made any smaller."
    else:
        target = LARGER_MODES[mode]
        result = enlarge(pdf_bytes, target)
        if result is pdf_bytes:
            note = f"The PDF is already larger than {target // MB} MB, so it was not changed."
    return result, {"original": original, "final": len(result), "note": note}
