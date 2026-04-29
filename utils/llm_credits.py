"""
Fetch prepaid / balance information from LLM providers where HTTP APIs exist.
Also rolls up Fortress-estimated spend from data/api_costs.jsonl by service.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_API_COSTS = _ROOT / "data" / "api_costs.jsonl"


def _load_repo_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(_ROOT / ".env", override=True)
        load_dotenv(_ROOT / ".env.fortress", override=False)
    except Exception:
        pass


def _spent_usd_by_service(services: set[str], days: int = 30) -> dict[str, float]:
    out = {s: 0.0 for s in services}
    if not _API_COSTS.exists():
        return out
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    try:
        with open(_API_COSTS, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                svc = str(row.get("service") or "").lower()
                if svc not in services:
                    continue
                ts = row.get("timestamp")
                if ts:
                    try:
                        tss = str(ts)
                        if len(tss) >= 10 and tss[4] == "-" and tss[7] == "-":
                            d = datetime.fromisoformat(tss[:10]).date()
                            if d < cutoff:
                                continue
                    except Exception:
                        pass
                out[svc] += float(row.get("cost_with_cache") or 0.0)
    except OSError:
        pass
    return out


def fetch_deepseek_credits() -> dict[str, Any]:
    _load_repo_dotenv()
    key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    base: dict[str, Any] = {
        "provider": "deepseek",
        "spent_usd_30d": round(_spent_usd_by_service({"deepseek"}, 30).get("deepseek", 0.0), 6),
    }
    manual_usd = (os.getenv("FORTRESS_DEEPSEEK_CREDITS_USD") or "").strip()
    if manual_usd:
        try:
            base["manual_balance_usd"] = float(manual_usd)
            base["manual_note"] = "FORTRESS_DEEPSEEK_CREDITS_USD"
        except ValueError:
            pass
    if not key:
        base.update({"ok": False, "configured": False, "detail": "DEEPSEEK_API_KEY not set"})
        return base
    req = urllib.request.Request(
        "https://api.deepseek.com/user/balance",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        infos = body.get("balance_infos") if isinstance(body, dict) else None
        rows = infos if isinstance(infos, list) else []
        summary = []
        for bi in rows[:12]:
            if not isinstance(bi, dict):
                continue
            summary.append(
                {
                    "currency": bi.get("currency"),
                    "total_balance": bi.get("total_balance"),
                    "granted_balance": bi.get("granted_balance"),
                    "topped_up_balance": bi.get("topped_up_balance"),
                }
            )
        base.update(
            {
                "ok": True,
                "configured": True,
                "balance_infos": summary,
                "is_available": body.get("is_available") if isinstance(body, dict) else None,
            }
        )
    except urllib.error.HTTPError as e:
        base.update({"ok": False, "configured": True, "detail": f"HTTP {e.code}"})
    except Exception as e:
        base.update({"ok": False, "configured": True, "detail": f"{type(e).__name__}: {e}"[:220]})
    return base


def fetch_xai_credits() -> dict[str, Any]:
    _load_repo_dotenv()
    base: dict[str, Any] = {
        "provider": "xai",
        "spent_usd_30d": round(_spent_usd_by_service({"xai"}, 30).get("xai", 0.0), 6),
    }
    manual = (os.getenv("FORTRESS_XAI_CREDITS_USD") or "").strip()
    if manual:
        try:
            base["manual_balance_usd"] = float(manual)
            base["manual_note"] = "FORTRESS_XAI_CREDITS_USD"
        except ValueError:
            pass
    mgmt = (os.getenv("XAI_MANAGEMENT_API_KEY") or os.getenv("XAI_MANAGEMENT_KEY") or "").strip()
    team = (os.getenv("XAI_TEAM_ID") or "").strip()
    if not mgmt or not team:
        base.update(
            {
                "ok": False,
                "configured": False,
                "detail": "Add XAI_MANAGEMENT_API_KEY + XAI_TEAM_ID for prepaid API, or set FORTRESS_XAI_CREDITS_USD",
            }
        )
        return base
    url = f"https://api.x.ai/v1/billing/teams/{team}/prepaid/balance"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {mgmt}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        base.update({"ok": True, "configured": True, "prepaid": body})
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            err_body = ""
        base.update(
            {
                "ok": False,
                "configured": True,
                "detail": f"HTTP {e.code} {err_body or e.reason}",
            }
        )
    except Exception as e:
        base.update({"ok": False, "configured": True, "detail": f"{type(e).__name__}: {e}"[:220]})
    return base


def fetch_anthropic_credits() -> dict[str, Any]:
    _load_repo_dotenv()
    out: dict[str, Any] = {
        "provider": "anthropic",
        "spent_usd_30d": round(_spent_usd_by_service({"anthropic"}, 30).get("anthropic", 0.0), 6),
        "note": "Metered when agents call track_api_cost(service='anthropic', …). Vision uses direct Anthropic SDK.",
    }
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    out["api_key_present"] = bool(key)
    manual = (os.getenv("FORTRESS_ANTHROPIC_CREDITS_USD") or "").strip()
    if manual:
        try:
            out["manual_balance_usd"] = float(manual)
            out["manual_note"] = "FORTRESS_ANTHROPIC_CREDITS_USD"
        except ValueError:
            pass
    return out


def ollama_row() -> dict[str, Any]:
    return {
        "provider": "ollama",
        "mode": "local",
        "note": "Local inference — no cloud prepaid credits.",
    }


def get_llm_credit_snapshot() -> dict[str, Any]:
    """Balances / spend rollup for all LLM backends used by Fortress."""
    _load_repo_dotenv()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "providers": [
            fetch_deepseek_credits(),
            fetch_xai_credits(),
            fetch_anthropic_credits(),
            ollama_row(),
        ],
    }
