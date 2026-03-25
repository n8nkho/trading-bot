#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage:"
  echo "  ./deploy_to_oracle.sh --host HOST --user USER --remote-dir DIR [--port PORT] [--venv VENV_DIR] [--service SERVICE_NAME] [--skip-import-gate] [--install-deps]"
  echo ""
  echo "Replace HOST / USER / DIR with your real server (not the words YOUR_HOST or /path/to/...)."
  echo ""
  echo "Examples:"
  echo "  ./deploy_to_oracle.sh --host 1.2.3.4 --user ubuntu --remote-dir /home/ubuntu/trading-bot --venv /home/ubuntu/trading-bot/venv --service fortress-dashboard"
  echo "  # Recommended (Lane 1): always pass --service fortress-dashboard so the UI reloads after rsync."
}

HOST=""
USER_NAME=""
REMOTE_DIR=""
PORT="22"
VENV_DIR=""
SERVICE_NAME=""
SKIP_IMPORT_GATE="0"
INSTALL_DEPS="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="${2}"; shift 2 ;;
    --user) USER_NAME="${2}"; shift 2 ;;
    --remote-dir) REMOTE_DIR="${2}"; shift 2 ;;
    --port) PORT="${2}"; shift 2 ;;
    --venv) VENV_DIR="${2}"; shift 2 ;;
    --service) SERVICE_NAME="${2}"; shift 2 ;;
    --install-deps) INSTALL_DEPS="1"; shift 1 ;;
    --skip-import-gate) SKIP_IMPORT_GATE="1"; shift 1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 1 ;;
  esac
done

if [[ "${INSTALL_DEPS}" == "1" ]]; then
  DEPLOY_INSTALL_DEPS="1"
fi

if [[ -z "${HOST}" || -z "${USER_NAME}" || -z "${REMOTE_DIR}" ]]; then
  usage
  exit 1
fi

# Catch copy-paste of documentation placeholders (common mistake).
_lc_host="$(printf '%s' "${HOST}" | tr '[:upper:]' '[:lower:]')"
_lc_user="$(printf '%s' "${USER_NAME}" | tr '[:upper:]' '[:lower:]')"
if [[ "${_lc_host}" == "your_host" || "${_lc_host}" == "example.com" ]]; then
  echo "[deploy] ERROR: --host looks like a placeholder (${HOST})."
  echo "         Use your VM's public IP or DNS name (e.g. 203.0.113.50 or myserver.example.com)."
  exit 1
fi
if [[ "${_lc_user}" == "your_user" ]]; then
  echo "[deploy] ERROR: --user looks like a placeholder (${USER_NAME})."
  echo "         Use the SSH login on the server (often: ubuntu, opc, or ec2-user)."
  exit 1
fi
if [[ "${REMOTE_DIR}" == *"/path/to/"* ]]; then
  echo "[deploy] ERROR: --remote-dir still contains /path/to/ (documentation placeholder)."
  echo "         Use the real path on the server, e.g. /home/ubuntu/trading-bot"
  exit 1
fi
if [[ -n "${VENV_DIR}" && "${VENV_DIR}" == *"/path/to/"* ]]; then
  echo "[deploy] ERROR: --venv still contains /path/to/ (documentation placeholder)."
  echo "         Use the real venv path, e.g. /home/ubuntu/trading-bot/venv"
  exit 1
fi

if [[ ! -f "orchestrator.py" ]]; then
  echo "This script must be run from the repo root containing orchestrator.py."
  exit 1
fi

echo "[deploy] Syncing repo to ${USER_NAME}@${HOST}:${REMOTE_DIR}"

# Capture local git info (if available). `.git/` is excluded from rsync.
LOCAL_COMMIT="$(git rev-parse HEAD 2>/dev/null || true)"
LOCAL_DIRTY_COUNT="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
if [[ -z "${LOCAL_DIRTY_COUNT}" ]]; then
  LOCAL_DIRTY_COUNT="0"
fi
if [[ "${LOCAL_DIRTY_COUNT}" -gt 0 ]]; then
  DEPLOY_DIRTY="true"
else
  DEPLOY_DIRTY="false"
fi

