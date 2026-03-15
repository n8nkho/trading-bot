#!/usr/bin/env python3
"""
Generate a signed license for a customer tier.

Usage (from project root):
  python scripts/generate_license_keypair.py   # once: creates random key pair (no hardcoded secret)
  python scripts/generate_license.py pro "Acme Corp" 2026-12-31
  python scripts/generate_license.py starter "Retail User"
  python scripts/generate_license.py master   # internal only; no signature needed

Uses Ed25519 private key from data/.license_private.pem (created by generate_license_keypair.py).
Legacy: LICENSE_SIGNING_SECRET still works for HMAC-signed licenses.
"""

import base64
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PRIVATE_KEY_PATH = ROOT / "data" / ".license_private.pem"


def _load_private_key():
    """Load Ed25519 private key from file or env path."""
    path = os.environ.get("LICENSE_SIGNING_KEY", "").strip() or PRIVATE_KEY_PATH
    path = Path(path)
    if not path.exists():
        return None
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        key_bytes = path.read_bytes()
        return load_pem_private_key(key_bytes, password=None)
    except Exception:
        return None


def _sign_ed25519(payload: str) -> str:
    key = _load_private_key()
    if key is None:
        raise SystemExit(
            "No license signing key. Run: python scripts/generate_license_keypair.py\n"
            "That creates a random key pair (data/.license_private.pem + config/license_public.pem)."
        )
    sig = key.sign(payload.encode("utf-8"))
    return base64.b64encode(sig).decode("ascii")


def _sign_hmac(payload: str) -> str:
    raw = os.environ.get("LICENSE_SIGNING_SECRET", "").strip()
    secret = raw.encode("utf-8") if raw else b""
    if not secret:
        raise SystemExit("LICENSE_SIGNING_SECRET is not set (legacy HMAC mode).")
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def sign(payload: str) -> str:
    if _load_private_key() is not None:
        return _sign_ed25519(payload)
    return _sign_hmac(payload)


def main():
    if len(sys.argv) < 2:
        print("Usage: generate_license.py <tier> [customer_id] [expiry_iso]")
        print("  tier: master (vendor only) | starter | growth | pro | enterprise")
        sys.exit(1)
    tier = sys.argv[1].strip().lower()
    if tier not in ("master", "starter", "growth", "pro", "enterprise"):
        print("Invalid tier. Use: master | starter | growth | pro | enterprise")
        sys.exit(1)
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
