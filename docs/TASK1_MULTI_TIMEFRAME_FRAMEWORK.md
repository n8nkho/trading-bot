# Task 1: Multi-Timeframe Strategy Framework

This document describes the implementation and integration of the three-sleeve framework:

- `day_trading` (30%)
- `swing_trading` (40%)
- `position_trading` (30%)

## Architecture

### New components

- `config/strategy_allocation.yaml`
  - Sleeve capital allocations
  - Holding-period descriptors
  - Per-sleeve risk blocks
  - Regime/VIX activation gates
- `utils/strategy_allocation.py`
  - Pydantic config models
  - Validation that sleeve allocation totals 100%
- `agents/day_trading_manager.py`
- `agents/swing_trading_manager.py`
- `agents/position_trading_manager.py`
  - Independent sleeve selection logic
  - Independent performance tracking JSONL files

### Orchestrator integration

- New CLI command:
  - `python orchestrator.py multi_timeframe [portfolio_value]`
- Output artifact:
  - `data/multi_timeframe_plan_YYYYMMDD.json`
- Per-sleeve metric logs:
  - `data/sleeve_metrics_day_trading.jsonl`
  - `data/sleeve_metrics_swing_trading.jsonl`
  - `data/sleeve_metrics_position_trading.jsonl`

## Design decisions and trade-offs

1. **Deterministic-first sleeve selection**
   - Uses existing screener candidates and deterministic thresholds.
   - Trade-off: less expressive than full LLM policy selection, but robust and auditable.
2. **Pydantic configuration validation**
   - Fails fast if allocations drift from 100%.
   - Trade-off: stricter config rules can block startup on malformed config (intentional).
3. **Non-breaking integration**
   - New command added without changing existing `screen/monitor/snipe` behavior.
   - Trade-off: framework is initially planner-mode; execution coupling is phase-2 work.

## Test coverage

- `tests/test_strategy_allocation_framework.py`
  - Verifies config integrity
  - Verifies manager outputs are structurally correct
- Existing suite remains green.

## Expected impact

- Immediate: a formal sleeve plan and telemetry framework for day/swing/position.
- Near-term: cleaner basis for increasing throughput by assigning candidates to sleeves instead of one-size entry logic.
- Next step: wire sleeve outputs into execution/risk budgets in `screen` and/or dedicated sleeve runners.

