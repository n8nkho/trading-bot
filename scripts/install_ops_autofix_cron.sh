#!/usr/bin/env bash
# Install or update a single cron entry for ops_autofix.
# Default mode is --dry-run (safe rollout). Use --apply to promote.
set -euo pipefail

MODE="dry-run"
MINUTE="10"
REPO=""
CRON_FILE=""

usage() {
  cat <<'EOF'
Usage:
  ./scripts/install_ops_autofix_cron.sh [--dry-run|--apply] [--minute N] [--repo /path/to/trading-bot] [--crontab-file /tmp/cron]

Examples:
  ./scripts/install_ops_autofix_cron.sh --dry-run
  ./scripts/install_ops_autofix_cron.sh --apply
  ./scripts/install_ops_autofix_cron.sh --dry-run --minute 15

Notes:
  - Idempotent: updates existing ops_autofix entry and avoids duplicates.
  - Removes opposite mode if present (dry-run vs apply).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) MODE="dry-run" ;;
    --apply) MODE="apply" ;;
    --minute)
      shift
      MINUTE="${1:-}"
      ;;
    --repo)
      shift
      REPO="${1:-}"
      ;;
    --crontab-file)
      shift
      CRON_FILE="${1:-}"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
  shift
done

if [[ -z "$REPO" ]]; then
  REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
if [[ ! -d "$REPO" ]]; then
  echo "ERROR: repo path not found: $REPO" >&2
  exit 1
fi
if [[ ! "$MINUTE" =~ ^[0-9]+$ ]] || (( MINUTE < 0 || MINUTE > 59 )); then
  echo "ERROR: --minute must be an integer 0..59 (got '$MINUTE')." >&2
  exit 1
fi

mkdir -p "$REPO/logs"

BASE_LINE="${MINUTE} * * * * ${REPO}/scripts/cron_run.sh ops_autofix"
if [[ "$MODE" == "dry-run" ]]; then
  TARGET_LINE="${BASE_LINE} --dry-run >> ${REPO}/logs/ops_autofix.log 2>&1"
  REMOVE_RE='ops_autofix( |$).*(>> .*ops_autofix\.log)'
else
  TARGET_LINE="${BASE_LINE} >> ${REPO}/logs/ops_autofix.log 2>&1"
  REMOVE_RE='ops_autofix --dry-run( |$).*(>> .*ops_autofix\.log)'
fi

TMP="$(mktemp)"
cleanup() { rm -f "$TMP"; }
trap cleanup EXIT

if [[ -n "$CRON_FILE" ]]; then
  if [[ -f "$CRON_FILE" ]]; then
    cp "$CRON_FILE" "$TMP"
  else
    : > "$TMP"
  fi
else
  crontab -l > "$TMP" 2>/dev/null || : > "$TMP"
fi

# 1) Remove previous ops_autofix job lines to keep one canonical entry.
# 2) Remove opposite-mode legacy line.
python3 - "$TMP" "$TARGET_LINE" "$REMOVE_RE" <<'PY'
import re
import sys
from pathlib import Path

p = Path(sys.argv[1])
target = sys.argv[2]
remove_re = re.compile(sys.argv[3])

lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
out = []
for ln in lines:
    s = ln.strip()
    if not s or s.startswith("#"):
        out.append(ln)
        continue
    if "cron_run.sh" in s and "ops_autofix" in s:
        continue
    if remove_re.search(s):
        continue
    out.append(ln)
out.append(target)
p.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY

if [[ -n "$CRON_FILE" ]]; then
  cp "$TMP" "$CRON_FILE"
  echo "[ops_autofix_cron] Updated file: $CRON_FILE"
else
  crontab "$TMP"
  echo "[ops_autofix_cron] Installed into user crontab."
fi

echo "[ops_autofix_cron] mode=$MODE minute=$MINUTE"
echo "[ops_autofix_cron] line: $TARGET_LINE"
