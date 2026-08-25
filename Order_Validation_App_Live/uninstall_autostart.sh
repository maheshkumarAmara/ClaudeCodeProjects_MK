#!/bin/bash
# Removes the launchd auto-start gateway and stops any related processes
# (gateway, internal Streamlit instance, bridge server) that are running.
#
# Local-machine setup only — not part of the shared repo.

PLIST_NAME="com.rubrik.order-validation-gateway"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

echo "🛑 Unloading launchd agent..."
launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true

if [ -f "$PLIST_PATH" ]; then
    rm -f "$PLIST_PATH"
    echo "🗑️  Removed $PLIST_PATH"
else
    echo "   (no plist found — already removed)"
fi

# Stop any processes still holding the relevant ports (gateway 8501,
# internal Streamlit 8510, bridge 3001).
for PORT in 8501 8510 3001; do
    PIDS=$(lsof -i :$PORT -sTCP:LISTEN -t 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "🛑 Stopping process(es) on port $PORT: $PIDS"
        kill $PIDS 2>/dev/null || true
    fi
done

echo "✅ Auto-start uninstalled. Use ./launch.sh to run the app manually."
