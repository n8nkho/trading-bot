#!/usr/bin/env bash
# Build a customer-ready tarball (no data/, .env, venv, or secrets).
# Run from project root: ./scripts/build_customer_package.sh
# Output: fortress-<VERSION>.tar.gz (in dist/ or project root).
# Customer receives this plus their data/license.json. See docs/SELL_READINESS_ANALYSIS.md.

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="1.0.0"
if [ -f "VERSION" ]; then
  VERSION="$(cat VERSION | tr -d '[:space:]')"
fi
OUTNAME="fortress-${VERSION}.tar.gz"
mkdir -p dist 2>/dev/null || true
OUT="${ROOT}/dist/${OUTNAME}"

echo "Building customer package: ${OUTNAME}"
echo "Excluding: data/, .env, venv, .git, dist/, __pycache__, *.pyc, .cursor, logs/"
tar czf "$OUT" -C "$ROOT" \
  --exclude='data' \
  --exclude='.env' \
  --exclude='venv' \
  --exclude='.git' \
  --exclude='dist' \
  --exclude='*__pycache__*' \
  --exclude='*.pyc' \
  --exclude='.cursor' \
  --exclude='logs' \
  --exclude='*.log' \
  --exclude='data_backup_*' \
  .

echo "Created: $OUT"
echo "Send this file plus the customer's data/license.json (and docs/CUSTOMER_GUIDE.md link)."
