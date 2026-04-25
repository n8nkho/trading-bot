#!/bin/bash
# Run once on the VM to permanently add Fortress flags to ~/.bashrc
# Usage: bash deploy/install_env_flags.sh

set -e

BASHRC="$HOME/.bashrc"
MARKER="# Fortress flags — auto-added by install_env_flags.sh"

if grep -q "$MARKER" "$BASHRC"; then
  echo "Fortress flags already present in $BASHRC — skipping."
  exit 0
fi

cat >> "$BASHRC" << 'EOF'

# Fortress flags — auto-added by install_env_flags.sh
source /home/ubuntu/trading-bot/.env.fortress
EOF

echo "Flags added to $BASHRC"
echo "Run: source ~/.bashrc"
