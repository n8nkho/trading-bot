#!/usr/bin/env python3
"""
Fail-fast import gate for production deployments.

Goal: catch import-time crashes caused by:
- optional dependencies missing (e.g., oandapyV20)
- missing credentials at import time (Alpaca / Anthropic / etc)

This script should be safe to run repeatedly and does not execute trades.
"""

from __future__ import annotations

import os
import sys
import traceback


def _set_default_env() -> None:
    # Prevent import-time credential validation failures.
    os.environ.setdefault("APCA_API_KEY_ID", "DUMMY")
    os.environ.setdefault("APCA_API_SECRET_KEY", "DUMMY")

    # Prevent import-time OANDA client setup failures (where applicable).
    os.environ.setdefault("OANDA_API_KEY", "DUMMY")
    os.environ.setdefault("OANDA_ACCOUNT_ID", "DUMMY")

    # Prevent "disabled analysis" branches from turning into noisy crashes.
    os.environ.setdefault("ANTHROPIC_API_KEY", "DUMMY")
    os.environ.setdefault("OPENAI_API_KEY", "DUMMY")


def _try_import(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except Exception:
        print(f"[FAIL] import {module_name}")
        traceback.print_exc()
        return False


def main() -> int:
    _set_default_env()

    # Modules that are critical for orchestrator/hedging workflows.
    modules = [
        # Common web dependencies used by dashboards
        "flask_cors",
        "orchestrator",
        "utils.policy_guardrails",
        "agents.walk_forward_validator",
        "agents.drift_detector",
        "utils.run_registry",
        "utils.market_calendar",
        "utils.pre_trade_gate",
        "utils.operator_halt",
        "utils.alerts",
        "utils.simple_daily_backtest",
        "utils.operator_morning_brief",
        "utils.tradingview_webhook",
        "utils.execution_mode",
        "utils.runtime_config",
        "utils.pending_execution_queue",
        "utils.alpaca_env",
        "utils.alpaca_broker",
        # Core trading workflow modules
        "agents.screener_agent",
        "agents.entry_agent",
        "agents.exit_monitor",
        "agents.risk_guardian",
        "agents.performance_analyzer",
        "agents.intraday_sniper",
        "agents.spy_intraday_swing",
        "agents.critique_loop",
        "agents.reflection_agent",
        "agents.briefing_agent",
        "agents.backtest_agent",
        "agents.sentiment_velocity_agent",
        "agents.earnings_intel_agent",
        "agents.regime_detector",
        "agents.options_flow_agent",
        "agents.prompt_evolution_agent",
        "agents.cross_asset_agent",
        "utils.atomic_json",
        "utils.llm_router",
        "utils.fortress_logger",
        "utils.trade_history",
        "agents.bot_audit_agent",
        # Fortress / hedging chain
        "agents.fortress_orchestrator",
        "agents.commodity_trader",
        "agents.bond_manager",
        "agents.vix_insurance",
        "agents.forex_hedger",
        "agents.theta_spreads",
        "agents.dividend_capture",
        "agents.pairs_trader",
        "agents.headline_event_agent",
    ]

    ok = True
    for m in modules:
        if not _try_import(m):
            ok = False

    if ok:
        print("[OK] import gate passed")
        return 0

    print("[ERROR] import gate failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

