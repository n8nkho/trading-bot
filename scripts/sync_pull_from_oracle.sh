#!/usr/bin/env bash
# Pull the repo FROM Oracle → this Mac clone (Oracle = source of truth for *code*).
# Run on your Mac from the repo root.
#
# IMPORTANT:
#   `deploy_to_oracle.sh` does NOT sync `.git/` to Oracle. If you use rsync --delete
#   pulling back, you can WIPE your Mac's `.git` and corrupt the repo. This script
#   does NOT use --delete by default (overlay only). See docs/SYNC_ORACLE_SOURCE_OF_TRUTH.md
#
# Usage:
#   ./scripts/sync_pull_from_oracle.sh ubuntu@YOUR_ORACLE_IP
#   REMOTE_DIR=/home/ubuntu/trading-bot ./scripts/sync_pull_from_oracle.sh ubuntu@YOUR_ORACLE_IP
#
# Optional: prune Mac files missing on Oracle (DANGEROUS — read the doc first):
#   SYNC_PULL_DELETE=1 ./scripts/sync_pull_from_oracle.sh ubuntu@HOST
#
set -euo pipefail

REMOTE_SSH="${1:?Usage: $0 ubuntu@oracle_public_ip_or_host}"
REMOTE_DIR="${REMOTE_DIR:-/home/ubuntu/trading-bot}"
TARGET="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[sync] SOURCE (code): ${REMOTE_SSH}:${REMOTE_DIR}/"
echo "[sync] DEST (Mac):     ${TARGET}/"

RSYNC_EXCLUDES=(
  --exclude 'venv/'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '.env'
  --exclude 'data/'
  --exclude 'logs/*.log'
  --exclude '.git/'
)

# Never merge Oracle's .git into Mac (deploy doesn't ship a full repo; partial .git is toxic).
RSYNC_DELETE=()
if [[ "${SYNC_PULL_DELETE:-}" == "1" ]]; then
  echo "[sync] WARN: SYNC_PULL_DELETE=1 — deleting on Mac anything not on Oracle (except protected paths)." >&2
  RSYNC_DELETE=(--delete)
  # rsync 3.x: do not remove local .git / .env / .cursor even if absent on sender
  if rsync --help 2>&1 | grep -q -- '--filter'; then
    RSYNC_DELETE+=(
      --filter='protect .git/'
      --filter='protect .env'
      --filter='protect .cursor/'
    )
  else
    echo "[sync] ERROR: rsync too old for safe --delete; install rsync 3+ or omit SYNC_PULL_DELETE." >&2
    exit 1
  fi
else
  echo "[sync] overlay only (no --delete). Your Mac .git/ is never removed by this script."
fi

# macOS Bash 3.2 + set -u: "${empty[@]}" is "unbound". Only expand when non-empty.
rsync -avz \
  ${RSYNC_DELETE[@]+"${RSYNC_DELETE[@]}"} \
  -e "ssh -o StrictHostKeyChecking=accept-new" \
  "${RSYNC_EXCLUDES[@]}" \
  "${REMOTE_SSH}:${REMOTE_DIR}/" "${TARGET}/"

echo "[sync] Done. Next: cd \"${TARGET}\" && git status"
echo "[sync] Daily ops reports (if generated on Oracle): ${TARGET}/reports/ops_daily/ — see docs/DAILY_OPS_REVIEW.md"
