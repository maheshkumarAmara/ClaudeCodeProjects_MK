"""Run history and scenario-matrix files under data/."""

import json
from pathlib import Path

# Same folder as before: <project root>/data (this file is one level down, in ov/).
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE = DATA_DIR / "history.json"
MATRIX_FILE = DATA_DIR / "fulfillment_matrix.json"

_DEFAULT_MATRIX_ROWS = [
    {"Scenario Key": "1A", "Booking Bucket": "1st of the Month",         "Fulfillment Date": "1st of the same month",            "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "Order Fulfillment Date"},
    {"Scenario Key": "1A", "Booking Bucket": "After 1st of the Month",   "Fulfillment Date": "After 1st of the same Month",      "Support Start": "1st of the Following Month", "Support End": "End of term", "New Ent Start": "1st of the Following Month", "New Ent End": "End of term", "Old Ent Termination": "New Ent start date - 1"},
    {"Scenario Key": "1A", "Booking Bucket": "Booked in Previous Month", "Fulfillment Date": "FF on any date in following Month", "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "Order Fulfillment Date - 1"},
    {"Scenario Key": "1B", "Booking Bucket": "1st of the Month",         "Fulfillment Date": "1st of the same month",            "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of term"},
    {"Scenario Key": "1B", "Booking Bucket": "After 1st of the Month",   "Fulfillment Date": "After 1st of the same Month",      "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of term"},
    {"Scenario Key": "1B", "Booking Bucket": "Booked in Previous Month", "Fulfillment Date": "FF on any date in following Month", "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of term"},
    {"Scenario Key": "1D", "Booking Bucket": "1st of the Month",         "Fulfillment Date": "1st of the same month",            "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of Paid Term"},
    {"Scenario Key": "1D", "Booking Bucket": "After 1st of the Month",   "Fulfillment Date": "After 1st of the same Month",      "Support Start": "1st of the Following Month", "Support End": "End of term", "New Ent Start": "1st of the Following Month", "New Ent End": "End of term", "Old Ent Termination": "New Ent start date - 1"},
    {"Scenario Key": "1D", "Booking Bucket": "Booked in Previous Month", "Fulfillment Date": "FF on any date in following Month", "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of Paid Term"},
    {"Scenario Key": "2A", "Booking Bucket": "1st of the Month",         "Fulfillment Date": "1st of the same month",            "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "Order Fulfillment Date"},
    {"Scenario Key": "2A", "Booking Bucket": "After 1st of the Month",   "Fulfillment Date": "After 1st of the same Month",      "Support Start": "1st of the Following Month", "Support End": "End of term", "New Ent Start": "1st of the Following Month", "New Ent End": "End of term", "Old Ent Termination": "New Ent start date - 1"},
    {"Scenario Key": "2A", "Booking Bucket": "Booked in Previous Month", "Fulfillment Date": "FF on any date in following Month", "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "Order Fulfillment Date - 1"},
    {"Scenario Key": "2B", "Booking Bucket": "1st of the Month",         "Fulfillment Date": "1st of the same month",            "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of term"},
    {"Scenario Key": "2B", "Booking Bucket": "After 1st of the Month",   "Fulfillment Date": "After 1st of the same Month",      "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of term"},
    {"Scenario Key": "2B", "Booking Bucket": "Booked in Previous Month", "Fulfillment Date": "FF on any date in following Month", "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of term"},
    {"Scenario Key": "2D", "Booking Bucket": "1st of the Month",         "Fulfillment Date": "1st of the same month",            "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of Paid Term"},
    {"Scenario Key": "2D", "Booking Bucket": "After 1st of the Month",   "Fulfillment Date": "After 1st of the same Month",      "Support Start": "1st of the Following Month", "Support End": "End of term", "New Ent Start": "1st of the Following Month", "New Ent End": "End of term", "Old Ent Termination": "New Ent start date - 1"},
    {"Scenario Key": "2D", "Booking Bucket": "Booked in Previous Month", "Fulfillment Date": "FF on any date in following Month", "Support Start": "Order Fulfillment Date",     "Support End": "End of term", "New Ent Start": "Order Fulfillment Date",     "New Ent End": "End of term", "Old Ent Termination": "End of Paid Term"},
]


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2))


def _load_fulfillment_matrix() -> dict:
    rows = _read_json(MATRIX_FILE, _DEFAULT_MATRIX_ROWS)
    return {
        (r["Scenario Key"], r["Booking Bucket"]): {
            k: v for k, v in r.items() if k not in ("Scenario Key", "Booking Bucket")
        }
        for r in rows
    }


def load_history() -> list:
    return _read_json(HISTORY_FILE, [])


def append_history(run: dict):
    history = load_history()
    history.append(run)
    _write_json(HISTORY_FILE, history[-50:])
