# Vending Machine Simulation (Flask + APScheduler + JSON)

Simulates a vending machine business with an auto-advancing day tick. Data is persisted in JSON files (no DB).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate  # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
export FLASK_APP=app.py  # (Windows PowerShell: $env:FLASK_APP="app.py")
python app.py  # starts Flask and the background scheduler
```
The scheduler advances **one simulated day every `tick_seconds`** (default 60s). You can also fast-forward using `POST /simulate/day`.

## API (selected)

- `GET /status` → Simulation status.
- `POST /simulate/day` → Force a single simulated day.
- `GET /inventory` → Current stock and pending restocks.
- `POST /inventory/order` → `{"item":"Coke","qty":20}` (enforces minimum order qty and adds a restock ETA).
- `POST /inventory/restock` → Applies any orders whose ETA is <= current date.
- `GET /prices` / `POST /prices` → Get or set sell prices.
- `GET /sales/today` → Sales for the most recently completed simulated date.
- `GET /sales/history` → Full sales list.
- `GET /financials/daily?date=YYYY-MM-DD` → Balance sheet for a day (or latest if omitted).
- `GET /financials/summary` → Aggregated profitability + per-product breakdown.
- `GET /financials/cogs` → COGS per product across history.
- `POST /config` → Update parts of config (operating_expenses, sales_simulation, supplier, simulation, tick_seconds).
- `POST /reset` → Reset JSON data (keeps config unless you pass `"reset_config": true`).

### Notes on "today"
- The engine *processes* the date stored in `config.simulation.current_date` and then advances it by one.
- `/sales/today` returns sales for the **most recent completed simulated date**.

## Default Data Files

- `data/inventory.json`
- `data/sales.json`
- `data/financials.json`
- `data/config.json`

## Tests

```bash
pytest -q
```
Unit tests cover JSON persistence, inventory ordering, and financial calculations.

## MCP server (Model Context Protocol) — local testing

This project includes a small local MCP server implementation for testing MCP
connectors with the project's JSON data. The server exposes `search` and
`fetch` tools and reads documents from the `data/` directory.

Run locally:

```powershell
# create and activate virtualenv (Windows PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# start the MCP server (SSE transport) on port 8000
python mcp_server.py
```

The server listens on http://127.0.0.1:8000/sse/ and implements the MCP
tool contract. Use tools `search` (query -> list of results) and `fetch` (id ->
document) for deep research testing. Results are returned as MCP content arrays
with a single `text` item containing JSON-encoded payloads.

Note: This is a local testing server and is not secured. Do not expose it to
the public or use it with sensitive data without adding authentication.

### MCP tool definitions

The included local MCP server exposes the following tools (MCP-compliant):

- `search(query: str)` → returns `{results: [{id,title,url}, ...]}` as a JSON string in a single `text` content item.
- `fetch(id: str)` → returns a full document `{id,title,text,url,metadata}` as a JSON string in a single `text` content item.
- `status()` → returns simulation and inventory summary.
- `sales_today()` → returns sales for the last simulated day.
- `sales_history()` → returns all sales records.
- `order_inventory(arg: str)` → accepts a JSON string like `{"item":"Coke","qty":20}` and places an order; returns order summary.
- `apply_restock()` → apply any pending restocks up to `config.simulation.current_date`.
- `get_prices_tool()` → returns current sell prices.
- `set_prices(arg: str)` → accepts `{"prices": {...}}` or `{"item":"Coke","sell_price":1.50}` to set prices.
- `financials_daily_tool(arg: str)` → optional date arg (YYYY-MM-DD) returns that day's financials (or latest if omitted).
- `financials_summary_tool()` → returns aggregated financial summary.

All tools return MCP "content" arrays with a single `text` item whose `text` is a JSON-encoded string payload as shown above. For example, a `search` response looks like:

```json
{"content":[{"type":"text","text":"{\"results\":[{\"id\":\"Coke\",\"title\":\"Coke\",\"url\":\"local://inventory/Coke\"}]}"}]}
```

### Example: Responses API tool configuration

Below is an example snippet showing how you might configure an MCP tool in a Responses API call. Replace `server_url` with your server's SSE URL (e.g., `http://127.0.0.1:8000/sse/` when running locally):

```json
"tools": [
	{
		"type": "mcp",
		"server_label": "vending_local",
		"server_url": "http://127.0.0.1:8000/sse/",
		"allowed_tools": ["search","fetch","status","sales_today","order_inventory","apply_restock","get_prices_tool","set_prices","financials_daily_tool","financials_summary_tool"],
		"require_approval": "never"
	}
]
```

With the server configured, a deep research model can call `search` and `fetch` to find documents, or call the action tools (`order_inventory`, `set_prices`, etc.) to interact with the simulation.


# Docker Setup
## Commands I ran:
```
docker run -it --rm `       
>>   -v "${PWD}\cloudflared:/home/nonroot/.cloudflared" `
>>   cloudflare/cloudflared:latest `
>>   tunnel login
```

```
docker run -it --rm `       
>>   -v "${PWD}\cloudflared:/home/nonroot/.cloudflared" `
>>   cloudflare/cloudflared:latest `
>>   tunnel create vending-sim
```
^^ The command above gave me the Tunnel ID I used in the config.yml

### Setting up DNS:
```
docker run -it --rm `       
>>   -v "${PWD}\cloudflared:/home/nonroot/.cloudflared" `
>>   cloudflare/cloudflared:latest `
>>   tunnel route dns vending-sim app.zach.games
2025-09-13T23:11:32Z INF Added CNAME app.zach.games which will route to this tunnel tunnelID=08371aa5-cafa-4fb2-8852-d7860e309242
PS C:\Users\zachb\Downloads\vending_machine_sim> docker run -it --rm `       
>>   -v "${PWD}\cloudflared:/home/nonroot/.cloudflared" `
>>   cloudflare/cloudflared:latest `
>>   tunnel route dns vending-sim mcp.zach.games
```

```
docker compose up -d --build
```