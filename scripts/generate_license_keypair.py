#!/usr/bin/env python3
"""
Generate a random Ed25519 key pair for license signing (vendor only).

Run once from project root. Creates:
  - data/.license_private.pem  (gitignored; keep secret, back up)
  - config/license_public.pem  (committed; shipped so customers can verify)

Then generate licenses with:
  python scripts/generate_license.py starter "Customer" 2026-12-31
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_PATH = ROOT / "data" / ".license_private.pem"
PUBLIC_PATH = ROOT / "config" / "license_public.pem"


def main():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    if PRIVATE_PATH.exists() or PUBLIC_PATH.exists():
        print("Key pair already exists.")
        print(f"  Private: {PRIVATE_PATH}")
        print(f"  Public:  {PUBLIC_PATH}")
        return

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    PRIVATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRIVATE_PATH.write_bytes(private_pem)
    PUBLIC_PATH.write_bytes(public_pem)

    print("License key pair generated (random, not hardcoded).")
    print(f"  Private: {PRIVATE_PATH}  (gitignored; back this up)")
    print(f"  Public:  {PUBLIC_PATH}  (commit; used for verification)")
    print("Generate licenses with: python scripts/generate_license.py <tier> [customer_id] [expiry]")


if __name__ == "__main__":
    main()