# Use rsync if available; fallback to scp only if necessary.
if command -v rsync >/dev/null 2>&1; then
  rsync -az \
    --exclude ".git/" \
    --exclude "__pycache__/" \
    --exclude "*.pyc" \
    --exclude "venv/" \
    --exclude "data/" \
    --exclude "logs/" \
    ./ "${USER_NAME}@${HOST}:${REMOTE_DIR}/"
else
  echo "[deploy] rsync not found; rsync is recommended."
  echo "[deploy] Please install rsync or run deployment manually."
  exit 1
fi

REMOTE_CMD=""

REMOTE_CMD+="cd \"${REMOTE_DIR}\""

# Remote path only — do not test -d locally (deploy from laptop would skip venv).
if [[ -n "${VENV_DIR}" ]]; then
  REMOTE_CMD+=" && source \"${VENV_DIR}/bin/activate\""
fi

if [[ "${DEPLOY_INSTALL_DEPS:-0}" == "1" ]]; then
  REMOTE_CMD+=" && (pip3 install -r requirements.txt >/dev/null 2>&1 || pip3 install -r requirements.txt)"
fi

# Fail fast: ensure critical modules can be imported without crashes.
# This prevents "new agent broke production import" incidents.
if [[ "${SKIP_IMPORT_GATE}" != "1" ]]; then
  REMOTE_CMD+=" && python3 smoke_deploy_import_gate.py"
fi

REMOTE_CMD+=" && DEPLOY_COMMIT=\"${LOCAL_COMMIT}\" DEPLOY_DIRTY=\"${DEPLOY_DIRTY}\" python3 record_version.py >/dev/null 2>&1 || true"

if [[ -n "${SERVICE_NAME}" ]]; then
  # Stale nohup/manual command_center.py often still owns 8083; systemctl restart alone leaves it
  # serving old code → new routes 404 on disk but not in curl. Free the port, then restart the unit.
  DASH_PORT="${COMMAND_CENTER_PORT:-8083}"
  # fuser -k prints killed PIDs to stdout — suppress both fds (otherwise zsh shows "PID%" with no newline).
  REMOTE_CMD+=" && ( command -v fuser >/dev/null 2>&1 && sudo fuser -k ${DASH_PORT}/tcp >/dev/null 2>&1 || true )"
  REMOTE_CMD+=" && sudo pkill -f \"${REMOTE_DIR}/dashboard/command_center.py\" 2>/dev/null || true"
  REMOTE_CMD+=" && sleep 1"
  # Do not swallow failures — a silent skip leaves old code running (e.g. billing links missing).
  REMOTE_CMD+=" && sudo systemctl restart \"${SERVICE_NAME}\" || { echo '[deploy] ERROR: systemctl restart failed (check sudo / unit name).'; exit 1; }"
fi

REMOTE_CMD+=" && echo \"[deploy] remote steps finished.\""

echo "[deploy] Running remote setup commands..."
ssh -p "${PORT}" "${USER_NAME}@${HOST}" "${REMOTE_CMD}"

echo "[deploy] Done."
echo "[deploy] Note: rsync copies this machine's repo root \`.env\` to the server (if it exists here)."
echo "        STRIPE_PAYMENT_LINK_* for /proof must be in that file on the laptop OR added on the VM."
echo "[deploy] Next — on the server (ssh ${USER_NAME}@${HOST}):"
echo "  cd ${REMOTE_DIR}"
echo "  # Git on VM (if you use it; rsync does not update .git): git pull origin master"
echo "  # Or set upstream once: git branch --set-upstream-to=origin/master master"
echo "  curl -s -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:8083/proof   # expect 200"
if [[ -n "${SERVICE_NAME}" ]]; then
  echo "  sudo systemctl status ${SERVICE_NAME}"
  echo "  # If new routes 404 but grep finds them on disk, stale process on 8083 — run:"
  echo "  sudo ./scripts/restart_dashboard_systemd.sh"
else
  echo "  # add --service fortress-dashboard to this deploy script to auto-restart the UI after sync"
  echo "  sudo systemctl restart fortress-dashboard   # or: ./scripts/restart_dashboard.sh"
fi
echo "[deploy] Next — on this machine (once, optional): ssh-copy-id -p ${PORT} ${USER_NAME}@${HOST}"

