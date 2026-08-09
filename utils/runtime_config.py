"""
Declarative runtime config (Fortress \"B\" layer).

Loads ``config/fortress_runtime.yaml`` if present, merged over built-in defaults.
Override path with env ``FORTRESS_RUNTIME_CONFIG``.

Policy risk/screening knobs stay in ``config/policy_profiles.json``; this file is for
agent on/off switches, default portfolio sizing, and LLM hints (DeepSeek in production).
"""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PATH = _ROOT / "config" / "fortress_runtime.yaml"


# Paper-first default book size for screen/snipe/risk sizing (override via YAML or env).
_DEFAULT_PORTFOLIO_USD = 20_000.0


def _builtin_defaults() -> dict[str, Any]:
    return {
        "version": 1,
        "agents": {
            "daily_screen": {"enabled": True},
            "position_monitor": {"enabled": True},
            "intraday_sniper": {"enabled": True},
            "spy_intraday_swing": {"enabled": True, "default_equity_usd": int(_DEFAULT_PORTFOLIO_USD)},
            "fortress": {"enabled": True},
            "headline_event": {"enabled": True},
            "meta_architect": {"enabled": True},
        },
        "defaults": {
            "portfolio_value_usd": _DEFAULT_PORTFOLIO_USD,
            "allow_overnight_holds": True,
            "universe_expansion_d_plus": "us_equities_options",
        },
        "llm": {
            # Production: DeepSeek only. Ollama/Llama not used.
            "provider": "deepseek",
            "deepseek_base_url": "https://api.deepseek.com/v1",
            "deepseek_model": "deepseek-chat",
            "default_model": "deepseek-chat",
        },
    }


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for k, v in over.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def _config_path() -> Path:
    raw = (os.environ.get("FORTRESS_RUNTIME_CONFIG") or "").strip()
    return Path(raw) if raw else _DEFAULT_PATH


def load_runtime_config_raw() -> dict[str, Any]:
    """Return merged config (defaults + YAML file if readable)."""
    base = _builtin_defaults()
    path = _config_path()
    if not path.is_file():
        return base
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        if isinstance(loaded, dict):
            return _deep_merge(base, loaded)
    except Exception:
        pass
    return base


_cfg_cache: dict[str, Any] | None = None


def get_runtime_config(*, reload: bool = False) -> dict[str, Any]:
    """Cached merged runtime config."""
    global _cfg_cache
    if _cfg_cache is None or reload:
        _cfg_cache = load_runtime_config_raw()
    return _cfg_cache


def is_agent_enabled(agent_key: str) -> bool:
    cfg = get_runtime_config()
    block = (cfg.get("agents") or {}).get(agent_key)
    if not isinstance(block, dict):
        return True
    return bool(block.get("enabled", True))


def get_default_portfolio_usd() -> float:
    """CLI/cron default when no argv override: env FORTRESS_PORTFOLIO_VALUE / PORTFOLIO_VALUE, else YAML."""
    for key in ("FORTRESS_PORTFOLIO_VALUE", "PORTFOLIO_VALUE"):
        v = os.environ.get(key)
        if v and str(v).strip():
            try:
                return float(v.strip())
            except ValueError:
                pass
    cfg = get_runtime_config()
    d = cfg.get("defaults") or {}
    try:
        return float(d.get("portfolio_value_usd", _DEFAULT_PORTFOLIO_USD))
    except (TypeError, ValueError):
        return _DEFAULT_PORTFOLIO_USD


def get_spy_swing_default_equity_usd() -> float:
    cfg = get_runtime_config()
    ag = (cfg.get("agents") or {}).get("spy_intraday_swing") or {}
    try:
        return float(ag.get("default_equity_usd", get_default_portfolio_usd()))
    except (TypeError, ValueError):
        return get_default_portfolio_usd()


def get_llm_config() -> dict[str, Any]:
    cfg = get_runtime_config()
    block = cfg.get("llm")
    return block if isinstance(block, dict) else _builtin_defaults()["llm"]
