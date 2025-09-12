"""
Local MCP server for the vending_machine_sim project.

This implements a minimal Model Context Protocol (MCP) server using FastMCP
with two tools: `search` and `fetch`.

The server reads from local JSON files in the `data/` directory and returns
MCP-compliant content arrays. This is intended for local testing and demo
purposes (no vector store integration).
"""
import json
import logging
import os
from typing import Any, Dict, List

from fastmcp import FastMCP

# Project model bindings
from utils.file_manager import read_json
from models.inventory import get_inventory, place_order, apply_restocks, get_prices, set_price, adjust_prices
from models.sales import sales_for_date, all_sales
from models.financials import get_daily, aggregate_profitability, latest_day
from app import simulate_day  # avoid circular import

LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

server_instructions = """
Local MCP server that exposes search and fetch tools against the project's
local JSON data files (inventory, sales, financials). This is for testing
and demoing MCP integrations.
"""


def load_all_documents() -> List[Dict[str, Any]]:
    """Load available document-like records from data files.

    We map items in `data/inventory.json` into small documents with id/title/text/url.
    """
    docs: List[Dict[str, Any]] = []

    # Inventory items
    inv_path = os.path.join(DATA_DIR, "inventory.json")
    if os.path.exists(inv_path):
        try:
            with open(inv_path, "r", encoding="utf-8") as f:
                inventory = json.load(f)
            for item in inventory.get("items", []) if isinstance(inventory, dict) else inventory:
                item_id = item.get("id") or item.get("sku") or item.get("name")
                title = item.get("name") or f"Item {item_id}"
                text = json.dumps(item)
                docs.append({
                    "id": str(item_id),
                    "title": title,
                    "text": text,
                    "url": f"local://inventory/{item_id}",
                    "metadata": {"source": "inventory"},
                })
        except Exception:
            LOG.exception("Failed to load inventory.json")

    # Sales records (short summary docs)
    sales_path = os.path.join(DATA_DIR, "sales.json")
    if os.path.exists(sales_path):
        try:
            with open(sales_path, "r", encoding="utf-8") as f:
                sales = json.load(f)
            # create a doc per sale
            for s in sales.get("sales", []) if isinstance(sales, dict) else sales:
                sid = s.get("id") or s.get("sale_id")
                title = f"Sale {sid}"
                text = json.dumps(s)
                docs.append({
                    "id": f"sale-{sid}",
                    "title": title,
                    "text": text,
                    "url": f"local://sales/{sid}",
                    "metadata": {"source": "sales"},
                })
        except Exception:
            LOG.exception("Failed to load sales.json")

    # Financials (single doc)
    fin_path = os.path.join(DATA_DIR, "financials.json")
    if os.path.exists(fin_path):
        try:
            with open(fin_path, "r", encoding="utf-8") as f:
                fin = json.load(f)
            docs.append({
                "id": "financials",
                "title": "Financials",
                "text": json.dumps(fin),
                "url": "local://financials",
                "metadata": {"source": "financials"},
            })
        except Exception:
            LOG.exception("Failed to load financials.json")

    return docs


