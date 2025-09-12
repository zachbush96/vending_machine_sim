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
This MCP server provides access to local vending machine simulation data. It supports
searching and fetching documents related to inventory, sales, and financials. 
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
        """
        Search documents for a query string and return lightweight results.

        This tool performs a simple, local fuzzy search over document titles and
        text loaded from the `data/` files (inventory, sales, financials). It
        returns a minimal result set suitable for quick semantic filtering. The
        returned value is formatted as an MCP content array: a dict with a
        single `content` key containing a list of text items. The text item
        contains a JSON-encoded payload with a `results` array.

        Args:
            query: Natural language or keyword query. If empty or whitespace,
                   the tool returns an empty results list.

        Returns:
            Dict with `content` -> [{"type":"text","text": json_payload}].
            The JSON payload has the shape {"results": [{"id","title","url"}, ...]}.

        Edge cases & notes:
            - This is not a vector or semantic embedding search; it uses simple
              substring matching on title and text.
            - Results are reloaded on each call so they reflect current data
              files. Large data files may slow this tool.
            - Use the `fetch` tool to retrieve full document content for any
              id returned here.
        """
        if not query or not query.strip():
            return {"content": [{"type": "text", "text": json.dumps({"results": []})}]}

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
        """
        Fetch a single document by id and return its full JSON content.

        This tool looks up documents produced by `load_all_documents()` and
        returns a complete document encoded as JSON inside an MCP content
        array. The payload contains id, title, text, url and metadata fields.

        Args:
            id: Document identifier as returned by search or the local URL
                fragment (for example: 'sale-123', 'financials', or an item id).

        Returns:
            Dict with `content` -> [{"type":"text","text": json_document}].
            json_document contains the document object.

        Edge cases & errors:
            - If `id` is falsy a ValueError is raised (MCP callers should provide id).
            - If no document matches, a ValueError is raised indicating not found.
            - Because the document `text` field may itself be JSON, callers may
              need to parse the returned text to access nested fields.
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
        """
        Return a snapshot of simulation configuration and inventory status.

        This action tool is intended for quick health/status checks by an LLM or
        an external controller. It reads `config.json` and the current in-memory
        inventory via the `get_inventory()` model function and returns a JSON
        summary with simulation config and per-item stock/restore info.

        Returns:
            MCP content array with a single text item. The text is a JSON
            object: {"simulation": {...}, "tick_seconds": N, "inventory_summary": {...}}

        Edge cases:
            - If configuration or inventory files are missing the tool will
              return whatever read_json/get_inventory provide (possibly empty
              dicts). Callers should handle missing fields.
        """
        cfg = read_json("config.json")
        inv = get_inventory()
        payload = {
            "simulation": cfg.get("simulation"),
            "tick_seconds": cfg.get("tick_seconds"),
            "inventory_summary": {
                k: {
                    "stock": v.get("stock"),
                    "restock_pending": v.get("restock_pending"),
                    "restock_eta": v.get("restock_eta"),
                }
                for k, v in inv.items()
            },
        }
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    @mcp.tool()
    async def sales_today() -> Dict[str, Any]:
        """
        Return sales for the most recently-simulated date.

        The tool determines the date to query from `config.json` (the
        `simulation.last_simulated_date` field) or falls back to the latest
        date available in financials/sales. It returns the list of sales for
        that date encoded in an MCP content array.

        Returns:
            MCP content array with JSON: {"date": iso_date, "sales": [...]}

        Edge cases:
            - If no date can be determined, an empty sales list is returned.
        """
        cfg = read_json("config.json")
        day = cfg["simulation"].get("last_simulated_date") or latest_day()
        sales = sales_for_date(day) if day else []
        payload = {"date": day, "sales": sales}
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    @mcp.tool()
    async def sales_history() -> Dict[str, Any]:
        """
        Return the full sales history as stored in `data/sales.json`.

        This returns every recorded sale (as the `all_sales()` model helper
        produces). The response is an MCP content array with a JSON object
        containing the `sales` list.

        Edge cases:
            - Large histories may produce big payloads. Consumers should be
              prepared to page or request specific ranges if needed.
        """
        payload = {"sales": all_sales()}
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    @mcp.tool()
    async def order_inventory(arg: str) -> Dict[str, Any]:
        """
        Place a supplier order for a given item.

        The `arg` parameter should be a JSON string with either a single
        item and qty (e.g. {"item":"Coke","qty":20}). The tool checks
        supplier config from `config.json` (min order qty and lead time) and
        calls `place_order()` to create the pending order.

        Args:
            arg: JSON-encoded string describing the order.

        Returns:
            MCP content array containing either {"order": {...}} on success
            or {"error": "..."} when input validation or placement fails.

        Edge cases:
            - If `arg` is invalid JSON the tool returns an error payload.
            - Qty is coerced to int; non-positive qty or missing item returns an error.
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
        """
        Apply any pending restocks up to the current simulation date.

        This tool reads the simulation `current_date` from `config.json` and
        applies supplier restocks whose ETA is <= that date by calling
        `apply_restocks(upto)`. It returns a summary of applied restocks.

        Returns:
            MCP content array with JSON: {"applied": [...], "upto": date}

        Edge cases:
            - If there are no restocks pending, `applied` will be an empty list.
        """
        cfg = read_json("config.json")
        upto = cfg["simulation"]["current_date"]
        applied = apply_restocks(upto)
        return {"content": [{"type": "text", "text": json.dumps({"applied": applied, "upto": upto})}]}

    @mcp.tool()
    async def get_prices_tool() -> Dict[str, Any]:
        """
        Return current sell prices for all items.

        This simple read-only tool calls `get_prices()` from the inventory
        model and returns a JSON object containing current pricing. Useful for
        informing pricing decisions or validating expected values.

        Returns:
            MCP content array with JSON: {"prices": {"ItemName": price, ...}}

        Edge cases:
            - If pricing data is missing the returned dict may be empty.
        """
        prices = get_prices()
        return {"content": [{"type": "text", "text": json.dumps({"prices": prices})}]}

    @mcp.tool()
    async def set_prices(arg: str) -> Dict[str, Any]:
        """
        Update item prices.

        The `arg` parameter accepts either a JSON object with a `prices` map
        (e.g. {"prices": {"Coke":1.5, "Pepsi":1.25}}) to adjust multiple
        prices at once, or a single item update like
        {"item":"Coke","sell_price":1.5}.

        Returns:
            MCP content array with the updated prices on success or an error
            payload containing an `error` message on failure.

        Edge cases:
            - Invalid JSON returns an error payload.
            - Missing required fields returns an error explaining the expectation.
        """
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
        """
        Advance the simulation by one day and return the day summary.

        This tool calls the project's `simulate_day()` function which performs a
        single simulation tick: generating sales, updating inventory, and
        recording financials. The returned summary is encoded inside the MCP
        content array and typically contains statistics about sales, restocks,
        and profit/loss for the day.

        Edge cases:
            - simulate_day may raise if dependencies or data files are missing;
              any exception will propagate unless handled by the caller.
        """
        summary = simulate_day()
        return {"content": [{"type": "text", "text": json.dumps({"summary": summary})}]}

    @mcp.tool()
    async def financials_daily_tool(arg: str) -> Dict[str, Any]:
        """
        Return financials for a specific day.

        Args:
            arg: Optional ISO date string. If empty, the tool will use the
                 latest available date returned by `latest_day()`.

        Returns:
            MCP content array with JSON: {"date": date, "financials": {...}}

        Edge cases:
            - If `arg` is invalid or no data exists for the requested date the
              `financials` value may be null.
        """
        # arg may be a date iso; if empty, use latest
        day = arg or latest_day()
        fin = get_daily(day) if day else None
        return {"content": [{"type": "text", "text": json.dumps({"date": day, "financials": fin})}]}

    @mcp.tool()
    async def financials_summary_tool() -> Dict[str, Any]:
        """
        Return aggregated profitability summary across available financials.

        This read-only tool runs `aggregate_profitability()` to produce a
        compact summary useful for dashboards or quick assessments. The result
        is returned inside an MCP content array as JSON under the `summary`
        key.

        Edge cases:
            - If no financials data exists an empty or null summary may be
              returned depending on the model implementation.
        """
        summary = aggregate_profitability()
        return {"content": [{"type": "text", "text": json.dumps({"summary": summary})}]}

    return mcp


def main():
    server = create_server()
    LOG.info("Starting local MCP server on 0.0.0.0:8000 (HTTP)")
    server.run(transport="http", host="0.0.0.0", port=8000, path="/mcp")


if __name__ == "__main__":
    main()
