#!/usr/bin/env bash
set -euo pipefail

python -u app.py &       # listens on 0.0.0.0:5000 inside container
APP_PID=$!

python -u mcp_server.py & # listens on 0.0.0.0:8000 inside container
MCP_PID=$!

# If either exits, terminate the other and exit
wait -n $APP_PID $MCP_PID
kill $APP_PID $MCP_PID 2>/dev/null || true
wait || true
