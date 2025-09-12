from utils.file_manager import ensure_defaults, read_json, write_json
from models.sales import record_sale, sales_for_date, cogs_per_product

def test_sales_record_and_query(tmp_path, monkeypatch):
    import utils.file_manager as fm
    monkeypatch.setattr(fm, "_DATA_DIR", tmp_path / "data")
    fm.ensure_defaults()

    record_sale("2025-09-01", "Coke", 2, revenue=2.50, cogs=1.0)
    record_sale("2025-09-01", "Chips", 1, revenue=1.00, cogs=0.3)

    rows = sales_for_date("2025-09-01")
    assert len(rows) == 2
    cogs = cogs_per_product()
    assert round(cogs["Coke"], 2) == 1.0
    assert round(cogs["Chips"], 2) == 0.3