import random
from datetime import datetime, timedelta, date
from typing import Dict, List
from utils.file_manager import (
    read_json,
    write_json,
    today_from_config,
    set_current_date,
    advance_one_day,
    set_last_simulated_date,
)
from models.inventory import get_inventory, deduct_stock, get_cost_price, apply_restocks
from models.sales import record_sale
from models.financials import update_daily

def _sales_volume_bounds(cfg, dow: int) -> int:
    minv = int(cfg["sales_simulation"]["min_sales_per_day"])
    maxv = int(cfg["sales_simulation"]["max_sales_per_day"])
    mult = float(cfg["sales_simulation"]["dow_multipliers"].get(str(dow), 1.0))
    base = random.randint(minv, maxv)
    vol = int(round(base * mult))
    return max(vol, 0)

def _pick_item(inv: Dict[str, Dict], price_limit: float) -> str:
    """Choose a random item that is in stock and priced within limit."""
    candidates = [
        k
        for k, v in inv.items()
        if int(v.get("stock", 0)) > 0 and float(v.get("sell_price", 0.0)) <= price_limit
    ]
    if not candidates:
        return None
    return random.choice(candidates)

def simulate_day() -> Dict:
    """Simulate a single day; returns summary dict for that processed date."""
    cfg = read_json("config.json")
    simulated_date = cfg["simulation"]["current_date"]
    dt = datetime.fromisoformat(simulated_date).date()
    dow = dt.weekday()

    # Apply any pending restocks that are due
    restocks = apply_restocks(simulated_date)

    inv = get_inventory()
    sales_records = []
    sales_count = _sales_volume_bounds(cfg, dow)
    price_limit = float(cfg["sales_simulation"].get("max_affordable_price", float("inf")))

    for _ in range(sales_count):
        item = _pick_item(inv, price_limit)
        if not item:
            break  # nothing affordable or all out of stock
        # sell one unit at a time to allow distribution
        if deduct_stock(item, 1):
            inv = get_inventory()  # reload since deducted
            sell_price = float(inv[item]["sell_price"])
            cost_price = float(inv[item]["cost_price"])
            record_sale(simulated_date, item, 1, revenue=sell_price, cogs=cost_price)

    # Recompute sales_records for the date
    from models.sales import sales_for_date
    sales_records = sales_for_date(simulated_date)

    # Update financials
    fin = update_daily(simulated_date, sales_records, cfg["operating_expenses"])

    # Advance day pointer
    set_last_simulated_date(simulated_date)
    next_day = advance_one_day(simulated_date)
    set_current_date(next_day)

    return {
        "date": simulated_date,
        "sales_count": sum(r["qty"] for r in sales_records),
        "revenue": fin["revenue"],
        "cogs": fin["cogs"],
        "expenses": fin["expenses"],
        "profit": fin["profit"],
        "restocks_applied": restocks
    }
