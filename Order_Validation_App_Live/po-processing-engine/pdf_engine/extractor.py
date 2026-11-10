"""Reads a distributor's template PDF back into an editable JSON shape.

Used to pre-fill the edit form: walks each `FieldBox` in the distributor's
`DistributorLayout` and slices the matching words out of the PDF via
pdfplumber, then walks the line-items table the same way.

Note: descriptions that wrap across multiple lines in the source PDF are
joined best-effort. Some distributor print engines omit a real space
between a wrapped line's end and the next line's start, so a wrapped
description may come back mildly garbled — acceptable since the value is
only a pre-fill; the user reviews/edits it in the form before regenerating.
"""

import contextvars
from pathlib import Path

import pdfplumber

import config
from distributors import get_layout, get_parser
from pdf_engine.models import DistributorLayout, FieldBox, TableLayout


def find_template_path(slug: str) -> Path | None:
    folder = config.TEMPLATES_DIR / slug
    if not folder.is_dir():
        return None
    # Case-insensitive, so a sample saved as "....PDF" is found like "....pdf".
    pdfs = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    return pdfs[0] if pdfs else None


def _words_in_box(words: list[dict], box: FieldBox) -> str:
    matched = [
        w
        for w in words
        if w["top"] >= box.top - 1
        and w["bottom"] <= box.bottom + 1
        and w["x0"] >= box.x0 - 1
        and w["x1"] <= box.x1 + 1
    ]
    if not matched:
        return ""
    if box.multiline:
        lines: dict[float, list[dict]] = {}
        for w in matched:
            lines.setdefault(round(w["top"]), []).append(w)
        ordered_tops = sorted(lines)
        return "\n".join(
            " ".join(w["text"] for w in sorted(lines[t], key=lambda w: w["x0"]))
            for t in ordered_tops
        )
    matched.sort(key=lambda w: (round(w["top"]), w["x0"]))
    return " ".join(w["text"] for w in matched)


def _extract_fields(pdf, layout: DistributorLayout) -> dict:
    values: dict[str, str] = {}
    all_boxes = layout.header_fields + layout.info_panel_fields + layout.trailer_fields
    for page_index, page in enumerate(pdf.pages):
        boxes_on_page = [b for b in all_boxes if b.page == page_index]
        if not boxes_on_page:
            continue
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
        for box in boxes_on_page:
            value = _words_in_box(words, box)
            if value and not values.get(box.key):
                values[box.key] = value
            values.setdefault(box.key, values.get(box.key, ""))
    return values


def _cluster_rows_by_top(words: list[dict], tolerance: float = 2.0) -> list[tuple[float, list[dict]]]:
    """Groups words into visual rows, tolerating small top-offsets.

    Words on the same printed line can differ in `top` by a fraction of a
    point (numbers and text are sometimes set in slightly different fonts
    sharing one baseline), so an exact-equality grouping incorrectly splits
    one logical row into two. Rows in this table are otherwise separated by
    at least ~11pt, so a small tolerance safely merges same-line words
    without merging distinct rows.
    """
    ordered = sorted(words, key=lambda w: w["top"])
    clusters: list[list] = []
    for w in ordered:
        if clusters and w["top"] - clusters[-1][0] <= tolerance:
            clusters[-1][1].append(w)
        else:
            clusters.append([w["top"], [w]])
    return [(top, ws) for top, ws in clusters]


def _looks_like_terms(row_words: list[dict], terms_label: str | None) -> bool:
    """Whether a lookahead row's text looks like the terms line.

    When `terms_label` is None (the original arrow-ecs-sau behavior), any
    sufficiently close row is accepted unconditionally — pure proximity.
    Otherwise, the row's words (concatenated without spaces, since some
    print engines split a label like "Terms:" across two word tokens) must
    start with the given label, case-insensitively.
    """
    if terms_label is None:
        return True
    text = "".join(w["text"] for w in sorted(row_words, key=lambda w: w["x0"])).strip().lower()
    return text.startswith(terms_label.lower())


