#!/usr/bin/env bash
# Restart Fortress Command Center (Flask on COMMAND_CENTER_PORT, default 8083).
# Run from repo root on the machine that serves the dashboard (OCI, laptop, etc.).
#
# On servers using systemd (fortress-dashboard.service), do NOT use this script —
# it starts a second copy on the same port and systemd will crash-loop.
# Use: sudo ./scripts/restart_dashboard_systemd.sh
# Override (not recommended): RESTART_DASHBOARD_ALLOW_NOHUP=1 ./scripts/restart_dashboard.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PORT="${COMMAND_CENTER_PORT:-8083}"
VENV="${VENV_PATH:-$ROOT/venv}"

if [[ -z "${RESTART_DASHBOARD_ALLOW_NOHUP:-}" ]] && command -v systemctl >/dev/null 2>&1; then
  if systemctl is-enabled fortress-dashboard.service &>/dev/null; then
    echo "[restart] ERROR: fortress-dashboard.service is enabled (systemd)." >&2
    echo "[restart] Starting nohup here would bind port ${PORT} twice and break systemd." >&2
    echo "[restart] Use: sudo ./scripts/restart_dashboard_systemd.sh" >&2
    exit 1
  fi
fi

echo "[restart] repo=$ROOT port=$PORT"

# Stop existing listener on this port (if any)
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 2>/dev/null || true
elif command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti ":${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${PIDS}" ]]; then
    kill -TERM ${PIDS} 2>/dev/null || true
    sleep 1
    PIDS="$(lsof -ti ":${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
    [[ -z "${PIDS}" ]] || kill -KILL ${PIDS} 2>/dev/null || true
  fi
fi

# Stop by process name (backup)
pkill -f "dashboard/command_center.py" 2>/dev/null || true
sleep 1

mkdir -p logs data
export PYTHONPATH="${PYTHONPATH:-$ROOT}"

if [[ -f "${VENV}/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "${VENV}/bin/activate"
fi

LOG="${ROOT}/logs/dashboard_restart.log"
echo "[restart] starting at $(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$LOG"
nohup python3 dashboard/command_center.py >>"$LOG" 2>&1 &
echo "[restart] dashboard PID=$! log=$LOG"
echo "[restart] listen: http://0.0.0.0:${PORT}/"
