"""
Map Stripe subscription webhooks → Fortress license JSON (Lanes 2–3).

Set env:
  STRIPE_WEBHOOK_SECRET       — from Stripe Dashboard → Webhooks → signing secret
  STRIPE_PRICE_STARTER        — Price ID for Starter (price_...)
  STRIPE_PRICE_PRO            — Price ID for Pro
  STRIPE_PRICE_ENTERPRISE     — Price ID for Enterprise
  STRIPE_LICENSE_OUT_PATH     — default: data/stripe_license.json
  STRIPE_SECRET_KEY           — optional; needed for checkout.session.completed when subscription is only an id

Customer should set:
  FORTRESS_LICENSE_PATH       — same path as STRIPE_LICENSE_OUT_PATH (or symlink)
and remove fixed FORTRESS_LICENSE_TIER if the file should win.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def price_id_to_tier(price_id: str) -> Optional[str]:
    pid = (price_id or "").strip()
    if not pid:
        return None
    mapping = {
        (os.environ.get("STRIPE_PRICE_STARTER") or "").strip(): "starter",
        (os.environ.get("STRIPE_PRICE_PRO") or "").strip(): "pro",
        (os.environ.get("STRIPE_PRICE_ENTERPRISE") or "").strip(): "enterprise",
    }
    mapping = {k: v for k, v in mapping.items() if k}
    return mapping.get(pid)


def _subscription_to_license(sub: Dict[str, Any]) -> Dict[str, Any]:
    status = str(sub.get("status") or "").lower()
    valid = status in ("active", "trialing")

    price_id = ""
    items = (sub.get("items") or {}).get("data") or []
    if items and isinstance(items[0], dict):
        price = items[0].get("price") or {}
        if isinstance(price, dict):
            price_id = str(price.get("id") or "")

    tier = price_id_to_tier(price_id)
    if tier is None:
        tier = "starter"
    names = {"starter": "Starter", "pro": "Pro", "enterprise": "Enterprise"}
    name = names.get(tier, tier.title())

    expires_at = None
    cpe = sub.get("current_period_end")
    if cpe is not None:
        try:
            expires_at = datetime.fromtimestamp(int(cpe), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            pass

    return {
        "tier": tier,
        "name": name,
        "valid": valid,
        "expires_at": expires_at,
        "source": "stripe",
        "stripe_subscription_id": sub.get("id"),
        "stripe_price_id": price_id,
        "stripe_status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _retrieve_subscription(sub_id: str) -> Optional[Dict[str, Any]]:
    key = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
    if not key or not sub_id:
        return None
    try:
        import stripe

        stripe.api_key = key
        sub = stripe.Subscription.retrieve(sub_id)
        if hasattr(sub, "to_dict"):
            return sub.to_dict()
        return dict(sub)
    except Exception:
        return None


def license_from_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Return a license dict to write, or None if this event type is ignored.
    """
    etype = event.get("type")
    obj = (event.get("data") or {}).get("object")
    if not isinstance(obj, dict):
        return None

    if etype in ("customer.subscription.created", "customer.subscription.updated"):
        return _subscription_to_license(obj)

    if etype == "customer.subscription.deleted":
        lic = _subscription_to_license(obj)
        lic["valid"] = False
        return lic

    if etype == "checkout.session.completed":
        mode = (obj.get("mode") or "").strip()
        if mode != "subscription":
            return None
        sub_field = obj.get("subscription")
        if isinstance(sub_field, dict):
            return _subscription_to_license(sub_field)
        if isinstance(sub_field, str):
            full = _retrieve_subscription(sub_field)
            if full:
                return _subscription_to_license(full)
        return None

    return None


def write_license_atomic(license_dict: Dict[str, Any]) -> Path:
    out = (os.environ.get("STRIPE_LICENSE_OUT_PATH") or "").strip()
    path = Path(out) if out else _root() / "data" / "stripe_license.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(license_dict, indent=2)
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)
    return path


def process_stripe_webhook_event(event: Dict[str, Any]) -> Optional[Path]:
    """
    Build license from verified Stripe event and write file. Returns path if written.
    """
    lic = license_from_event(event)
    if lic is None:
        return None
    return write_license_atomic(lic)
