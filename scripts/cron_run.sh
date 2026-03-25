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
exec "$PY" -u "${REPO_ROOT}/orchestrator.py" "$@"
