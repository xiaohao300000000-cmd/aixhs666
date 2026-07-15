#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
RUNTIME_DIR="$ROOT_DIR/.runtime"
TAILSCALE_BIN="/Applications/Tailscale.app/Contents/MacOS/Tailscale"

mkdir -p "$LAUNCH_AGENTS_DIR" "$RUNTIME_DIR"

cat > "$LAUNCH_AGENTS_DIR/com.aixhs.operator-gateway.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.aixhs.operator-gateway</string>
  <key>ProgramArguments</key>
  <array><string>$ROOT_DIR/scripts/run_operator_gateway.sh</string></array>
  <key>WorkingDirectory</key><string>$ROOT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$RUNTIME_DIR/operator-gateway.log</string>
  <key>StandardErrorPath</key><string>$RUNTIME_DIR/operator-gateway.error.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/com.aixhs.operator-tunnel" 2>/dev/null || true
rm -f "$LAUNCH_AGENTS_DIR/com.aixhs.operator-tunnel.plist"

launchctl bootout "gui/$(id -u)/com.aixhs.operator-gateway" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENTS_DIR/com.aixhs.operator-gateway.plist"

if [[ ! -x "$TAILSCALE_BIN" ]]; then
  echo "Tailscale CLI not found at $TAILSCALE_BIN" >&2
  exit 1
fi

"$TAILSCALE_BIN" funnel --bg --yes 8020

echo "operator gateway and Tailscale Funnel configured"
