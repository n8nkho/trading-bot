from __future__ import annotations

"""
Core data schemas for Fortress Trading Bot.

These dataclasses formalize the shapes that were previously loose dicts
for candidates, decisions, positions, outcomes, recommendations, and regimes.

They are designed to be:
- Backwards compatible with existing JSON structures
- Lightweight (no runtime dependency on Pydantic for now)
- Usable in both runtime code and tests/backtests
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Candidate:
    ticker: str
    drop_pct: Optional[float] = None
    rsi: Optional[float] = None
    volume_ratio: Optional[float] = None
    current_price: Optional[float] = None
    regime: Optional[str] = None
    confidence: Optional[float] = None
    source: Optional[str] = None  # e.g. screener, pead, vol_compression
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Candidate":
        return cls(
            ticker=str(data.get("ticker", "")),
            drop_pct=_to_float_or_none(data.get("drop_pct")),
            rsi=_to_float_or_none(data.get("rsi")),
            volume_ratio=_to_float_or_none(data.get("volume_ratio")),
            current_price=_to_float_or_none(data.get("current_price")),
            regime=data.get("regime"),
            confidence=_to_float_or_none(data.get("confidence")),
            source=data.get("source"),
            meta={k: v for k, v in data.items() if k not in {
                "ticker", "drop_pct", "rsi", "volume_ratio",
                "current_price", "regime", "confidence", "source",
            }},
        )

    def to_dict(self) -> Dict[str, Any]:
        base = {
            "ticker": self.ticker,
            "drop_pct": self.drop_pct,
            "rsi": self.rsi,
            "volume_ratio": self.volume_ratio,
            "current_price": self.current_price,
            "regime": self.regime,
            "confidence": self.confidence,
            "source": self.source,
        }
        base.update(self.meta)
        return base


@dataclass
class Position:
    ticker: str
    shares: float
    entry_price: float
    entry_date: str
    side: str = "long"
    order_id: Optional[str] = None
    sector: Optional[str] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    auto_executed: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Position":
        shares = data.get("shares", data.get("qty", 0))
        entry_date = data.get("entry_date") or data.get("entry_time") or ""
        return cls(
            ticker=str(data.get("ticker", "")),
            shares=float(shares or 0),
            entry_price=float(data.get("entry_price", 0.0)),
            entry_date=str(entry_date),
            side=str(data.get("side", "long")),
            order_id=data.get("order_id"),
            sector=data.get("sector"),
            stop_loss_pct=_to_float_or_none(data.get("stop_loss_pct")),
            take_profit_pct=_to_float_or_none(data.get("take_profit_pct")),
            auto_executed=bool(data.get("auto_executed", False)),
            meta={k: v for k, v in data.items() if k not in {
                "ticker", "shares", "qty", "entry_price", "entry_date",
                "entry_time", "side", "order_id", "sector",
                "stop_loss_pct", "take_profit_pct", "auto_executed",
            }},
        )

    def to_dict(self) -> Dict[str, Any]:
        base = {
            "ticker": self.ticker,
            "shares": self.shares,
            "entry_price": self.entry_price,
            "entry_date": self.entry_date,
            "side": self.side,
            "order_id": self.order_id,
            "sector": self.sector,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "auto_executed": self.auto_executed,
        }
        base.update(self.meta)
        return base


@dataclass
class Decision:
    ticker: str
    action: str  # BUY / SELL / HOLD / SKIP
    reason: str
    confidence: Optional[float] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    source_strategy: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        base = {
            "ticker": self.ticker,
            "action": self.action,
            "reason": self.reason,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "source_strategy": self.source_strategy,
        }
        base.update(self.meta)
        return base


@dataclass
class OutcomeRecord:
    ticker: str
    signal_date: str
    drop_pct: Optional[float]
    rsi: Optional[float]
    volume_ratio: Optional[float]
    regime: str
    outcome: str  # safe_win / stop_hit / open
    outcome_pct: Optional[float]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutcomeRecord":
        return cls(
            ticker=str(data.get("ticker", "")),
            signal_date=str(data.get("signal_date", "")),
            drop_pct=_to_float_or_none(data.get("drop_pct")),
            rsi=_to_float_or_none(data.get("rsi")),
            volume_ratio=_to_float_or_none(data.get("volume_ratio")),
            regime=str(data.get("regime", "")),
            outcome=str(data.get("outcome", "")),
            outcome_pct=_to_float_or_none(data.get("outcome_pct")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "signal_date": self.signal_date,
            "drop_pct": self.drop_pct,
            "rsi": self.rsi,
            "volume_ratio": self.volume_ratio,
            "regime": self.regime,
            "outcome": self.outcome,
            "outcome_pct": self.outcome_pct,
        }


@dataclass
class Recommendation:
    title: str
    body: str
    action: str
    severity: str = "low"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "body": self.body,
            "action": self.action,
            "severity": self.severity,
        }


@dataclass
class RegimeRecord:
    regime: str
    vix: Optional[float] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "vix": self.vix,
            "timestamp": self.timestamp,
        }


def _to_float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

