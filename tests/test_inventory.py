import json, os
from utils.file_manager import ensure_defaults, read_json, write_json
from models.inventory import place_order, apply_restocks, get_inventory

def test_order_and_restock_flow(tmp_path, monkeypatch):
    # Redirect data dir by monkeypatching utils.file_manager's _DATA_DIR
    import utils.file_manager as fm
    monkeypatch.setattr(fm, "_DATA_DIR", tmp_path / "data")
    fm.ensure_defaults()

    cfg = fm.read_json("config.json")
    today = cfg["simulation"]["current_date"]
    res = place_order("Coke", 10, today, min_qty=5, lead_time_days=0)
    assert res["restock_pending"] == 10
    # Same-day restock since lead_time_days=0
    applied = apply_restocks(today)
    assert applied and applied[0]["item"] == "Coke"
    inv = get_inventory()
    assert inv["Coke"]["stock"] == 30  # default 20 + 10