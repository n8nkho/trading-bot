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
  - signature: optional; HMAC-SHA256(license_key, tier|expiry|customer_id) in hex
"""

from __future__ import annotations

import hashlib
import hmac
import json
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

# Server-side secret for signature verification (in production set via env or secure store)
# Customers never see this; only your build/deploy has it to generate signed licenses.
_LICENSE_SECRET = b"fortress-license-v1-change-in-production"


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


def _verify_signature(payload: str, signature_hex: str) -> bool:
    if not signature_hex or not payload:
        return False
    expected = hmac.new(
        _LICENSE_SECRET,
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_hex.lower())


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
