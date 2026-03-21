#!/usr/bin/env bash
# Fortress / trading-bot — first-time install (laptop, OCI VM, bare metal).
# Creates venv, installs Python deps, ensures data dirs, seeds .env if missing.
#
# Usage:
#   ./scripts/install.sh
#   INSTALL_ROOT=/opt/fortress ./scripts/install.sh
#   ./scripts/install.sh --verify        # run verify_install.sh after install
set -euo pipefail

WITH_VERIFY="0"
for arg in "$@"; do
  case "$arg" in
    --verify) WITH_VERIFY="1" ;;
    -h|--help)
      echo "Usage: $0 [--verify]"
      exit 0
      ;;
  esac
done

ROOT="${INSTALL_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"

echo "[install] repository: $ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[install] ERROR: python3 not found. Install Python 3.10+ and retry." >&2
  exit 1
fi

PYVER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "[install] python: $(command -v python3) ($PYVER)"

VENV="${VENV_PATH:-$ROOT/venv}"
if [[ ! -f "$VENV/bin/activate" ]]; then
  echo "[install] creating venv: $VENV"
  python3 -m venv "$VENV"
else
  echo "[install] using existing venv: $VENV"
fi

# shellcheck source=/dev/null
source "$VENV/bin/activate"

echo "[install] upgrading pip"
python3 -m pip install --upgrade pip setuptools wheel

echo "[install] installing requirements (this may take several minutes)"
python3 -m pip install -r "$ROOT/requirements.txt"

mkdir -p "$ROOT/logs" "$ROOT/data"

ENV_FILE="$ROOT/.env"
ENV_EX="$ROOT/.env.example"
if [[ ! -f "$ENV_FILE" && -f "$ENV_EX" ]]; then
  cp "$ENV_EX" "$ENV_FILE"
  echo "[install] created $ENV_FILE from .env.example — edit with your Alpaca paper keys."
elif [[ ! -f "$ENV_FILE" ]]; then
  echo "[install] WARNING: no .env.example found; create .env manually." >&2
fi

export PYTHONPATH="${PYTHONPATH:-$ROOT}"
echo "[install] PYTHONPATH=$PYTHONPATH"

if [[ "$WITH_VERIFY" == "1" ]]; then
  echo "[install] running verification..."
  bash "$ROOT/scripts/verify_install.sh"
else
  echo "[install] done. Next:"
  echo "  1) Edit $ENV_FILE (Alpaca paper keys, etc.)"
  echo "  2) Run: ./scripts/verify_install.sh"
  echo "  3) Run: ./scripts/restart_dashboard.sh"
  echo "  4) Optional (OCI, as root): sudo ./scripts/install_systemd.sh"
fi
