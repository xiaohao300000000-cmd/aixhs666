#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
RUNTIME_DIR="$ROOT_DIR/.runtime"
NPX_BIN="$(command -v npx)"

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

cat > "$LAUNCH_AGENTS_DIR/com.aixhs.operator-tunnel.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.aixhs.operator-tunnel</string>
  <key>ProgramArguments</key>
  <array>
    <string>$NPX_BIN</string><string>--yes</string><string>localtunnel</string>
    <string>--port</string><string>8020</string>
    <string>--subdomain</string><string>aixhs-operator-gateway</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$RUNTIME_DIR/operator-tunnel.log</string>
  <key>StandardErrorPath</key><string>$RUNTIME_DIR/operator-tunnel.error.log</string>
</dict>
</plist>
PLIST

for label in com.aixhs.operator-gateway com.aixhs.operator-tunnel; do
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  sleep 1
  launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENTS_DIR/$label.plist"
done

echo "operator gateway launch agents installed"
