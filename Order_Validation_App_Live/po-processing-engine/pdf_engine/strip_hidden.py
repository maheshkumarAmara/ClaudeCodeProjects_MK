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


def _is_white(operands: list, operator: bytes, cover_colors: tuple = ()) -> bool:
    """Whether this colour-setting operator selects white, or one of `cover_colors` (RGB tuples
    of a template's own background that its generator paints over old text)."""
    if operator == b"g":
        return len(operands) == 1 and _num(operands[0]) == 1
    if operator == b"rg":
        if len(operands) != 3:
            return False
        rgb = tuple(_num(v) for v in operands)
        return all(v == 1 for v in rgb) or any(_close(rgb, c) for c in cover_colors)
    if operator == b"k":
        return len(operands) == 4 and all(_num(v) == 0 for v in operands)
    return False


def _close(a: tuple, b: tuple, slack: float = 0.002) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= slack for x, y in zip(a, b))


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


def _candidates(operations, per_show: bool = False, cover_colors: tuple = ()) -> list[list[int]]:
    """For each text run that a later white box appears to cover, the indices of its
    text-showing operators (what would be removed). Nothing is changed here. A box filled
    with one of `cover_colors` counts as a cover too, like a white one.

    By default a run is judged by its final text position. With `per_show`, every Tj/TJ
    in the run is judged by its own position instead, for templates that put a whole
    page of text (header, item rows, footer) in a single BT..ET block: the final
    position there says nothing about the rows that a white box actually covers."""

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
    shows = []         # per_show: (op_index, origin) of each Tj/TJ in the current run
    line_moves = False  # per_show: the run uses T*, ' or ", whose positions aren't tracked
    run_shows = []     # per_show: (start_index, end_index, [(op_index, origin), ...]) per run
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
            fill_white = _is_white(operands, operator, cover_colors)
        elif operator in (b"G", b"RG", b"K", b"sc", b"scn", b"cs", b"CS"):
            if operator in (b"sc", b"scn"):
                fill_white = len(operands) in (1, 3, 4) and all(
                    isinstance(v, (int, float)) or hasattr(v, "as_numeric") for v in operands
                ) and (
                    (len(operands) in (1, 3) and all(_num(v) == 1 for v in operands))
                    or (len(operands) == 4 and all(_num(v) == 0 for v in operands))
                    or (len(operands) == 3 and any(_close(tuple(_num(v) for v in operands), c) for c in cover_colors))
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
            shows, line_moves = [], False
        elif operator == b"Tm" and tm is not None and len(operands) == 6:
            tm = [_num(v) for v in operands]
        elif operator in (b"Td", b"TD") and tm is not None and len(operands) == 2:
            if per_show:
                # Td moves in the text matrix's own space, so a scaled Tm (a template that sets
                # `0.24 0 0 0.24` and then offsets in 1/0.24 units) moves by offset x scale.
                tm[4] += _num(operands[0]) * tm[0] + _num(operands[1]) * tm[2]
                tm[5] += _num(operands[0]) * tm[1] + _num(operands[1]) * tm[3]
            else:
                tm[4] += _num(operands[0])
                tm[5] += _num(operands[1])
        elif operator in _TEXT_SHOW and tm is not None:
            shows_text = True
            if operator in (b"'", b'"'):
                line_moves = True
            elif not (abs(tm[1]) > 1e-6 or abs(tm[2]) > 1e-6):
                shows.append(
                    (index, (ctm[0] * tm[4] + ctm[2] * tm[5] + ctm[4], ctm[1] * tm[4] + ctm[3] * tm[5] + ctm[5]))
                )
        elif operator == b"T*" and tm is not None:
            line_moves = True
        elif operator == b"ET" and run_start is not None:
            if shows_text and tm is not None:
                skewed = abs(tm[1]) > 1e-6 or abs(tm[2]) > 1e-6
                if not skewed:
                    origin = (ctm[0] * tm[4] + ctm[2] * tm[5] + ctm[4], ctm[1] * tm[4] + ctm[3] * tm[5] + ctm[5])
                    runs.append((run_start, index, origin))
            if shows and not line_moves:
                run_shows.append((run_start, index, shows))
            run_start, tm = None, None

    # Pass 2: a run is a candidate if a white box later in the stream contains its origin.
    # Only its text-showing operators are proposed for removal: its BT/ET, font, colour and
    # marked-content (BDC/EMC) operators stay, since a viewer pairs those across the stream
    # and a block's colour or state can carry over to what is drawn next.
    found = []
    if per_show:
        # Each Tj/TJ is judged on its own: covered if a white box drawn after it holds its origin.
        for _start, _end, run in run_shows:
            for op_index, origin in run:
                if any(idx > op_index and _inside(origin, box) for idx, box in whites):
                    found.append([op_index])
        return found
    for start, end, origin in runs:
        if any(idx > end and _inside(origin, box) for idx, box in whites):
            ops = [i for i in range(start, end + 1) if operations[i][1] in _TEXT_SHOW]
            if ops:
                found.append(ops)
    return found


def _outside_clip(operations) -> list[list[int]]:
    """Each text-showing operator whose origin lies outside the clipping rectangle in force
    where it is drawn. A generator that cuts a band out of a template page does it with
    `re W n` around the whole page content, so the rest of the page's text stays in the file
    though a viewer never shows it. Nothing is changed here."""
    found = []
    stack = []  # (ctm, clip, leading) saved by q
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    clip = None  # (x0, y0, x1, y1) in page space, or None while nothing clips
    pending = []  # rectangles built since the last path-painting operator
    clip_next = False
    tm = None
    shows = []  # (op_index, origin) of each Tj/TJ in the current BT..ET
    leading = 0.0  # the text leading (TL, or set by TD) that T*, ' and " move down by
    run_clip = None

    def move(tx: float, ty: float) -> None:
        # Moves the line start by (tx, ty) in text space; tm is unskewed whenever it is used.
        tm[4] += tx * tm[0]
        tm[5] += ty * tm[3]

    def record(index: int) -> None:
        if not (abs(tm[1]) > 1e-6 or abs(tm[2]) > 1e-6):
            shows.append((index, (ctm[0] * tm[4] + ctm[2] * tm[5] + ctm[4], ctm[1] * tm[4] + ctm[3] * tm[5] + ctm[5])))

    for index, (operands, operator) in enumerate(operations):
        if operator == b"q":
            stack.append((ctm, clip, leading))
        elif operator == b"Q":
            if stack:
                ctm, clip, leading = stack.pop()
        elif operator == b"TL" and len(operands) == 1:
            leading = _num(operands[0])
        elif operator == b"cm" and len(operands) == 6:
            ctm = _multiply(tuple(_num(v) for v in operands), ctm)
        elif operator == b"re" and len(operands) == 4:
            pending.append(_rect_in_page(ctm, *(_num(v) for v in operands)))
        elif operator in (b"W", b"W*"):
            clip_next = True
        elif operator in (b"n", b"f", b"F", b"f*", b"S", b"s", b"B", b"B*", b"b", b"b*"):
            if clip_next and pending:
                # Only rectangles narrow the clip; the union of several is never smaller than the
                # real region, so the pass can only keep more text than it should, not less.
                box = (
                    min(r[0] for r in pending),
                    min(r[1] for r in pending),
                    max(r[2] for r in pending),
                    max(r[3] for r in pending),
                )
                clip = box if clip is None else (
                    max(clip[0], box[0]), max(clip[1], box[1]), min(clip[2], box[2]), min(clip[3], box[3])
                )
            pending, clip_next = [], False
        elif operator == b"BT":
            tm, shows, run_clip = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0], [], clip
        elif operator == b"Tm" and tm is not None and len(operands) == 6:
            tm = [_num(v) for v in operands]
        elif operator in (b"Td", b"TD") and tm is not None and len(operands) == 2:
            if operator == b"TD":
                leading = -_num(operands[1])
            move(_num(operands[0]), _num(operands[1]))
        elif operator == b"T*" and tm is not None:
            move(0.0, -leading)
        elif operator in (b"Tj", b"TJ") and tm is not None:
            record(index)
        elif operator in (b"'", b'"') and tm is not None:
            move(0.0, -leading)
            record(index)
        elif operator == b"ET" and tm is not None:
            if run_clip is not None:
                found.extend([i] for i, origin in shows if not _inside(origin, run_clip))
            tm = None
    return found