def _extract_line_items(pdf, layout: DistributorLayout) -> list[dict]:
    table: TableLayout = layout.table
    page = pdf.pages[layout.items_page_template_index]
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)

    body_words = [
        w
        for w in words
        if table.header_top + 15 < w["top"] < table.items_page_max_row_bottom + 6
    ]

    rows = _cluster_rows_by_top(body_words)

    items: list[dict] = []
    i = 0
    while i < len(rows):
        top, row_words = rows[i]
        item = {}
        for col in table.columns:
            col_words = sorted(
                (w for w in row_words if w["x0"] >= col.x0 - 2 and w["x1"] <= col.x1 + 2),
                key=lambda w: w["x0"],
            )
            item[col.key] = " ".join(w["text"] for w in col_words)
        item["terms"] = ""

        if (
            i + 1 < len(rows)
            and rows[i + 1][0] - top <= table.terms_line_height + 2
            and _looks_like_terms(rows[i + 1][1], table.terms_label)
        ):
            _, terms_words = rows[i + 1]
            item["terms"] = " ".join(w["text"] for w in sorted(terms_words, key=lambda w: w["x0"]))
            i += 1
        elif (
            table.terms_label
            and i + 2 < len(rows)
            and rows[i + 2][0] - top <= table.row_line_height + table.terms_line_height + 4
            and _looks_like_terms(rows[i + 2][1], table.terms_label)
        ):
            # Some distributors wrap a code column (e.g. part_number) across
            # this continuation row too, mid-token (no space), alongside the
            # description continuation (space-joined) -- merge whichever
            # columns actually have continuation words here.
            _, continuation_words = rows[i + 1]
            for col in table.columns:
                col_cont = sorted(
                    (w for w in continuation_words if w["x0"] >= col.x0 - 2 and w["x1"] <= col.x1 + 2),
                    key=lambda w: w["x0"],
                )
                if not col_cont:
                    continue
                continuation_text = " ".join(w["text"] for w in col_cont)
                if col.key == "part_number":
                    item[col.key] = f"{item.get(col.key, '')}{continuation_text}"
                else:
                    item[col.key] = f"{item.get(col.key, '')} {continuation_text}".strip()
            _, terms_words = rows[i + 2]
            item["terms"] = " ".join(w["text"] for w in sorted(terms_words, key=lambda w: w["x0"]))
            i += 2
        elif (
            table.terms_label
            and i + 1 < len(rows)
            and rows[i + 1][0] - top <= table.row_line_height + 2
        ):
            # A continuation row with no terms row after it on this page --
            # e.g. the last item's terms line overflows onto the trailer
            # page. Still merge the continuation text; leave terms blank.
            _, continuation_words = rows[i + 1]
            for col in table.columns:
                col_cont = sorted(
                    (w for w in continuation_words if w["x0"] >= col.x0 - 2 and w["x1"] <= col.x1 + 2),
                    key=lambda w: w["x0"],
                )
                if not col_cont:
                    continue
                continuation_text = " ".join(w["text"] for w in col_cont)
                if col.key == "part_number":
                    item[col.key] = f"{item.get(col.key, '')}{continuation_text}"
                else:
                    item[col.key] = f"{item.get(col.key, '')} {continuation_text}".strip()
            i += 1

        if item.get("part_number") or item.get("description"):
            items.append(item)
        i += 1

    return items


def parse_template(slug: str) -> dict:
    path = find_template_path(slug)
    if path is None:
        raise FileNotFoundError(f"No template PDF found for distributor '{slug}'")
    return parse_pdf(slug, path)


def _is_white(color) -> bool:
    """True for a white fill, given as a float (grayscale) or a 1-, 3- or 4-number tuple (gray, RGB, CMYK)."""
    if color is None:
        return False
    if isinstance(color, (int, float)):
        return color == 1
    values = tuple(color)
    if len(values) == 4:  # CMYK: white is no ink at all
        return all(v == 0 for v in values)
    return bool(values) and all(v == 1 for v in values)

# Set per request (and per thread / task) by parse_pdf(visible_only=True); read by open_pdf().
_visible_only: contextvars.ContextVar[bool] = contextvars.ContextVar("visible_only", default=False)


