#!/bin/bash
# Install Command Center as a systemd service (starts on boot, restarts on crash).
# Run from project root: sudo bash scripts/install_command_center_service.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SVC="fortress-command-center.service"

cp "$ROOT/scripts/$SVC" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SVC"
systemctl start "$SVC"
echo "Command Center service installed and started."
echo "  status: sudo systemctl status $SVC"
echo "  logs:   journalctl -u $SVC -f"
echo "  stop:   sudo systemctl stop $SVC"
