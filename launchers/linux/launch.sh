#!/usr/bin/env bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR/../.."

PYTHON_BIN="venv/bin/python"
if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

echo "Starting RACHEL Proxy..."
$PYTHON_BIN -m uvicorn rachel.proxy:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!

sleep 2
if command -v xdg-open > /dev/null; then
    xdg-open http://localhost:8000
fi

wait $SERVER_PID
