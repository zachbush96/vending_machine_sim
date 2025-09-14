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

def create_server() -> FastMCP:
    mcp = FastMCP(name="Vending Machine Local MCP", instructions=server_instructions)

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
      Place supplier order(s) for item(s).

      The `arg` parameter accepts:
        - single order: {"item":"Coke","qty":20}
        - bulk list: {"orders":[{"item":"Coke","qty":20}, {"item":"Pepsi","qty":10}]}
        - items dict: {"items": {"Coke":20, "Pepsi":10}}

      Returns MCP content array with {"orders":[...], "errors":[...]}.
      """
      try:
        data = json.loads(arg) if arg else {}
      except Exception:
        return {"content": [{"type": "text", "text": json.dumps({"error": "Invalid JSON argument"})}]}

      cfg = read_json("config.json")
      min_q = int(cfg["supplier"].get("min_order_qty", 1))
      lead = int(cfg["supplier"].get("lead_time_days", 1))
      current_date = cfg["simulation"]["current_date"]

      # Normalize to a list of order entries
      entries = []
      if isinstance(data.get("orders"), list):
        entries = data["orders"]
      elif "items" in data and isinstance(data["items"], dict):
        entries = [{"item": k, "qty": v} for k, v in data["items"].items()]
      else:
        # single order fallback
        entries = [{"item": data.get("item"), "qty": data.get("qty", 0)}]

      placed = []
      errors = []
      for e in entries:
        item = e.get("item")
        try:
          qty = int(e.get("qty", 0))
        except Exception:
          errors.append({"item": item, "error": "qty must be an integer"})
          continue

        if not item or qty <= 0:
          errors.append({"item": item, "error": "Provide item and positive qty"})
          continue

        try:
          res = place_order(item, qty, current_date, min_q, lead)
          placed.append(res)
        except Exception as exc:
          errors.append({"item": item, "error": str(exc)})

      payload = {"orders": placed}
      if errors:
        payload["errors"] = errors

      return {"content": [{"type": "text", "text": json.dumps(payload)}]}

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
            # return current prices
            return {"content": [{"type": "text", "text": json.dumps({"prices": get_prices()})}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": json.dumps({"error": str(e)})}]}

    @mcp.tool()
    async def reset_simulation(reset_arg: str = None) -> Dict[str, Any]:
        """
        Reset simulation data files (inventory, sales, financials) and optionally config.

        The `reset_arg` may be a JSON string like {"reset_config": true} or
        omitted/empty to only reset runtime data files. This mirrors the `/reset`
        HTTP endpoint in the Flask app.
        """
        try:
            data = json.loads(reset_arg) if reset_arg else {}
        except Exception:
            data = {}

        reset_config = bool(data.get("reset_config", False))
        # Use the project's DEFAULTS to restore files
        from utils.file_manager import DEFAULTS, write_json

        for fname in ["inventory.json", "sales.json", "financials.json"]:
            write_json(fname, DEFAULTS[fname])
        if reset_config:
            write_json("config.json", DEFAULTS["config.json"])

        return {"content": [{"type": "text", "text": json.dumps({"ok": True})}]}

    @mcp.tool()
    async def simulate_day_tool(arg: str) -> Dict[str, Any]:
      """
      Advance the simulation by N days and return summaries.

      The `arg` may be:
        - an integer string like "5"
        - a JSON integer like "5"
        - a JSON object with {"days": N}

      Days will be coerced to int and must be between 1 and 90 (inclusive).
      The tool calls `simulate_day()` repeatedly and returns a list of daily
      summaries. Non-JSON-serializable summaries are returned as strings.

      Returns:
        MCP content array with JSON: {"days": N, "summaries": [...]}
        or {"error": "..."} on invalid input or runtime errors.
      """
      # parse argument to determine number of days
      try:
        if not arg or not arg.strip():
          days = 1
        else:
          # try JSON first (handles {"days":N} or plain JSON number)
          try:
            parsed = json.loads(arg)
            if isinstance(parsed, dict) and "days" in parsed:
              days = int(parsed["days"])
            elif isinstance(parsed, (int, float, str)):
              days = int(parsed)
            else:
              # fallback to parsing plain string int
              days = int(str(parsed))
          except Exception:
            # fallback: try to parse as plain integer string
            days = int(arg)
      except Exception:
        return {"content": [{"type": "text", "text": json.dumps({"error": "Invalid days argument"})}]}

      # validate range
      if days < 1 or days > 90:
        return {"content": [{"type": "text", "text": json.dumps({"error": "days must be between 1 and 90"})}]}

      summaries = []
      try:
        for i in range(days):
          summary = simulate_day()
          # ensure JSON serializability per-item; if not serializable, stringify it
          try:
            json.dumps(summary)
            summaries.append(summary)
          except Exception:
            summaries.append(str(summary))
      except Exception as e:
        return {"content": [{"type": "text", "text": json.dumps({"error": f"Simulation failed on day {len(summaries)+1}: {str(e)}"})}]}

      payload = {"days": days, "summaries": summaries}
      return {"content": [{"type": "text", "text": json.dumps(payload)}]}

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


    @mcp.tool()
    async def list_files() -> Dict[str, Any]:
        """
        List all files in the project directory.

        This tool scans the project directory and returns a list of all file
        names. The result is returned inside an MCP content array as JSON
        under the `files` key.

        Edge cases:
            - If the directory is empty, an empty list is returned.
        """
        files = []
        for root, _, filenames in os.walk(os.path.dirname(__file__)):
            for filename in filenames:
                rel_dir = os.path.relpath(root, os.path.dirname(__file__))
                rel_file = os.path.join(rel_dir, filename) if rel_dir != '.' else filename
                files.append(rel_file)
        payload = {"files": files}
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}
    
    # MCP tool to read a specific file and return its contents
    @mcp.tool()
    async def read_file(file_path: str) -> Dict[str, Any]:
        """
        Read the contents of a specific file in the project directory.

        Args:
            file_path: Relative path to the file to be read.
        Returns:
            MCP content array with JSON: {"file_path": file_path, "content": file_content}
        Edge cases:
            - If the file does not exist or cannot be read, an error message is returned.
            - If the file is binary or too large, an appropriate error message is returned.
        """
        if not file_path or '..' in file_path or file_path.startswith('/'):
            return {"content": [{"type": "text", "text": json.dumps({"error": "Invalid file path"})}]}
        
        abs_path = os.path.join(os.path.dirname(__file__), file_path)
        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            return {"content": [{"type": "text", "text": json.dumps({"error": "File not found"})}]}
        
        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read()
            payload = {"file_path": file_path, "content": content}
            return {"content": [{"type": "text", "text": json.dumps(payload)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": json.dumps({"error": str(e)})}]}

    return mcp


def main():
    server = create_server()
    LOG.info("Starting local MCP server on 0.0.0.0:8000 (HTTP)")
    server.run(transport="http", host="0.0.0.0", port=8000, path="/mcp")


if __name__ == "__main__":
    main()
