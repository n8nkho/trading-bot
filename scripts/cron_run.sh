#!/usr/bin/env bash
# Run orchestrator from repo root with the project venv (fixes wrong cwd in cron).
# Usage in crontab:  $REPO/scripts/cron_run.sh screen >> $REPO/logs/orchestrator.log 2>&1
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
PY="${REPO_ROOT}/venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

if [[ "${1:-}" == "screen" && "${FORTRESS_UPLIFT_AUTO_PROMOTE_AFTER_SCREEN:-0}" == "1" ]]; then
  "$PY" -u "${REPO_ROOT}/orchestrator.py" "$@"
  screen_rc=$?
  # Cron-safe: never block daily screen completion due to auto-promotion checks.
  "$PY" -u "${REPO_ROOT}/orchestrator.py" uplift_auto_promote --apply --required-clean-sessions "${FORTRESS_UPLIFT_REQUIRED_CLEAN_SESSIONS:-5}" || true
  exit "$screen_rc"
fi

exec "$PY" -u "${REPO_ROOT}/orchestrator.py" "$@"
