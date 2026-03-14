#!/usr/bin/env python3
"""
Generate a signed license for a customer tier.

Usage (from project root):
  python scripts/generate_license.py pro "Acme Corp" 2026-12-31
  python scripts/generate_license.py starter "Retail User"
  python scripts/generate_license.py master   # internal only; no signature needed

Output: JSON suitable for data/license.json. For master, no signature.
For starter/pro/enterprise, prints signature so you can paste into license.json.
Uses same secret as config/license.py (_LICENSE_SECRET); in production use env var.
"""

import hashlib
import hmac
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Must match config/license.py
_SECRET = b"fortress-license-v1-change-in-production"


def sign(payload: str) -> str:
    return hmac.new(_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def main():
    if len(sys.argv) < 2:
        print("Usage: generate_license.py <tier> [customer_id] [expiry_iso]")
        print("  tier: master | starter | pro | enterprise")
        sys.exit(1)
    tier = sys.argv[1].strip().lower()
    customer_id = sys.argv[2].strip() if len(sys.argv) > 2 else ""
    expiry = sys.argv[3].strip() if len(sys.argv) > 3 else ""

    if tier == "master":
        out = {"tier": "master", "name": "Master (internal)", "max_tenants": 1}
        print(json.dumps(out, indent=2))
        return

    payload = f"{tier}|{expiry}|{customer_id}"
    sig = sign(payload)
    out = {
        "tier": tier,
        "name": f"{tier.capitalize()} Plan",
        "customer_id": customer_id or "default",
        "expiry": expiry or None,
        "max_tenants": 1,
        "license_key": "issued",
        "signature": sig,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
