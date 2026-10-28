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

from pathlib import Path

import pdfplumber

import config
from pdf_engine.layouts import get_layout
from pdf_engine.models import DistributorLayout, FieldBox, TableLayout
from pdf_engine.parsers import PARSERS


def find_template_path(slug: str) -> Path | None:
    folder = config.TEMPLATES_DIR / slug
    if not folder.is_dir():
        return None
    pdfs = sorted(folder.glob("*.pdf"))
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

    parser = PARSERS.get(slug)
    if parser is not None:
        result = parser(path)
        result.setdefault("hidden_fields", [])
        return result

    layout = get_layout(slug)
    if layout is None:
        raise LookupError(f"No layout configured yet for distributor '{slug}'")

    with pdfplumber.open(path) as pdf:
        fields = _extract_fields(pdf, layout)
        line_items = _extract_line_items(pdf, layout)

    return {
        "fields": fields,
        "line_items": line_items,
        "hidden_fields": sorted(layout.hidden_field_keys),
    }