def _form_hidden_shows(page_operations, resources, writer) -> list[tuple[object, list[int]]]:
    """For each Form XObject the page draws (`Do`), the form and the indices of its text-showing
    operators that the clipping rectangle in force at the `Do` hides. pypdf's merge_page wraps a
    clipped template page as such a form, so a generator that cuts a band out of its template
    leaves the rest of the template's text inside the form, outside the clip. Nothing is changed."""
    found = []
    xobjects = resources.get("/XObject") if resources is not None else None
    if not xobjects:
        return found
    stack = []
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    clip = None
    pending = []
    clip_next = False
    fill_white = False
    fill_stack = []
    drawn = []  # (form, base ctm, clip at the Do, op index of the Do)
    whites = []  # (op index, box): white rectangles painted on the page
    for index, (operands, operator) in enumerate(page_operations):
        if operator == b"q":
            stack.append((ctm, clip))
            fill_stack.append(fill_white)
        elif operator == b"Q":
            if stack:
                ctm, clip = stack.pop()
            if fill_stack:
                fill_white = fill_stack.pop()
        elif operator == b"cm" and len(operands) == 6:
            ctm = _multiply(tuple(_num(v) for v in operands), ctm)
        elif operator in (b"g", b"rg", b"k"):
            fill_white = _is_white(operands, operator)
        elif operator == b"re" and len(operands) == 4:
            pending.append(_rect_in_page(ctm, *(_num(v) for v in operands)))
        elif operator in (b"W", b"W*"):
            clip_next = True
        elif operator in (b"n", b"f", b"F", b"f*", b"S", b"s", b"B", b"B*", b"b", b"b*"):
            if operator in (b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*") and fill_white:
                whites.extend((index, box) for box in pending)
            if clip_next and pending:
                box = (
                    min(r[0] for r in pending),
                    min(r[1] for r in pending),
                    max(r[2] for r in pending),
                    max(r[3] for r in pending),
                )
                clip = box if clip is None else (
                    max(clip[0], box[0]), max(clip[1], box[1]), min(clip[2], box[2]), min(clip[3], box[3])
                )
            pending, clip_next = [], False
        elif operator == b"Do" and operands:
            form = xobjects.get(operands[0])
            form = form.get_object() if form is not None else None
            if form is not None and form.get("/Subtype") == "/Form":
                drawn.append((form, ctm, clip, index))
    for form, base, form_clip, do_index in drawn:
        covers = [box for idx, box in whites if idx > do_index]
        found.append((form, _shows_hidden(ContentStream(form, writer).operations, base, form_clip, covers)))
    return found


def _shows_hidden(operations, base_ctm, clip, covers) -> list[int]:
    """Indices of the Tj/TJ/'/\" operators whose origin, placed by `base_ctm`, lies outside `clip`
    or inside one of the `covers` (white boxes the page paints after the form).
    `base_ctm` is the matrix in force where the form is drawn; the form's own cm operators stack on it."""
    outside = []
    ctm = base_ctm
    stack = []
    tm = None
    leading = 0.0
    for index, (operands, operator) in enumerate(operations):
        if operator == b"q":
            stack.append((ctm, leading))
        elif operator == b"Q":
            if stack:
                ctm, leading = stack.pop()
        elif operator == b"cm" and len(operands) == 6:
            ctm = _multiply(tuple(_num(v) for v in operands), ctm)
        elif operator == b"TL" and len(operands) == 1:
            leading = _num(operands[0])
        elif operator == b"BT":
            tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        elif operator == b"Tm" and tm is not None and len(operands) == 6:
            tm = [_num(v) for v in operands]
        elif operator in (b"Td", b"TD") and tm is not None and len(operands) == 2:
            if operator == b"TD":
                leading = -_num(operands[1])
            tm[4] += _num(operands[0]) * tm[0] + _num(operands[1]) * tm[2]
            tm[5] += _num(operands[0]) * tm[1] + _num(operands[1]) * tm[3]
        elif operator == b"T*" and tm is not None:
            tm[4] += -leading * tm[2]
            tm[5] += -leading * tm[3]
        elif operator in _TEXT_SHOW and tm is not None:
            if operator in (b"'", b'"'):
                tm[4] += -leading * tm[2]
                tm[5] += -leading * tm[3]
            if not (abs(tm[1]) > 1e-6 or abs(tm[2]) > 1e-6):
                origin = (ctm[0] * tm[4] + ctm[2] * tm[5] + ctm[4], ctm[1] * tm[4] + ctm[3] * tm[5] + ctm[5])
                outside_clip = clip is not None and not _inside(origin, clip)
                if outside_clip or any(_inside(origin, box) for box in covers):
                    outside.append(index)
        elif operator == b"ET":
            tm = None
    return outside


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


def _same_look(a, b, tolerance: int = _MAX_CHANGED_PIXELS) -> bool:
    from PIL import ImageChops

    if a.size != b.size:
        return False
    diff = ImageChops.difference(a, b).point(lambda v: 255 if v > _PIXEL_TOLERANCE else 0)
    return sum(1 for v in diff.getdata() if v) <= tolerance


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


def _safe_subset(
    writer: PdfWriter,
    page_number: int,
    operations,
    proposals: list[list[int]],
    tolerance: int = _MAX_CHANGED_PIXELS,
    already: list[list[int]] | None = None,
) -> list[list[int]]:
    """The proposals whose removal leaves the page looking the same (found by splitting).
    `already` are removals accepted earlier; they are applied to every render here, so these
    proposals are judged against the page as it now stands."""
    base = {i for ops in (already or []) for i in ops}
    original = _render(_page_bytes(writer, page_number, [op for i, op in enumerate(operations) if i not in base]), 0)

    def looks_same(chosen: list[list[int]]) -> bool:
        drop = base | {i for ops in chosen for i in ops}
        trimmed = [op for i, op in enumerate(operations) if i not in drop]
        return _same_look(original, _render(_page_bytes(writer, page_number, trimmed), 0), tolerance)

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


def _strip_forms(writer: PdfWriter, number: int, page, operations, tolerance: int) -> bool:
    """Removes, from each Form XObject on the page, the text its clip hides. A form is shared by
    reference, so the edit is checked by rendering the whole page: if it does not look the same
    afterwards, the form is put back exactly as it was. Returns whether anything was removed."""
    try:
        hidden = [(form, idx) for form, idx in _form_hidden_shows(operations, page.get("/Resources"), writer) if idx]
        if not hidden:
            return False
        before = _render(_whole_page(writer, number), 0)
        originals = []
        for form, idx in hidden:
            ops = ContentStream(form, writer).operations
            originals.append((form, form.get_data()))
            kept = ContentStream(None, writer)
            kept.operations = [op for i, op in enumerate(ops) if i not in set(idx)]
            form.set_data(kept.get_data())
        if _same_look(before, _render(_whole_page(writer, number), 0), tolerance):
            return True
        for form, data in originals:  # the render changed: undo
            form.set_data(data)
        return False
    except Exception:
        return False


def _whole_page(writer: PdfWriter, number: int) -> bytes:
    """A one-page PDF of page `number` as the writer holds it now, for rendering."""
    single = PdfWriter(clone_from=PdfReader(io.BytesIO(_whole(writer))))
    for n in range(len(single.pages) - 1, -1, -1):
        if n != number:
            single.remove_page(n)
    buffer = io.BytesIO()
    single.write(buffer)
    return buffer.getvalue()


def strip_hidden_text(
    pdf_bytes: bytes,
    per_show: bool = False,
    clipped: bool = False,
    tolerance: int = _MAX_CHANGED_PIXELS,
    cover_colors: tuple = (),
    forms: bool = False,
) -> bytes:
    """The PDF with the text that is hidden under white boxes removed, page by page, and
    only where a render shows the page looks the same afterwards. `per_show` judges each
    text-showing operator separately (see `_candidates`); `clipped` also removes text drawn
    outside the clipping rectangle in force (see `_outside_clip`). `tolerance` is how many
    pixels a removal may change and still count as unchanged. `cover_colors` are extra RGB
    fills (besides white) that a template's generator paints over old text, e.g. a green band.
    `forms` also looks inside the Form XObjects a page draws and removes the text its clipping
    rectangle hides (see `_form_hidden_shows`); the page must still render the same. All of them
    keep the strict defaults unless a template needs them (deleting a real glyph changes about
    20 pixels or more, so keep tolerance small)."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    changed = False
    for number, page in enumerate(writer.pages):
        contents = page.get_contents()
        if contents is None:
            continue
        content = ContentStream(contents, writer)
        operations = content.operations
        if forms and _strip_forms(writer, number, page, operations, tolerance):
            changed = True
        # Text outside a clip and text under a white box are checked separately, so that one
        # white-box removal that nudges a pixel can't make the check throw away the (much
        # larger) clipped group along with it.
        groups = [_candidates(operations, per_show, cover_colors)]
        if clipped:
            groups.insert(0, _outside_clip(operations))
        try:
            safe: list[list[int]] = []
            for proposals in groups:
                # Later groups are judged against the page as the earlier ones left it, and
                # skip anything an earlier group already removed.
                dropped = {i for ops in safe for i in ops}
                proposals = [p for p in proposals if not dropped.intersection(p)]
                if proposals:
                    safe.extend(_safe_subset(writer, number, operations, proposals, tolerance, already=safe))
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
