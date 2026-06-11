"""
Central pre-submit gate for broker orders — compliance-style hard blocks.
All paths that submit orders should call evaluate_pre_trade_submission() first.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from utils.operator_halt import is_trading_halted
from utils.tunable_overrides import get_position_size_pct


_EQUITY_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_OCC_OPTION_SYMBOL_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


def _is_valid_symbol(symbol: str, order_class: str) -> bool:
    sym = (symbol or "").strip().upper()
    cls = (order_class or "").strip().lower()
    if cls == "option":
        # OCC-form option symbols, e.g. ET260605C00020000
        return bool(_OCC_OPTION_SYMBOL_RE.match(sym))
    return bool(_EQUITY_SYMBOL_RE.match(sym))


def _is_in_blackout_window_et() -> tuple[bool, str]:
    """
    Returns (in_blackout, window_label). Format:
    FORTRESS_ENTRY_BLACKOUT_WINDOWS_ET="08:25-08:40,09:28-09:40,13:55-14:10"
    """
    raw = str(os.getenv("FORTRESS_ENTRY_BLACKOUT_WINDOWS_ET", "") or "").strip()
    if not raw:
        return False, ""
    now = datetime.now(ZoneInfo("America/New_York"))
    cur = now.hour * 60 + now.minute
    for block in [x.strip() for x in raw.split(",") if x.strip()]:
        try:
            left, right = block.split("-", 1)
            sh, sm = [int(v) for v in left.split(":")]
            eh, em = [int(v) for v in right.split(":")]
            smin = sh * 60 + sm
            emin = eh * 60 + em
            if smin <= cur <= emin:
                return True, block
        except Exception:
            continue
    return False, ""


def evaluate_pre_trade_submission(
    *,
    side: str,
    symbol: str,
    qty: float,
    estimated_notional_usd: float | None = None,
    portfolio_equity_usd: float | None = None,
    order_class: str = "equity",
    bid: float | None = None,
    ask: float | None = None,
    quote_age_seconds: float | None = None,
) -> dict[str, Any]:
    """
    Returns {"allowed": bool, "reasons": [str, ...]}.
    """
    reasons: list[str] = []

    if is_trading_halted():
        reasons.append("global_trading_halt")

    base = (os.getenv("ALPACA_BASE_URL") or "").lower()
    live_ack = (os.getenv("FORTRESS_LIVE_TRADING_ACK") or "").strip()
    if base and "paper" not in base and live_ack != "I_ACCEPT_LIVE_RISK":
        reasons.append("non_paper_endpoint_without_live_ack")

    try:
        max_notional = float(os.environ.get("FORTRESS_MAX_ORDER_NOTIONAL_USD", "25000"))
    except ValueError:
        max_notional = 25000.0

    position_pct_cap: float | None = None
    if (
        (side or "").strip().upper() == "BUY"
        and portfolio_equity_usd is not None
        and float(portfolio_equity_usd) > 0
    ):
        try:
            position_pct_cap = float(portfolio_equity_usd) * float(get_position_size_pct())
        except (TypeError, ValueError):
            position_pct_cap = None
        if position_pct_cap is not None and position_pct_cap > 0:
            max_notional = min(max_notional, position_pct_cap)

    if estimated_notional_usd is not None and estimated_notional_usd > max_notional:
        reasons.append(f"estimated_notional_exceeds_cap:{max_notional}")

    try:
        max_qty = float(os.environ.get("FORTRESS_MAX_ORDER_QTY", "5000"))
    except ValueError:
        max_qty = 5000.0
    if qty and abs(float(qty)) > max_qty:
        reasons.append(f"qty_exceeds_cap:{max_qty}")

    sym = (symbol or "").strip().upper()
    if not sym:
        reasons.append("missing_symbol")
    elif not _is_valid_symbol(sym, order_class):
        reasons.append("invalid_symbol_format")

    sd = (side or "").strip().upper()
    if sd not in ("BUY", "SELL"):
        reasons.append("invalid_side")
    if sd == "BUY":
        in_blackout, window = _is_in_blackout_window_et()
        if in_blackout:
            reasons.append(f"event_blackout_window:{window}")

    # Phase 2 data-quality controls: observe-by-default, enforce by env.
    dq_enforce = str(os.getenv("FORTRESS_DATA_QUALITY_ENFORCE", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    dq_issues: list[str] = []
    if estimated_notional_usd is not None and float(estimated_notional_usd) <= 0:
        dq_issues.append("non_positive_notional")
    if bid is not None and ask is not None:
        try:
            b = float(bid)
            a = float(ask)
            if b <= 0 or a <= 0 or a < b:
                dq_issues.append("invalid_quote_sides")
            else:
                spread = (a - b) / b
                max_spread = float(os.getenv("FORTRESS_MAX_SPREAD_PCT", "0.03"))
                if spread > max_spread:
                    dq_issues.append(f"spread_too_wide:{spread:.4f}>{max_spread}")
        except Exception:
            dq_issues.append("quote_parse_error")
    if quote_age_seconds is not None:
        try:
            age = float(quote_age_seconds)
            max_age = float(os.getenv("FORTRESS_MAX_QUOTE_AGE_SECONDS", "90"))
            if age > max_age:
                dq_issues.append(f"stale_quote:{age:.1f}s>{max_age:.1f}s")
        except Exception:
            dq_issues.append("quote_age_parse_error")

    if dq_issues and dq_enforce:
        reasons.extend([f"data_quality:{i}" for i in dq_issues])

    signal_adjustments: dict[str, Any] = {
        "sentiment_confidence_multiplier": 1.0,
    }
    try:
        from utils.regime_freshness import sentiment_pipeline_meta

        sm = sentiment_pipeline_meta()
        signal_adjustments["sentiment_confidence_multiplier"] = float(sm.get("confidence_multiplier") or 1.0)
        signal_adjustments["sentiment_pipeline"] = sm
    except Exception:
        pass

    if sd == "BUY":
        try:
            from utils.runtime_safety import hedging_error_blocks_entries

            hb, why = hedging_error_blocks_entries()
            if hb:
                reasons.append(f"hedging_execution_error:{why}")
        except Exception:
            pass

        regime_block = str(os.getenv("FORTRESS_REGIME_STALE_BLOCK_RTH", "1")).strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        if regime_block:
            try:
                from utils.regime_freshness import refresh_regime_if_stale_rth, regime_is_stale_for_rth

                refresh_regime_if_stale_rth()
                stale, why = regime_is_stale_for_rth()
                if stale:
                    reasons.append(f"regime_stale_rth:{why}")
            except Exception:
                pass

    return {
        "allowed": len(reasons) == 0,
        "reasons": reasons,
        "data_quality_issues": dq_issues,
        "order_class": order_class,
        "symbol": sym,
        "side": sd,
        "qty": qty,
        "signal_adjustments": signal_adjustments,
    }


def format_gate_block_message(gate: dict[str, Any]) -> str:
    return "pre_trade_gate: " + ",".join(gate.get("reasons") or [])
