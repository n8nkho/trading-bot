"""
Provider safety and simple circuit breakers for external data sources.

This module centralizes lightweight, in-memory circuit breakers for
external APIs such as yfinance, Grok, and OpenAI. It is intentionally
conservative:

- Fails CLOSED for non-critical analytics (e.g., pattern mining) by
  returning None instead of raising.
- Never alters core trading paths directly; existing callers should
  continue to handle None / empty data as "no signal".
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """
    Minimal in-memory circuit breaker.

    Designed for single-process use. Safe defaults:
    - Opens after `failure_threshold` consecutive failures.
    - Remains open for `cooldown_seconds`, during which calls are skipped.
    - After cooldown, allows a single "probe" call; success closes the breaker.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_seconds: int = 300,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures = 0
        self._opened_at: Optional[float] = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if (time.time() - self._opened_at) >= self.cooldown_seconds:
            # Cooldown expired; half-open state (allow next call)
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold and self._opened_at is None:
            self._opened_at = time.time()
            logger.warning(
                "Circuit '%s' opened after %d failures; cooldown=%ss",
                self.name,
                self._failures,
                self.cooldown_seconds,
            )


_breakers: Dict[str, CircuitBreaker] = {
    "yfinance": CircuitBreaker("yfinance", failure_threshold=5, cooldown_seconds=600),
    "grok": CircuitBreaker("grok", failure_threshold=3, cooldown_seconds=300),
    "openai": CircuitBreaker("openai", failure_threshold=3, cooldown_seconds=300),
}


def get_breaker(name: str) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name)
    return _breakers[name]


def guarded_call(name: str, fn: Callable[[], Any]) -> Any:
    """
    Execute `fn` under circuit breaker `name`.

    Returns None immediately when circuit is open. Callers should treat
    None as "data unavailable" and degrade gracefully (no trades).
    """
    br = get_breaker(name)
    if br.is_open:
        logger.warning("Circuit '%s' open; skipping external call", name)
        return None
    try:
        result = fn()
        br.record_success()
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("Circuit '%s' failure: %s", name, exc)
        br.record_failure()
        return None


