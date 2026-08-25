#!/bin/bash
# Installs the gateway as a per-user launchd agent so it starts automatically
# at login and stays running (auto-restarting only if it crashes).
#
# Local-machine setup only — not part of the shared repo.

set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
PLIST_NAME="com.rubrik.order-validation-gateway"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
NODE_BIN="$(command -v node)"

if [ -z "$NODE_BIN" ]; then
    echo "❌ node not found on PATH — install Node.js first."
    exit 1
fi

mkdir -p "$PROJECT_DIR/logs"

# launchd agents run with a minimal PATH (no /usr/local/bin, no Python
# framework bin, no nvm) which is NOT the same PATH your interactive shell
# has. Capture the current (interactive) PATH so launch.sh can find pip3,
# streamlit, and node the same way it does when run by hand.
GATEWAY_PATH="${PATH}"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${NODE_BIN}</string>
        <string>${PROJECT_DIR}/gateway.js</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${GATEWAY_PATH}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>Crashed</key>
        <true/>
    </dict>
    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/logs/launchd.log</string>
</dict>
</plist>
EOF

echo "📝 Wrote $PLIST_PATH"

# Unload first in case it's already installed, then (re)load.
launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

echo "✅ Gateway installed and started."
echo "   It will now auto-start at login and listen on http://localhost:8501"
echo "   Logs: $PROJECT_DIR/logs/gateway.log (app activity) and logs/launchd.log (launchd-level)"
echo ""
echo "Check status with:"
echo "   launchctl list | grep order-validation-gateway"
echo ""
echo "To remove it later, run: ./uninstall_autostart.sh"
