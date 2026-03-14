"""
Add-on loader: customers extend the bot only through this API.

Core code must not be modified. Add-ons live in customer_addons/ and implement
optional hooks. This module discovers and invokes them. Only this file imports
from customer_addons/; all other code stays unchanged.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ADDONS_DIR = PROJECT_ROOT / "customer_addons"

logger = logging.getLogger(__name__)

# Hook name -> list of callables (add-on functions)
_hooks: Dict[str, List[Callable[..., Any]]] = {}


def _discover_addons() -> None:
    if not ADDONS_DIR.exists():
        return
    for path in sorted(ADDONS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"customer_addons.{path.stem}", path
            )
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "register"):
                env = _AddonEnv()
                mod.register(env)
        except Exception as e:
            logger.warning("Add-on %s failed to load: %s", path.name, e)


class _AddonEnv:
    """
    Environment passed to add-on register(env). Add-ons call env.on_* to subscribe.
    """

    def on_screen_done(self, fn: Callable[..., Any]) -> None:
        """Called after daily screening with candidates list. Signature: (candidates: list) -> None."""
        _hooks.setdefault("on_screen_done", []).append(fn)

    def on_before_trade(self, fn: Callable[..., Any]) -> None:
        """Called before a trade is submitted. Signature: (decision: dict) -> dict | None. Return modified decision or None to allow as-is."""
        _hooks.setdefault("on_before_trade", []).append(fn)

    def on_after_trade(self, fn: Callable[..., Any]) -> None:
        """Called after a trade is logged. Signature: (decision: dict, outcome: str) -> None."""
        _hooks.setdefault("on_after_trade", []).append(fn)


def invoke(hook_name: str, **kwargs: Any) -> Any:
    """
    Invoke all add-ons registered for hook_name. kwargs passed to each callable.
    For on_before_trade, if any callable returns a dict, that becomes the decision
    for the next callable; if one returns None, original is used. Final return
    is the last non-None decision or the original kwargs.get("decision").
    """
    if not _hooks:
        _discover_addons()
    callables = _hooks.get(hook_name, [])
    result = kwargs.get("decision")
    for fn in callables:
        try:
            out = fn(**kwargs)
            if hook_name == "on_before_trade" and out is not None and isinstance(out, dict):
                result = out
                kwargs["decision"] = out
        except Exception as e:
            logger.warning("Add-on hook %s failed: %s", hook_name, e)
    return result


def invoke_screen_done(candidates: list) -> None:
    """Call after screening. Add-ons cannot change candidates; they can log or notify."""
    invoke("on_screen_done", candidates=candidates)


def invoke_before_trade(decision: dict) -> dict:
    """Call before submitting trade. Add-ons can return modified decision (within bounds)."""
    out = invoke("on_before_trade", decision=decision)
    return out if isinstance(out, dict) else decision


def invoke_after_trade(decision: dict, outcome: str) -> None:
    invoke("on_after_trade", decision=decision, outcome=outcome)
