# Missing Guardrails - Phased Ticket Stack

This stack implements the 10 proposed guardrails in deployment-safe phases.

## Phase 1 - Pre-live hard protections

- [x] GR-01 Drawdown circuit breaker scaffold in `risk_guardian` with runtime equity tracking and optional enforcement (`FORTRESS_DRAWDOWN_GUARD_ENFORCE`).
- [x] GR-02 Sector concentration hard cap made configurable (`FORTRESS_MAX_SECTOR_CONCENTRATION_PCT`) and optional correlation cap (`FORTRESS_ENABLE_CORRELATION_GUARD`).
- [x] GR-03 LLM hallucination checks on BUY intents (ticker/reasoning sanity + optional tradability check).
- [x] GR-08 Pre-trade data-quality checks (symbol format, notional sanity, quote spread/age hooks) with enforce flag (`FORTRESS_DATA_QUALITY_ENFORCE`).

## Phase 2 - Runtime stability controls

- [x] GR-04 Flash crash and rapid-velocity guardrails via runtime equity velocity checks and optional enforce-to-halt mode (`FORTRESS_VELOCITY_GUARD_ENFORCE`).
- [x] GR-05 Velocity/momentum limiter wired into risk status and pre-entry risk path.
- [x] GR-06 Short squeeze protection for short positions in `exit_monitor` (`FORTRESS_SHORT_SQUEEZE_GUARD`).
- [x] GR-07 Position aging limits split by side (`FORTRESS_POSITION_AGING_GUARD`, `FORTRESS_MAX_HOLD_DAYS_LONG`, `FORTRESS_MAX_HOLD_DAYS_SHORT`).

## Phase 3 - Evolution and event safety

- [x] GR-09 Recursive evolution safeguards: max one-step parameter delta and approval queue (`FORTRESS_EVOLUTION_REQUIRE_APPROVAL`, `FORTRESS_EVOLUTION_MAX_PARAM_DELTA_PCT`).
- [x] GR-10 News/event blackout windows via configurable ET windows in pre-trade gate (`FORTRESS_ENTRY_BLACKOUT_WINDOWS_ET`).

## Rollout Playbook

1. Run in observe-only for 3-5 sessions (`*_ENFORCE=0`).
2. Review `risk_status.runtime_guardrail_*` and pre-trade gate issues.
3. Enable enforcement in paper trading for 2 sessions.
4. Enable limited live only after go-live scorecard passes.
