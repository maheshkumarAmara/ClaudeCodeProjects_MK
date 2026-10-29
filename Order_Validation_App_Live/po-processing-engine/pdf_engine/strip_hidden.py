"""Removes text that a generated PO hides under white boxes.

Every generator starts from the distributor's template page and merges an overlay on
top: a white box over the old value, then the new value drawn on it. The old text is
covered but still in the file, so anything that reads the PDF's text (a search, a
copy/paste, an extraction pipeline) finds the template's values as well as the new
ones. This pass walks each page's content stream, remembers every rectangle filled
white, and proposes to delete the text of any run drawn earlier that sits inside one.

A proposal is only a guess about what a viewer shows. The position rule is wrong for
some templates (Computer Gross draws its own white cell backgrounds and duplicate text
layers, so a run "under a later white box" can still be the visible one), so every page
is rendered before and after and a change is kept only if the page looks the same. When
a page differs, the proposed runs are split and re-tested so the safe ones are still
removed and the others stay. The worst case is that hidden text remains in the file.

Only the text-showing operators (Tj, TJ) of a run are removed. The box, the artwork,
the text that is not covered, and the rest of each run's block (font, colour,
marked-content markers) all stay.

Known limitations:
  - A run is positioned from its text matrix origin; a run whose origin is inside a white
    box but whose tail pokes out is kept (no visible change).
  - A block that shows several lines is judged by its first line's position only; the
    render check is what keeps it from deleting a visible line.
  - Text set through a rotated or skewed text matrix is left alone.
  - Only the page's own content stream is processed, not text inside nested forms.
  - The visual check compares renders at 1x with a small tolerance, so a change smaller
    than a couple of pixels is not noticed.
"""

import io

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream

_TEXT_SHOW = (b"Tj", b"TJ", b"'", b'"')


def _num(value) -> float:
    return float(value)


def _is_white(operands: list, operator: bytes) -> bool:
    if operator == b"g":
        return len(operands) == 1 and _num(operands[0]) == 1
    if operator == b"rg":
        return len(operands) == 3 and all(_num(v) == 1 for v in operands)
    if operator == b"k":
        return len(operands) == 4 and all(_num(v) == 0 for v in operands)
    return False


def _multiply(a, b):
    """Matrix product a x b for PDF [a b c d e f] matrices."""
    return (
        a[0] * b[0] + a[1] * b[2],
        a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2],
        a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4],
        a[4] * b[1] + a[5] * b[3] + b[5],
    )


def _rect_in_page(ctm, x, y, w, h):
    """Bounding box (x0, y0, x1, y1) of a re rectangle after the current matrix."""
    corners = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
    pts = [(ctm[0] * px + ctm[2] * py + ctm[4], ctm[1] * px + ctm[3] * py + ctm[5]) for px, py in corners]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _inside(point, box, slack: float = 0.5) -> bool:
    return box[0] - slack <= point[0] <= box[2] + slack and box[1] - slack <= point[1] <= box[3] + slack


