from datetime import datetime, date
from typing import Dict, Optional
from utils.file_manager import read_json, write_json

def get_inventory() -> Dict:
    return read_json("inventory.json")

def save_inventory(inv: Dict):
    write_json("inventory.json", inv)

def get_prices() -> Dict[str, float]:
    inv = get_inventory()
    return {k: v.get("sell_price", 0.0) for k, v in inv.items()}

def set_price(item: str, price: float):
    inv = get_inventory()
    if item not in inv:
        raise ValueError(f"Unknown item: {item}")
    inv[item]["sell_price"] = float(price)
    save_inventory(inv)

def adjust_prices(prices: Dict[str, float]):
    inv = get_inventory()
    for item, price in prices.items():
        if item in inv:
            inv[item]["sell_price"] = float(price)
    save_inventory(inv)

def place_order(item: str, qty: int, today_iso: str, min_qty: int, lead_time_days: int):
    inv = get_inventory()
    if item not in inv:
        raise ValueError(f"Unknown item: {item}")
    if qty < min_qty:
        raise ValueError(f"Minimum order quantity is {min_qty}")
    # If there's already pending, accumulate quantity and keep the earliest ETA
    existing_eta = inv[item].get("restock_eta")
    if existing_eta:
        inv[item]["restock_pending"] += int(qty)
    else:
        inv[item]["restock_pending"] = int(qty)
        eta = datetime.fromisoformat(today_iso).date()
        eta = eta.fromordinal(eta.toordinal() + int(lead_time_days))
        inv[item]["restock_eta"] = eta.isoformat()
    save_inventory(inv)
    return {"item": item, "restock_pending": inv[item]["restock_pending"], "restock_eta": inv[item]["restock_eta"]}

def apply_restocks(upto_date_iso: str):
    """Apply any pending orders with ETA <= upto_date_iso"""
    inv = get_inventory()
    applied = []
    upto = datetime.fromisoformat(upto_date_iso).date()
    for item, data in inv.items():
        eta = data.get("restock_eta")
        pending = int(data.get("restock_pending", 0) or 0)
        if pending > 0 and eta:
            eta_date = datetime.fromisoformat(eta).date()
            if eta_date <= upto:
                data["stock"] = int(data.get("stock", 0)) + pending
                data["restock_pending"] = 0
                data["restock_eta"] = None
                applied.append({"item": item, "qty": pending, "applied_on_or_before": upto_date_iso})
    if applied:
        save_inventory(inv)
    return applied

def deduct_stock(item: str, qty: int) -> bool:
    inv = get_inventory()
    if item not in inv:
        return False
    if inv[item]["stock"] >= qty:
        inv[item]["stock"] -= qty
        save_inventory(inv)
        return True
    return False

def add_stock(item: str, qty: int):
    inv = get_inventory()
    if item not in inv:
        raise ValueError(f"Unknown item: {item}")
    inv[item]["stock"] += int(qty)
    save_inventory(inv)

def get_cost_price(item: str) -> float:
    inv = get_inventory()
    if item not in inv:
        raise ValueError(f"Unknown item: {item}")
    return float(inv[item]["cost_price"])