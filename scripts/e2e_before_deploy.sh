#!/usr/bin/env bash
# End-to-end gate for trading-bot — run before git commit / deploy.
#
# Primary: ./scripts/verify_install.sh (import gate + smoke scripts + deterministic e2e smoke).
# Optional: set RUN_UNIT_TESTS=1 to also run `python3 -m unittest discover` (some tests need pytest;
# install with: pip install pytest).
#
# Usage:
#   ./scripts/e2e_before_deploy.sh
#   ./scripts/e2e_before_deploy.sh --quick
#   RUN_UNIT_TESTS=1 ./scripts/e2e_before_deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="${ROOT}/venv"
if [[ ! -f "${VENV}/bin/activate" ]]; then
  echo "[e2e:tb] ERROR: venv not found at ${VENV} — run ./scripts/install.sh first." >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${VENV}/bin/activate"
export PYTHONPATH="${PYTHONPATH:-}:${ROOT}"

EXTRA=()
for arg in "$@"; do
  case "$arg" in
    -h|--help)
      echo "Usage: $0 [--quick]"
      echo "Env: RUN_UNIT_TESTS=1 — also run unittest discover (pytest may be required for some modules)."
      exit 0
      ;;
    *)
      EXTRA+=("$arg")
      ;;
  esac
done

echo "[e2e:tb] repo root: ${ROOT}"

echo "[e2e:tb] verify_install.sh (${EXTRA[*]:-full})..."
"${ROOT}/scripts/verify_install.sh" "${EXTRA[@]}"

echo "[e2e:tb] policy / drift activity gate smoke..."
python3 -m pytest tests/test_trading_activity_drift_gate.py tests/test_policy_guardrails_drift_rollback.py -q --tb=short

if [[ "${RUN_UNIT_TESTS:-}" == "1" ]]; then
  echo "[e2e:tb] RUN_UNIT_TESTS=1 — unittest discover..."
  python3 -m unittest discover -s tests -p 'test_*.py' -v
fi

echo "[e2e:tb] OK — safe to commit/deploy"
