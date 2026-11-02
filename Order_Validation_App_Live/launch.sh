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
    BRIDGE_STARTED=1
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

# Interactive mode (run from a terminal, not by gateway.js, which redirects
# output to a log): open the browser when Streamlit is up, and on exit — Ctrl+C
# or closing the terminal — stop the app and close that browser tab.
# Set NO_BROWSER=1 to skip the browser handling.
INTERACTIVE=""
if [ -t 1 ] && [ -z "$NO_BROWSER" ]; then
    INTERACTIVE=1
fi

APP_URL="http://localhost:$STREAMLIT_PORT"
STREAMLIT_PID=""
OPENER_PID=""

# Close browser tabs showing this app, including the tabs its pages open in a new
# window ("Open in a new tab" on the PO Processing Engine and SOQL Builder pages
# points at those tools' own ports, not at the Streamlit port).
# macOS only; Chrome, Brave, Edge, Safari. Only touches browsers that are already
# running, and only tabs whose URL starts with one of the prefixes below.
PO_ENGINE_PORT="${PO_ENGINE_PORT:-8012}"
SOQL_BUILDER_PORT="${SOQL_BUILDER_PORT:-4580}"

close_browser_tabs() {
    command -v osascript >/dev/null 2>&1 || return 0
    prefixes=""
    for host in localhost 127.0.0.1; do
        for port in "$STREAMLIT_PORT" "$PO_ENGINE_PORT" "$SOQL_BUILDER_PORT"; do
            prefixes="$prefixes\"http://$host:$port/\", "
        done
    done
    prefixes="${prefixes%, }"
    for app in "Google Chrome" "Brave Browser" "Microsoft Edge" "Safari"; do
        # Walk windows and tabs from the end so closing one doesn't skip the next.
        osascript >/dev/null 2>&1 <<EOF
if application "$app" is running then
    set prefixes to {$prefixes}
    tell application "$app"
        repeat with wi from (count of windows) to 1 by -1
            set w to window wi
            repeat with ti from (count of tabs of w) to 1 by -1
                set u to URL of tab ti of w
                repeat with p in prefixes
                    if u starts with (contents of p) then
                        close tab ti of w
                        exit repeat
                    end if
                end repeat
            end repeat
        end repeat
    end tell
end if
EOF
    done
}

cleanup() {
    trap '' HUP INT TERM
    [ -n "$OPENER_PID" ] && kill "$OPENER_PID" 2>/dev/null
    if [ -n "$STREAMLIT_PID" ]; then
        kill "$STREAMLIT_PID" 2>/dev/null
        wait "$STREAMLIT_PID" 2>/dev/null
    fi
    if [ -n "$INTERACTIVE" ]; then
        # Stop the bridge only if this run started it.
        if [ -n "$BRIDGE_STARTED" ]; then
            lsof -i :$BRIDGE_PORT -sTCP:LISTEN -t 2>/dev/null | xargs kill 2>/dev/null
        fi
        close_browser_tabs
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

if [ -n "$INTERACTIVE" ]; then
    (
        for _ in $(seq 1 60); do
            if lsof -i :"$STREAMLIT_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
                open "$APP_URL" 2>/dev/null || xdg-open "$APP_URL" 2>/dev/null
                break
            fi
            sleep 1
        done
    ) &
    OPENER_PID=$!
fi

# Run Streamlit in the background and wait on it, so the trap above fires
# immediately on Ctrl+C / terminal close instead of after Streamlit exits.
streamlit run Order_Validation_App.py --server.port "$STREAMLIT_PORT" --server.headless true --server.enableCORS false --server.enableXsrfProtection false &
STREAMLIT_PID=$!
wait "$STREAMLIT_PID"
