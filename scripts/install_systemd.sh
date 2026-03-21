#!/usr/bin/env bash
# Install systemd unit for Fortress Command Center (Linux servers, e.g. Oracle OCI).
# Must run as root. Stops any existing dashboard on 8083 before enabling service.
#
# Usage:
#   sudo ./scripts/install_systemd.sh
#   sudo FORTRESS_USER=ubuntu FORTRESS_HOME=/home/ubuntu/trading-bot ./scripts/install_systemd.sh
#   sudo ./scripts/install_systemd.sh --now    # enable and start immediately
set -euo pipefail

START_NOW="0"
for arg in "$@"; do
  case "$arg" in
    --now) START_NOW="1" ;;
    -h|--help)
      echo "Usage: sudo $0 [--now]"
      exit 0
      ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run as root (sudo)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_HOME="$(cd "$SCRIPT_DIR/.." && pwd)"
FORTRESS_HOME="${FORTRESS_HOME:-$DEFAULT_HOME}"
FORTRESS_USER="${FORTRESS_USER:-${SUDO_USER:-$(logname 2>/dev/null || echo ubuntu)}}"
FORTRESS_GROUP="${FORTRESS_GROUP:-$(id -gn "$FORTRESS_USER" 2>/dev/null || echo "$FORTRESS_USER")}"

TEMPLATE="$FORTRESS_HOME/deploy/systemd/fortress-dashboard.service.template"
UNIT_DST="/etc/systemd/system/fortress-dashboard.service"

if [[ ! -f "$TEMPLATE" ]]; then
  echo "ERROR: template not found: $TEMPLATE" >&2
  exit 1
fi

if [[ ! -x "$FORTRESS_HOME/venv/bin/python3" ]]; then
  echo "ERROR: venv missing at $FORTRESS_HOME/venv — run ./scripts/install.sh first." >&2
  exit 1
fi

mkdir -p "$FORTRESS_HOME/logs" "$FORTRESS_HOME/data"
chown -R "$FORTRESS_USER:$FORTRESS_GROUP" "$FORTRESS_HOME/logs" "$FORTRESS_HOME/data" 2>/dev/null || true

TMP="$(mktemp)"
sed -e "s|@FORTRESS_HOME@|${FORTRESS_HOME}|g" \
    -e "s|@FORTRESS_USER@|${FORTRESS_USER}|g" \
    -e "s|@FORTRESS_GROUP@|${FORTRESS_GROUP}|g" \
    "$TEMPLATE" >"$TMP"
install -m 0644 "$TMP" "$UNIT_DST"
rm -f "$TMP"

systemctl daemon-reload
systemctl enable fortress-dashboard.service
echo "[systemd] installed $UNIT_DST (user=$FORTRESS_USER home=$FORTRESS_HOME)"

if [[ "$START_NOW" == "1" ]]; then
  # Free port if old nohup process is still bound
  if command -v fuser >/dev/null 2>&1; then
    fuser -k 8083/tcp 2>/dev/null || true
  fi
  systemctl restart fortress-dashboard.service
  systemctl --no-pager status fortress-dashboard.service || true
  echo "[systemd] started. Check: curl -s -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:8083/proof"
else
  echo "[systemd] enabled. Start with: sudo systemctl start fortress-dashboard.service"
fi