def create_server() -> FastMCP:
    mcp = FastMCP(name="Vending Machine Local MCP", instructions=server_instructions)

    @mcp.tool()
    async def search(query: str) -> Dict[str, List[Dict[str, Any]]]:
        """Return a list of matching documents for a query.

        This is a very small fuzzy search over titles and text.
        """
        if not query or not query.strip():
            return {"results": []}

        q = query.lower()
        results: List[Dict[str, Any]] = []
        # reload documents to reflect current data
        documents = load_all_documents()
        for doc in documents:
            title = doc.get("title", "").lower()
            text = doc.get("text", "").lower()
            if q in title or q in text:
                # Return subset metadata for search result
                results.append({
                    "id": doc["id"],
                    "title": doc.get("title"),
                    "url": doc.get("url"),
                })

        # MCP requires the tool result to be returned as a content array with one text item
        payload = json.dumps({"results": results})
        return {"content": [{"type": "text", "text": payload}]}

    @mcp.tool()
    async def fetch(id: str) -> Dict[str, Any]:
        """Fetch a single document by id and return full content.

        Returns an MCP content array with a single text item containing the JSON-encoded document.
        """
        if not id:
            raise ValueError("id is required")

        # reload documents to reflect current data
        documents = load_all_documents()
        hit = None
        for doc in documents:
            if str(doc.get("id")) == str(id) or doc.get("id") == id:
                hit = doc
                break

        if not hit:
            raise ValueError(f"Document not found: {id}")

        result_payload = json.dumps({
            "id": hit.get("id"),
            "title": hit.get("title"),
            "text": hit.get("text"),
            "url": hit.get("url"),
            "metadata": hit.get("metadata"),
        })

        return {"content": [{"type": "text", "text": result_payload}]}

    # ---- Action tools ----
    @mcp.tool()
    async def status() -> Dict[str, Any]:
        """Return basic simulation and inventory status."""
        cfg = read_json("config.json")
        inv = get_inventory()
        payload = {"simulation": cfg.get("simulation"), "tick_seconds": cfg.get("tick_seconds"), "inventory_summary": {k: {"stock": v.get("stock"), "restock_pending": v.get("restock_pending"), "restock_eta": v.get("restock_eta")} for k, v in inv.items()}}
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    @mcp.tool()
    async def sales_today() -> Dict[str, Any]:
        cfg = read_json("config.json")
        day = cfg["simulation"].get("last_simulated_date") or latest_day()
        sales = sales_for_date(day) if day else []
        payload = {"date": day, "sales": sales}
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    @mcp.tool()
    async def sales_history() -> Dict[str, Any]:
        payload = {"sales": all_sales()}
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    @mcp.tool()
    async def order_inventory(arg: str) -> Dict[str, Any]:
        """Place an order. Arg should be a JSON string like {"item":"Coke","qty":20}.

        Returns the order summary (pending qty and ETA).
        """
        try:
            data = json.loads(arg) if arg else {}
        except Exception:
            return {"content": [{"type": "text", "text": json.dumps({"error": "Invalid JSON argument"})}]}

        item = data.get("item")
        qty = int(data.get("qty", 0))
        if not item or qty <= 0:
            return {"content": [{"type": "text", "text": json.dumps({"error": "Provide item and positive qty"})}]}

        cfg = read_json("config.json")
        min_q = int(cfg["supplier"].get("min_order_qty", 1))
        lead = int(cfg["supplier"].get("lead_time_days", 1))
        try:
            res = place_order(item, qty, cfg["simulation"]["current_date"], min_q, lead)
            return {"content": [{"type": "text", "text": json.dumps({"order": res})}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": json.dumps({"error": str(e)})}]}

    @mcp.tool()
    async def apply_restock() -> Dict[str, Any]:
        cfg = read_json("config.json")
        upto = cfg["simulation"]["current_date"]
        applied = apply_restocks(upto)
        return {"content": [{"type": "text", "text": json.dumps({"applied": applied, "upto": upto})}]}

    @mcp.tool()
    async def get_prices_tool() -> Dict[str, Any]:
        prices = get_prices()
        return {"content": [{"type": "text", "text": json.dumps({"prices": prices})}]}

    @mcp.tool()
    async def set_prices(arg: str) -> Dict[str, Any]:
        """Set prices. Arg can be JSON: {"prices": {"Coke":1.5}} or {"item":"Coke","sell_price":1.5}"""
        try:
            data = json.loads(arg) if arg else {}
        except Exception:
            return {"content": [{"type": "text", "text": json.dumps({"error": "Invalid JSON argument"})}]}

        try:
            if "prices" in data and isinstance(data["prices"], dict):
                adjust_prices(data["prices"])
            else:
                item = data.get("item")
                price = data.get("sell_price")
                if not item or price is None:
                    raise ValueError("Provide 'prices' dict or 'item' and 'sell_price'")
                set_price(item, float(price))
            return {"content": [{"type": "text", "text": json.dumps({"prices": get_prices()})}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": json.dumps({"error": str(e)})}]}

    @mcp.tool()
    async def simulate_day_tool() -> Dict[str, Any]:
        summary = simulate_day()
        return {"content": [{"type": "text", "text": json.dumps({"summary": summary})}]}

    @mcp.tool()
    async def financials_daily_tool(arg: str) -> Dict[str, Any]:
        # arg may be a date iso; if empty, use latest
        day = arg or latest_day()
        fin = get_daily(day) if day else None
        return {"content": [{"type": "text", "text": json.dumps({"date": day, "financials": fin})}]}

    @mcp.tool()
    async def financials_summary_tool() -> Dict[str, Any]:
        summary = aggregate_profitability()
        return {"content": [{"type": "text", "text": json.dumps({"summary": summary})}]}
    
    return mcp


def main():
    server = create_server()
    LOG.info("Starting local MCP server on 0.0.0.0:8000 (HTTP)")
    server.run(transport="http", host="0.0.0.0", port=8000, path="/mcp")


if __name__ == "__main__":
    main()
