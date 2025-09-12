from flask import Flask, jsonify, request, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from utils.file_manager import ensure_defaults, read_json, write_json, today_from_config
from models.inventory import get_inventory, place_order, apply_restocks, get_prices, set_price, adjust_prices
from models.sales import sales_for_date, all_sales, cogs_per_product
from models.financials import get_daily, latest_day, aggregate_profitability
from simulation import simulate_day

ensure_defaults()
app = Flask(__name__)

scheduler = BackgroundScheduler(daemon=True)
def _schedule_job():
    cfg = read_json("config.json")
    running = bool(cfg["simulation"].get("running", True))
    seconds = int(cfg.get("tick_seconds", 60))
    if running:
        # Remove existing jobs to avoid duplicates when reloading
        for job in scheduler.get_jobs():
            scheduler.remove_job(job.id)
        scheduler.add_job(simulate_day, trigger=IntervalTrigger(seconds=seconds), id="daily_tick", replace_existing=True)
        if not scheduler.running:
            scheduler.start()

_schedule_job()

@app.get("/status")
def status():
    cfg = read_json("config.json")
    jobs = scheduler.get_jobs()
    next_run = jobs[0].next_run_time.isoformat() if jobs else None
    return jsonify({
        "simulation": cfg["simulation"],
        "tick_seconds": cfg.get("tick_seconds", 60),
        "scheduler_running": scheduler.running,
        "next_run_time": next_run
    })

@app.post("/simulate/day")
def simulate_day_endpoint():
    summary = simulate_day()
    return jsonify({"ok": True, "summary": summary})

# -------- Inventory --------
@app.get("/inventory")
def inventory_get():
    return jsonify(get_inventory())

@app.post("/inventory/order")
def inventory_order():
    data = request.get_json(force=True, silent=True) or {}
    item = data.get("item")
    qty = int(data.get("qty", 0))
    cfg = read_json("config.json")
    min_q = int(cfg["supplier"]["min_order_qty"])
    lead = int(cfg["supplier"]["lead_time_days"])
    if not item or qty <= 0:
        return jsonify({"ok": False, "error": "Provide item and positive qty."}), 400
    try:
        res = place_order(item, qty, cfg["simulation"]["current_date"], min_q, lead)
        return jsonify({"ok": True, "order": res})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@app.post("/inventory/restock")
def inventory_restock():
    cfg = read_json("config.json")
    upto = cfg["simulation"]["current_date"]
    applied = apply_restocks(upto)
    return jsonify({"ok": True, "applied": applied, "upto_date": upto})

# -------- Pricing --------
@app.get("/prices")
def prices_get():
    return jsonify(get_prices())

@app.post("/prices")
def prices_post():
    data = request.get_json(force=True, silent=True) or {}
    if "prices" in data and isinstance(data["prices"], dict):
        adjust_prices(data["prices"])
        return jsonify({"ok": True, "prices": get_prices()})
    item = data.get("item")
    price = data.get("sell_price")
    if not item or price is None:
        return jsonify({"ok": False, "error": "Provide either 'prices' dict or 'item' and 'sell_price'."}), 400
    try:
        set_price(item, float(price))
        return jsonify({"ok": True, "prices": get_prices()})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

# -------- Sales --------
@app.get("/sales/today")
def sales_today():
    # "Today" means the last fully simulated day
    cfg = read_json("config.json")
    day = cfg["simulation"]["last_simulated_date"] or latest_day()
    if not day:
        return jsonify({"ok": True, "date": None, "sales": []})
    return jsonify({"ok": True, "date": day, "sales": sales_for_date(day)})

@app.get("/sales/history")
def sales_history():
    return jsonify({"ok": True, "sales": all_sales()})

# -------- Financials --------
@app.get("/financials/daily")
def financials_daily():
    q = request.args.get("date")
    day = q or latest_day()
    if not day:
        return jsonify({"ok": True, "date": None, "financials": None})
    return jsonify({"ok": True, "date": day, "financials": get_daily(day)})

@app.get("/financials/summary")
def financials_summary():
    agg = aggregate_profitability()
    return jsonify({"ok": True, "summary": agg})

@app.get("/financials/cogs")
def financials_cogs():
    return jsonify({"ok": True, "cogs_per_product": cogs_per_product()})

# -------- Admin --------
@app.post("/config")
def config_update():
    data = request.get_json(force=True, silent=True) or {}
    cfg = read_json("config.json")
    # Allow partial updates to top-level keys
    allowed = {"operating_expenses", "sales_simulation", "supplier", "simulation", "tick_seconds"}
    changed = {}
    for k, v in data.items():
        if k in allowed:
            cfg[k] = v
            changed[k] = v
    write_json("config.json", cfg)
    # Re-schedule if tick or running changed
    if "simulation" in changed or "tick_seconds" in changed:
        _schedule_job()
    return jsonify({"ok": True, "changed": changed, "config": cfg})

@app.post("/reset")
def reset_all():
    data = request.get_json(force=True, silent=True) or {}
    reset_config = bool(data.get("reset_config", False))
    from utils.file_manager import DEFAULTS, data_path, write_json
    # Reset inventory/sales/financials
    for fname in ["inventory.json", "sales.json", "financials.json"]:
        write_json(fname, DEFAULTS[fname])
    if reset_config:
        write_json("config.json", DEFAULTS["config.json"])
    return jsonify({"ok": True})

@app.get("/")
def index():
    # Serve the simple monitoring UI
    return render_template("index.html")

if __name__ == "__main__":
    # Running directly: start Flask dev server
    app.run(host="0.0.0.0", port=5000, debug=True)


