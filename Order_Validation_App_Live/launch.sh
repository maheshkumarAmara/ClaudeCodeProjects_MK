#!/bin/bash

# Navigate to script directory regardless of where it's called from
cd "$(dirname "$0")"

# Port Streamlit binds to (overridable — used by gateway.js to run an internal instance)
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"

echo ""
echo "====================================="
echo "   Order Validation App — Launcher"
echo "====================================="
echo ""

# Step 1: Install dependencies (skips quietly if already installed)
echo "📦 Checking dependencies..."
pip3 install -r requirements.txt -q
echo "   Dependencies OK ✅"
echo ""

# Step 2: Auto-start the Salesforce Bridge server used by the EDI Order Ops Tool
# (idempotent — skips if already running on port 3001)
BRIDGE_DIR="$(pwd)/bridge"
BRIDGE_PORT=3001
BRIDGE_LOG="/tmp/sf_bridge_server.log"

echo "🔌 Checking Salesforce Bridge server (EDI tool)..."
if lsof -i :$BRIDGE_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "   Already running on port $BRIDGE_PORT ✅"
elif [ -f "$BRIDGE_DIR/sf-bridge-server.js" ]; then
    (cd "$BRIDGE_DIR" && nohup node sf-bridge-server.js > "$BRIDGE_LOG" 2>&1 &)
    sleep 1
    if lsof -i :$BRIDGE_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "   Started ✅ (log: $BRIDGE_LOG)"
    else
        echo "   ⚠️  Could not confirm startup — check $BRIDGE_LOG"
    fi
else
    echo "   ⚠️  sf-bridge-server.js not found at $BRIDGE_DIR — skipping"
fi
echo ""

# Step 3: Launch the app
echo "🚀 Launching Order Validation App..."
echo "   Opening at http://localhost:$STREAMLIT_PORT"
echo "   Select QA or UAT environment in the app sidebar."
echo ""
streamlit run Order_Validation_App.py --server.port "$STREAMLIT_PORT" --server.headless true --server.enableCORS false --server.enableXsrfProtection false
