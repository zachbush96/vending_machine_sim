from models.financials import update_daily

def test_update_daily():
    recs = [
        {"revenue": 6.25, "cogs": 2.5, "qty": 5},
        {"revenue": 3.00, "cogs": 0.9, "qty": 3},
    ]
    exp = {"electricity": 1.0, "maintenance": 1.0}
    out = update_daily("2025-09-01", recs, exp)
    assert out["revenue"] == 9.25
    assert round(out["cogs"], 2) == 3.4
    assert out["expenses"] == 2.0
    assert round(out["profit"], 2) == 3.85