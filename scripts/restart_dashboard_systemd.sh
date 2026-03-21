#!/usr/bin/env bash
# Restart Fortress Command Center when managed by systemd (production VM).
# Frees port 8083 from stale nohup/manual runs, then restarts the unit.
#
# Usage (repo root, as root):
#   sudo ./scripts/restart_dashboard_systemd.sh
#
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run with sudo (needs fuser + systemctl)." >&2
  exit 1
fi

PORT="${COMMAND_CENTER_PORT:-8083}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[restart-systemd] freeing port ${PORT}/tcp and command_center.py (stale nohup)…"
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 2>/dev/null || true
fi
pkill -f "${ROOT}/dashboard/command_center.py" 2>/dev/null || true
sleep 1

echo "[restart-systemd] systemctl restart fortress-dashboard…"
systemctl restart fortress-dashboard.service
systemctl --no-pager status fortress-dashboard.service || true
echo "[restart-systemd] check: curl -s -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:${PORT}/proof"
