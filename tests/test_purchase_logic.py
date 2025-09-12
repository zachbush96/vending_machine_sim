import utils.file_manager as fm

def setup_env(tmp_path, monkeypatch):
    monkeypatch.setattr(fm, "_DATA_DIR", tmp_path / "data")
    fm.ensure_defaults()
    cfg = fm.read_json("config.json")
    cfg["sales_simulation"]["min_sales_per_day"] = 1
    cfg["sales_simulation"]["max_sales_per_day"] = 1
    cfg["sales_simulation"]["max_affordable_price"] = 2.0
    fm.write_json("config.json", cfg)
    return cfg


def test_no_purchase_when_price_high_or_out_of_stock(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    inv = fm.read_json("inventory.json")
    for item in inv:
        inv[item]["stock"] = 0
    inv["Coke"]["stock"] = 5
    inv["Coke"]["sell_price"] = 10.0  # overpriced
    inv["Chips"]["stock"] = 0  # out of stock (redundant but explicit)
    fm.write_json("inventory.json", inv)

    from simulation import simulate_day

    summary = simulate_day()
    assert summary["sales_count"] == 0
    assert fm.read_json("sales.json") == []
    inv_after = fm.read_json("inventory.json")
    assert inv_after["Coke"]["stock"] == 5


def test_purchase_when_affordable_and_in_stock(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    inv = fm.read_json("inventory.json")
    for item in inv:
        inv[item]["stock"] = 0
    inv["Coke"]["stock"] = 5
    inv["Coke"]["sell_price"] = 1.5
    fm.write_json("inventory.json", inv)

    from simulation import simulate_day

    summary = simulate_day()
    assert summary["sales_count"] == 1
    inv_after = fm.read_json("inventory.json")
    assert inv_after["Coke"]["stock"] == 4
    sales = fm.read_json("sales.json")
    assert len(sales) == 1 and sales[0]["item"] == "Coke"

