from typing import Dict, List
from utils.file_manager import read_json, write_json

def _fin() -> Dict[str, Dict]:
    return read_json("financials.json")

def _save_fin(f):
    write_json("financials.json", f)

def update_daily(date_iso: str, sales_records: List[Dict], expenses_cfg: Dict[str, float]):
    revenue = sum(float(r["revenue"]) for r in sales_records)
    cogs = sum(float(r["cogs"]) for r in sales_records)
    expenses = sum(float(v) for v in expenses_cfg.values())
    profit = revenue - (cogs + expenses)
    f = _fin()
    f[date_iso] = {
        "revenue": round(revenue, 4),
        "cogs": round(cogs, 4),
        "expenses": round(expenses, 4),
        "profit": round(profit, 4),
    }
    _save_fin(f)
    return f[date_iso]

def get_daily(date_iso: str):
    return _fin().get(date_iso)

def latest_day() -> str:
    f = _fin()
    if not f:
        return None
    # lexicographic works for YYYY-MM-DD keys
    return sorted(f.keys())[-1]

def aggregate_profitability():
    f = _fin()
    if not f:
        return {"total": {"revenue":0,"cogs":0,"expenses":0,"profit":0}, "per_day": {}}
    total = {"revenue":0.0,"cogs":0.0,"expenses":0.0,"profit":0.0}
    for v in f.values():
        total["revenue"] += float(v["revenue"])
        total["cogs"] += float(v["cogs"])
        total["expenses"] += float(v["expenses"])
        total["profit"] += float(v["profit"])
    # round
    for k in total:
        total[k] = round(total[k], 4)
    return {"total": total, "per_day": f}