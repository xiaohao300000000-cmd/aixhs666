#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
RUNTIME_DIR="$ROOT_DIR/.runtime"
LABEL="com.aixhs.skill-run-worker"

mkdir -p "$LAUNCH_AGENTS_DIR" "$RUNTIME_DIR"
chmod +x "$ROOT_DIR/scripts/run_skill_run_worker.sh"

cat > "$LAUNCH_AGENTS_DIR/$LABEL.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$ROOT_DIR/scripts/run_skill_run_worker.sh</string></array>
  <key>WorkingDirectory</key><string>$ROOT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$RUNTIME_DIR/skill-run-worker.log</string>
  <key>StandardErrorPath</key><string>$RUNTIME_DIR/skill-run-worker.error.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENTS_DIR/$LABEL.plist"
echo "skill run worker configured"

