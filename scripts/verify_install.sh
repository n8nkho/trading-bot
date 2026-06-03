#!/usr/bin/env bash
# Verify a Fortress / trading-bot install (import gate + optional smoke tests).
#
# Usage:
#   ./scripts/verify_install.sh           # import gate + deterministic smoke
#   ./scripts/verify_install.sh --quick   # import gate only
#   INSTALL_ROOT=/path ./scripts/verify_install.sh
set -euo pipefail

QUICK="0"
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK="1" ;;
    -h|--help)
      echo "Usage: $0 [--quick]"
      exit 0
      ;;
  esac
done

ROOT="${INSTALL_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"
VENV="${VENV_PATH:-$ROOT/venv}"

if [[ ! -f "$VENV/bin/activate" ]]; then
  echo "[verify] ERROR: venv not found at $VENV — run ./scripts/install.sh first." >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$VENV/bin/activate"
export PYTHONPATH="${PYTHONPATH:-$ROOT}"

echo "[verify] import gate..."
python3 "$ROOT/smoke_deploy_import_gate.py"

echo "[verify] operator run registry smoke..."
python3 "$ROOT/smoke_operator_run_registry.py"

echo "[verify] pre-trade gate smoke..."
python3 "$ROOT/smoke_pre_trade_gate.py"

echo "[verify] option notional gate smoke..."
python3 "$ROOT/smoke_option_notional_gate.py"

echo "[verify] trust ledger chain smoke..."
python3 "$ROOT/smoke_trust_ledger_chain.py"

echo "[verify] operator morning brief smoke..."
python3 "$ROOT/smoke_operator_morning_brief.py"

echo "[verify] tradingview webhook smoke..."
python3 "$ROOT/smoke_tradingview_webhook.py"

if [[ "$QUICK" == "1" ]]; then
  echo "[verify] --quick: skipping smoke_test_end_to_end"
  echo "[verify] OK (quick)"
  exit 0
fi

echo "[verify] deterministic end-to-end smoke (no live screener)..."
SMOKE_SKIP_LIVE_SCREENER=1 python3 "$ROOT/smoke_test_end_to_end.py"

if [[ -n "${ALPACA_API_KEY:-}" && -n "${ALPACA_SECRET_KEY:-}" ]]; then
  echo "[verify] Alpaca paper submit+cancel (optional; needs network)..."
  python3 "$ROOT/smoke_alpaca_paper_trade_cancel.py"
else
  echo "[verify] skip smoke_alpaca_paper_trade_cancel (no Alpaca keys in env)"
fi

echo "[verify] dashboard entry + Flask stack..."
python3 << 'PY'
from pathlib import Path
import ast
import flask  # noqa: F401
import flask_cors  # noqa: F401
# cwd is repo root (set by verify_install.sh)
p = Path("dashboard/command_center.py")
ast.parse(p.read_text(encoding="utf-8"))
print("[verify] command_center.py parses; flask OK")
PY

echo "[verify] OK"
