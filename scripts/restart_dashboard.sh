#!/usr/bin/env bash
# Restart Fortress Command Center (Flask on COMMAND_CENTER_PORT, default 8083).
# Run from repo root on the machine that serves the dashboard (OCI, laptop, etc.).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PORT="${COMMAND_CENTER_PORT:-8083}"
VENV="${VENV_PATH:-$ROOT/venv}"

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
