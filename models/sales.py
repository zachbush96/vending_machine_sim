from typing import List, Dict, Optional
from utils.file_manager import read_json, write_json

def _sales() -> List[Dict]:
    return read_json("sales.json")

def _save_sales(s):
    write_json("sales.json", s)

def record_sale(date_iso: str, item: str, qty: int, revenue: float, cogs: float):
    s = _sales()
    s.append({
        "date": date_iso,
        "item": item,
        "qty": int(qty),
        "revenue": round(float(revenue), 4),
        "cogs": round(float(cogs), 4),
    })
    _save_sales(s)

def sales_for_date(date_iso: str) -> List[Dict]:
    return [r for r in _sales() if r.get("date") == date_iso]

def all_sales() -> List[Dict]:
    return _sales()

def cogs_per_product() -> Dict[str, float]:
    agg = {}
    for r in _sales():
        agg[r["item"]] = agg.get(r["item"], 0.0) + float(r["cogs"])
    return agg