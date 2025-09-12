import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, date

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_FILE_LOCK = threading.Lock()

DEFAULTS = {
    "inventory.json": {
        "Coke":  { "stock": 20, "restock_pending": 0, "restock_eta": None, "cost_price": 0.50, "sell_price": 1.25 },
        "Chips": { "stock": 15, "restock_pending": 0, "restock_eta": None, "cost_price": 0.30, "sell_price": 1.00 },
        "Water": { "stock": 25, "restock_pending": 0, "restock_eta": None, "cost_price": 0.20, "sell_price": 1.00 },
        "Candy": { "stock": 18, "restock_pending": 0, "restock_eta": None, "cost_price": 0.15, "sell_price": 0.85 },
    },
    "sales.json": [],
    "financials.json": {},
    "config.json": {
        "operating_expenses": {
            "electricity": 1.0,
            "maintenance": 1.0
        },
        "sales_simulation": {
            "min_sales_per_day": 5,
            "max_sales_per_day": 20,
            "dow_multipliers": {  # 0=Mon ... 6=Sun
                "0": 1.0, "1": 1.0, "2": 1.05, "3": 1.05, "4": 1.1, "5": 0.9, "6": 0.85
            },
            "max_affordable_price": 2.0,
        },
        "supplier": {
            "lead_time_days": 2,
            "min_order_qty": 10
        },
        "simulation": {
            "running": True,
            "current_date": date.today().isoformat(),
            "last_simulated_date": None
        },
        "tick_seconds": 60
    }
}

def data_path(filename: str) -> str:
    os.makedirs(_DATA_DIR, exist_ok=True)
    return os.path.join(_DATA_DIR, filename)

def _atomic_write(path: str, data_obj):
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=_DATA_DIR)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data_obj, f, indent=2)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

def ensure_defaults():
    os.makedirs(_DATA_DIR, exist_ok=True)
    for fname, default in DEFAULTS.items():
        path = data_path(fname)
        if not os.path.exists(path):
            with _FILE_LOCK:
                _atomic_write(path, default)

def read_json(filename: str):
    path = data_path(filename)
    with _FILE_LOCK:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

def write_json(filename: str, obj):
    path = data_path(filename)
    with _FILE_LOCK:
        _atomic_write(path, obj)

def today_from_config() -> str:
    cfg = read_json("config.json")
    return cfg["simulation"]["current_date"]

def set_current_date(new_date_iso: str):
    cfg = read_json("config.json")
    cfg["simulation"]["current_date"] = new_date_iso
    write_json("config.json", cfg)

def set_last_simulated_date(date_iso: str):
    cfg = read_json("config.json")
    cfg["simulation"]["last_simulated_date"] = date_iso
    write_json("config.json", cfg)

def advance_one_day(date_iso: str) -> str:
    d = datetime.fromisoformat(date_iso).date()
    return (d + timedelta(days=1)).isoformat()