def _covered_by_later_fill(page) -> set[int]:
    """ids of the page's chars that a filled box drawn after them paints over.

    Reads the page in paint order (pdfplumber lists chars and rects in content-stream
    order), so it needs no font or position guess: a char is hidden when a LATER filled
    box covers its centre. This catches a template run that only partly sits under the
    box, such as the "Q-" of "Quote number : Q-" under a regenerated quote number, and
    boxes that are panel grey rather than white (the PO date). Spaces are kept so the
    words around a replaced value still read as separate words.
    """
    from pdfminer.layout import LTChar, LTRect

    chars = iter(page.chars)
    sequence = []  # ("char", dict) / ("box", bounds) in paint order
    for obj in page.layout:
        if isinstance(obj, LTChar):
            sequence.append(("char", next(chars, None)))
        elif isinstance(obj, LTRect) and obj.fill:
            sequence.append(("box", (obj.x0, page.height - obj.y1, obj.x1, page.height - obj.y0)))
    hidden: set[int] = set()
    later_boxes: list[tuple] = []
    for kind, item in reversed(sequence):
        if kind == "box":
            later_boxes.append(item)
        elif item is not None and item["text"].strip():
            if any(_covers_char(box, item) for box in later_boxes):
                hidden.add(id(item))
    return hidden


def _covers_char(box: tuple, char: dict) -> bool:
    """True if the box is a patch over the char: it holds the char's centre and spans most
    of its height. A hairline rule (drawn as a filled rectangle) or a panel far taller than
    the text is artwork, not a cover, and the text beside it stays visible."""
    x0, top, x1, bottom = box
    cx = (char["x0"] + char["x1"]) / 2
    height = char["bottom"] - char["top"]
    box_height = bottom - top
    if not (x0 <= cx <= x1 and top - 1 <= char["top"] and char["bottom"] <= bottom + 1):
        return False
    return box_height <= 3 * height


def _visible_page(page):
    """The page without the original text that a generated PO hides under boxes.

    A PO this engine generated draws new text over boxes that cover the template's
    original text but leaves that original text in the file, so reading every character
    doubles each value ("Q-960271" reads "QQ--960271"). On a page with Helvetica text
    (the generators' font) two rules find the covered text: any char that a filled box
    drawn after it covers (paint order), and any non-Helvetica char under a white box.
    A page with no Helvetica text, such as a PO straight from a distributor, is
    returned unchanged.
    """
    if not any("Helvetica" in c["fontname"] for c in page.chars):
        return page
    try:
        covered = _covered_by_later_fill(page)
    except Exception:  # an unusual page: fall back to the font rule alone
        covered = set()
    whites = [r for r in page.rects if r.get("fill") and _is_white(r.get("non_stroking_color"))]

    def hidden(c) -> bool:
        if id(c) in covered:
            return True
        if "Helvetica" in c["fontname"]:
            return False
        cx, cy = (c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2
        return any(r["x0"] <= cx <= r["x1"] and r["top"] <= cy <= r["bottom"] for r in whites)

    return page.filter(lambda o: o.get("object_type") != "char" or not hidden(o))


class _VisibleDocument:
    """A pdfplumber PDF whose pages expose only the visible text (see _visible_page)."""

    def __init__(self, pdf):
        self._pdf = pdf
        self.pages = [_visible_page(p) for p in pdf.pages]

    def __getattr__(self, name):
        return getattr(self._pdf, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._pdf.__exit__(*exc)


def open_pdf(path):
    """pdfplumber.open() for the parsers: the visible text only while parse_pdf(visible_only=True) runs."""
    pdf = pdfplumber.open(path)
    return _VisibleDocument(pdf) if _visible_only.get() else pdf


def parse_pdf(slug: str, path: Path, visible_only: bool = False) -> dict:
    """Parses any PDF of this distributor's layout (the stored sample, or an uploaded PO).

    With visible_only=True the parser sees just the text a viewer would see, which is
    what an uploaded, already-generated PO needs (see _visible_page).
    """
    token = _visible_only.set(visible_only)
    try:
        return _parse_pdf(slug, path)
    finally:
        _visible_only.reset(token)


def _parse_pdf(slug: str, path: Path) -> dict:
    parser = get_parser(slug)
    if parser is not None:
        result = parser(path)
        result.setdefault("hidden_fields", [])
        return result

    layout = get_layout(slug)
    if layout is None:
        raise LookupError(f"No layout configured yet for distributor '{slug}'")

    with open_pdf(path) as pdf:
        fields = _extract_fields(pdf, layout)
        line_items = _extract_line_items(pdf, layout)

    return {
        "fields": fields,
        "line_items": line_items,
        "hidden_fields": sorted(layout.hidden_field_keys),
    }
