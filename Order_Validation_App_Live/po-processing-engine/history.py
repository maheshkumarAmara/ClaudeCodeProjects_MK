"""History of generated / converted POs, shown in the left panel of the page.

Each entry keeps the form values it was made from, so clicking it can refill the form.
Stored in data/po_history.json, newest first, capped at MAX_ENTRIES.
"""
import json
import threading
import uuid
from datetime import datetime

import config

HISTORY_FILE = config.BASE_DIR / "data" / "po_history.json"
MAX_ENTRIES = 50

_lock = threading.Lock()


def _read() -> list[dict]:
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _write(entries: list[dict]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = HISTORY_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(HISTORY_FILE)


def _quote_number(fields: dict) -> str:
    """The quote number for the entry title. Most layouts have a plain `quote_number`;
    the Exclusive Networks South Africa one only has `quote_number_line`, which carries
    its printed label ("Quote #:Q-123"), so the label is stripped."""
    plain = (fields.get("quote_number") or "").strip()
    if plain:
        return plain
    line = (fields.get("quote_number_line") or "").strip()
    return line.split(":", 1)[1].strip() if ":" in line else line


def add(slug: str, action: str, fields: dict, line_items: list[dict]) -> dict:
    entry = {
        "id": uuid.uuid4().hex[:12],
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "slug": slug,
        "distributor": config.DISTRIBUTORS.get(slug, slug),
        "action": action,
        "po_number": (fields.get("po_number") or "").strip(),
        "quote_number": _quote_number(fields),
        "fields": fields,
        "line_items": line_items,
    }
    with _lock:
        entries = _read()
        entries.insert(0, entry)
        del entries[MAX_ENTRIES:]
        _write(entries)
    return entry


def summaries() -> list[dict]:
    """The list shown in the panel: everything except the (large) form values."""
    return [
        {**{k: v for k, v in entry.items() if k not in ("fields", "line_items")}, "line_count": len(entry.get("line_items") or [])}
        for entry in _read()
    ]


def get(entry_id: str) -> dict | None:
    return next((entry for entry in _read() if entry.get("id") == entry_id), None)


def delete(entry_id: str) -> bool:
    with _lock:
        entries = _read()
        kept = [entry for entry in entries if entry.get("id") != entry_id]
        if len(kept) == len(entries):
            return False
        _write(kept)
    return True


def clear() -> None:
    with _lock:
        _write([])
