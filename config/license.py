"""
License and plan for tiered deployments.

Reads data/license.json. Master (internal) uses tier "master" with no restrictions.
Customer deployments use tier "starter" | "pro" | "enterprise"; features are gated
in config/tiers.py. Optional signature prevents customers from editing tier in the file.

Schema (data/license.json):
  - tier: "master" | "starter" | "pro" | "enterprise"
  - name: display name (e.g. "Pro Plan")
  - expiry: optional ISO date string; if past, treat as Starter
  - license_key: optional; if present, signature is validated
  - signature: Ed25519 (base64) or legacy HMAC-SHA256 hex
  - integrity_check: optional bool; if true and data/integrity_manifest.json exists,
    core file hashes are checked; on mismatch plan is downgraded to Starter.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from config.tiers import (
    TIER_MASTER,
    get_tier_spec,
    TIER_SPECS,
    TierSpec,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LICENSE_FILE = PROJECT_ROOT / "data" / "license.json"
INTEGRITY_MANIFEST = PROJECT_ROOT / "data" / "integrity_manifest.json"
LICENSE_PUBLIC_KEY = PROJECT_ROOT / "config" / "license_public.pem"

# Cache integrity result per process so we don't re-hash on every get_plan().
_integrity_ok: Optional[bool] = None

# Legacy HMAC fallback for old licenses only (not used for new licenses).
_VERIFICATION_FALLBACK = b"fortress-license-v1-change-in-production"


def _get_license_secret() -> bytes:
    raw = os.environ.get("LICENSE_SIGNING_SECRET", "").strip()
    return raw.encode("utf-8") if raw else _VERIFICATION_FALLBACK


def _verify_signature_ed25519(payload: str, signature_b64: str) -> bool:
    """Verify Ed25519 signature using config/license_public.pem (no secret in code)."""
    if not signature_b64 or not payload or not LICENSE_PUBLIC_KEY.exists():
        return False
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from cryptography.exceptions import InvalidSignature
        key_bytes = LICENSE_PUBLIC_KEY.read_bytes()
        public_key = load_pem_public_key(key_bytes)
        sig = base64.b64decode(signature_b64, validate=True)
        public_key.verify(sig, payload.encode("utf-8"))
        return True
    except Exception:
        return False


@dataclass
class Plan:
    """License plan; tier drives feature set via config.tiers."""
    name: str = "dev-unlimited"
    tier: str = TIER_MASTER
    max_tenants: int = 1
    max_strategies: int = 999
    max_universe_size: int = 10000
    auto_trading_allowed: bool = True
    expiry: Optional[datetime] = None
    valid: bool = True  # False if signature invalid or expired


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            with open(path) as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def _verify_signature(payload: str, signature: str) -> bool:
    if not signature or not payload:
        return False
    # New licenses: Ed25519 base64 (no hardcoded secret; public key in config/).
    if len(signature) != 64 or not all(c in "0123456789abcdef" for c in signature.lower()):
        return _verify_signature_ed25519(payload, signature)
    # Legacy: HMAC hex (fallback secret only for old licenses).
    secret = _get_license_secret()
    if not secret:
        return False
    expected = hmac.new(
        secret,
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def get_plan() -> Plan:
    data = _read_json(LICENSE_FILE)
    if not data:
        return Plan(tier=TIER_MASTER)

    tier = (data.get("tier") or TIER_MASTER).strip().lower()
    name = str(data.get("name", "dev-unlimited"))
    expiry = None
    if data.get("expiry"):
        try:
            expiry = datetime.fromisoformat(data["expiry"].replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    valid = True
    if data.get("license_key") and data.get("signature"):
        payload = f"{tier}|{data.get('expiry', '')}|{data.get('customer_id', '')}"
        if not _verify_signature(payload, data["signature"]):
            valid = False
            tier = "starter"  # Downgrade on invalid signature
        if expiry and datetime.now(timezone.utc) > expiry:
            valid = False
            tier = "starter"  # Downgrade on expiry

    # Optional: enforce core file integrity when license has integrity_check and manifest exists
    if valid and data.get("integrity_check") and INTEGRITY_MANIFEST.exists():
        global _integrity_ok
        if _integrity_ok is None:
            try:
                from utils.integrity import check_integrity
                _integrity_ok, _ = check_integrity(INTEGRITY_MANIFEST)
            except Exception:
                _integrity_ok = False
        if not _integrity_ok:
            valid = False
            tier = "starter"  # Downgrade on tampered core

    spec = get_tier_spec(tier)
    return Plan(
        name=name,
        tier=tier,
        max_tenants=int(data.get("max_tenants", 1)),
        max_strategies=spec.max_strategies,
        max_universe_size=spec.max_universe_size,
        auto_trading_allowed=spec.auto_trading_allowed and valid,
        expiry=expiry,
        valid=valid,
    )


def get_tier_spec_from_plan() -> TierSpec:
    """Convenience: tier spec for current plan."""
    plan = get_plan()
    return get_tier_spec(plan.tier)
