#!/usr/bin/env bash
# Fortress Trading Bot – first-run setup.
# Run from project root: ./setup.sh
# Does not overwrite existing .env or config; creates dirs and templates if missing.

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "=== Fortress Setup ==="

# 1. Python
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found. Install Python 3.10+."
  exit 1
fi
echo "  Python: $(python3 --version)"

# 2. Venv (optional but recommended)
if [ ! -d "venv" ]; then
  echo "  Creating venv..."
  python3 -m venv venv
fi
if [ -d "venv" ]; then
  echo "  Activating venv..."
  # shellcheck source=/dev/null
  source venv/bin/activate
fi

# 3. .env from example if missing
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo "  Created .env from .env.example – add your Alpaca (and optional) keys."
  else
    echo "  WARNING: No .env or .env.example found."
  fi
else
  echo "  .env exists (not overwritten)."
fi

# 4. data/ and config/
mkdir -p data config
if [ ! -f "config/watchlist.json" ]; then
  if [ -f "config/watchlist.json.example" ]; then
    cp config/watchlist.json.example config/watchlist.json
    echo "  Created config/watchlist.json from example."
  else
    echo '{"quality_stocks":[{"ticker":"AAPL","sector":"Technology","name":"Apple"}]}' > config/watchlist.json
    echo "  Created minimal config/watchlist.json."
  fi
fi

# 5. Dependencies
if [ -f "requirements.txt" ]; then
  echo "  Installing dependencies..."
  pip install -q -r requirements.txt
fi

# 6. Health check
echo ""
echo "Running health check..."
if python3 check_health.py; then
  echo ""
  echo "Setup complete."
  echo ""
  echo "NEXT: Run the dashboard and finish in your browser (no terminal needed after that):"
  echo "  ./start_dashboard.sh"
  echo "  Then open: http://localhost:8083"
  echo "  Use the setup page to enter your Alpaca keys. See docs/CUSTOMER_INSTALL.md for details."
else
  echo ""
  echo "Health check reported issues (see above). Fix env/config and run: python3 check_health.py"
fi
echo "=== Setup complete ==="