def _candidates(operations) -> list[list[int]]:
    """For each text run that a later white box appears to cover, the indices of its
    text-showing operators (what would be removed). Nothing is changed here."""

    # Pass 1: find each text run (BT..ET) and each white-filled rectangle, with the
    # operation index where it appears, so a run is only judged against boxes that
    # come LATER in the stream (painted over it).
    runs = []      # (start_index, end_index, origin (x, y))
    whites = []    # (index, box)
    stack = []
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    fill_white = False
    fill_stack = []
    pending_rects = []
    run_start = None
    tm = None
    shows_text = False
    for index, (operands, operator) in enumerate(operations):
        if operator == b"q":
            stack.append(ctm)
            fill_stack.append(fill_white)
        elif operator == b"Q":
            if stack:
                ctm = stack.pop()
            if fill_stack:
                fill_white = fill_stack.pop()
        elif operator == b"cm" and len(operands) == 6:
            ctm = _multiply(tuple(_num(v) for v in operands), ctm)
        elif operator in (b"g", b"rg", b"k"):
            fill_white = _is_white(operands, operator)
        elif operator in (b"G", b"RG", b"K", b"sc", b"scn", b"cs", b"CS"):
            if operator in (b"sc", b"scn"):
                fill_white = len(operands) in (1, 3, 4) and all(
                    isinstance(v, (int, float)) or hasattr(v, "as_numeric") for v in operands
                ) and (
                    (len(operands) in (1, 3) and all(_num(v) == 1 for v in operands))
                    or (len(operands) == 4 and all(_num(v) == 0 for v in operands))
                )
        elif operator == b"re" and len(operands) == 4:
            pending_rects.append(_rect_in_page(ctm, *(_num(v) for v in operands)))
        elif operator in (b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"):
            if fill_white:
                for box in pending_rects:
                    whites.append((index, box))
            pending_rects = []
        elif operator in (b"n", b"S", b"s"):
            pending_rects = []
        elif operator == b"BT":
            run_start, tm, shows_text = index, [1.0, 0.0, 0.0, 1.0, 0.0, 0.0], False
        elif operator == b"Tm" and tm is not None and len(operands) == 6:
            tm = [_num(v) for v in operands]
        elif operator in (b"Td", b"TD") and tm is not None and len(operands) == 2:
            tm[4] += _num(operands[0])
            tm[5] += _num(operands[1])
        elif operator in _TEXT_SHOW and tm is not None:
            shows_text = True
        elif operator == b"ET" and run_start is not None:
            if shows_text and tm is not None:
                skewed = abs(tm[1]) > 1e-6 or abs(tm[2]) > 1e-6
                if not skewed:
                    origin = (ctm[0] * tm[4] + ctm[2] * tm[5] + ctm[4], ctm[1] * tm[4] + ctm[3] * tm[5] + ctm[5])
                    runs.append((run_start, index, origin))
            run_start, tm = None, None

    # Pass 2: a run is a candidate if a white box later in the stream contains its origin.
    # Only its text-showing operators are proposed for removal: its BT/ET, font, colour and
    # marked-content (BDC/EMC) operators stay, since a viewer pairs those across the stream
    # and a block's colour or state can carry over to what is drawn next.
    found = []
    for start, end, origin in runs:
        if any(idx > end and _inside(origin, box) for idx, box in whites):
            ops = [i for i in range(start, end + 1) if operations[i][1] in _TEXT_SHOW]
            if ops:
                found.append(ops)
    return found


# A pixel counts as changed when its grey level moves by more than this (0-255).
_PIXEL_TOLERANCE = 40
# A page may differ in at most this many pixels and still count as unchanged (anti-aliasing noise).
_MAX_CHANGED_PIXELS = 0


def _render(pdf_bytes: bytes, index: int):
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return document[index].render(scale=1.0).to_pil().convert("L")
    finally:
        document.close()


def _same_look(a, b) -> bool:
    from PIL import ImageChops

    if a.size != b.size:
        return False
    diff = ImageChops.difference(a, b).point(lambda v: 255 if v > _PIXEL_TOLERANCE else 0)
    return sum(1 for v in diff.getdata() if v) <= _MAX_CHANGED_PIXELS


def _page_bytes(writer: PdfWriter, page_number: int, operations) -> bytes:
    """A one-page PDF of this page with the given operations, for rendering."""
    single = PdfWriter(clone_from=PdfReader(io.BytesIO(_whole(writer))))
    for number in range(len(single.pages) - 1, -1, -1):
        if number != page_number:
            single.remove_page(number)
    page = single.pages[0]
    content = ContentStream(page.get_contents(), single)
    content.operations = operations
    page.replace_contents(content)
    buffer = io.BytesIO()
    single.write(buffer)
    return buffer.getvalue()


def _whole(writer: PdfWriter) -> bytes:
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _safe_subset(writer: PdfWriter, page_number: int, operations, proposals: list[list[int]]) -> list[list[int]]:
    """The proposals whose removal leaves the page looking the same (found by splitting)."""
    original = _render(_page_bytes(writer, page_number, operations), 0)

    def looks_same(chosen: list[list[int]]) -> bool:
        drop = {i for ops in chosen for i in ops}
        trimmed = [op for i, op in enumerate(operations) if i not in drop]
        return _same_look(original, _render(_page_bytes(writer, page_number, trimmed), 0))

    safe: list[list[int]] = []

    def settle(group: list[list[int]]) -> None:
        if not group:
            return
        if looks_same(group):
            safe.extend(group)
        elif len(group) > 1:
            middle = len(group) // 2
            settle(group[:middle])
            settle(group[middle:])
        # a single proposal that changes the page stays in the file

    # Removals can interact, so the union of the individually safe groups is checked once
    # more at the end; if it fails, fall back to the groups that pass one at a time.
    settle(proposals)
    if safe and not looks_same(safe):
        safe = [one for one in safe if looks_same([one])]
        while safe and not looks_same(safe):
            safe.pop()
    return safe


def strip_hidden_text(pdf_bytes: bytes) -> bytes:
    """The PDF with the text that is hidden under white boxes removed, page by page, and
    only where a render shows the page looks the same afterwards."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    changed = False
    for number, page in enumerate(writer.pages):
        contents = page.get_contents()
        if contents is None:
            continue
        content = ContentStream(contents, writer)
        operations = content.operations
        proposals = _candidates(operations)
        if not proposals:
            continue
        try:
            safe = _safe_subset(writer, number, operations, proposals)
        except Exception:
            # If the page can't be rendered to check it, leave it exactly as it is.
            continue
        if not safe:
            continue
        drop = {i for ops in safe for i in ops}
        content.operations = [op for i, op in enumerate(operations) if i not in drop]
        page.replace_contents(content)
        changed = True
    if not changed:
        return pdf_bytes
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
