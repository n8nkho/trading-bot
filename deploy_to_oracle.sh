#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage:"
  echo "  ./deploy_to_oracle.sh --host HOST --user USER --remote-dir DIR [--port PORT] [--venv VENV_DIR] [--service SERVICE_NAME] [--skip-import-gate] [--install-deps]"
  echo ""
  echo "Examples:"
  echo "  ./deploy_to_oracle.sh --host 1.2.3.4 --user ubuntu --remote-dir /home/ubuntu/trading-bot --venv /home/ubuntu/trading-bot/venv --service fortress-dashboard"
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
  REMOTE_CMD+=" && (sudo systemctl restart \"${SERVICE_NAME}\" || true)"
fi

echo "[deploy] Running remote setup commands..."
ssh -p "${PORT}" "${USER_NAME}@${HOST}" "${REMOTE_CMD}"

echo "[deploy] Done."
echo "[deploy] Next — on the server (ssh ${USER_NAME}@${HOST}):"
echo "  cd ${REMOTE_DIR}"
echo "  curl -s -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:8083/proof   # expect 200"
if [[ -n "${SERVICE_NAME}" ]]; then
  echo "  sudo systemctl status ${SERVICE_NAME}"
else
  echo "  # add --service fortress-dashboard to this deploy script to auto-restart the UI after sync"
  echo "  sudo systemctl restart fortress-dashboard   # or: ./scripts/restart_dashboard.sh"
fi
echo "[deploy] Next — on this machine (once, optional): ssh-copy-id -p ${PORT} ${USER_NAME}@${HOST}"

