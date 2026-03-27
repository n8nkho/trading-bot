# Trading Bot System Blueprint

This document is a single-source blueprint for external review of the Fortress trading bot system: architecture, controls, runtime behavior, and improvement targets.

**Last updated:** 2026-03-27 (post LLM reasoning + DeepSeek token/cost telemetry tracking)

## 1) Executive Snapshot

- **Primary objective:** paper-first, rules-driven autonomous trading with hard risk/compliance gates.
- **Current default book size:** `$20,000` (`config/fortress_runtime.yaml` + `utils/runtime_config.py`).
- **Execution posture:** supports `autonomous` and `human_in_loop` (`utils/execution_mode.py`).
- **Operating model:** Oracle VM is production runner; local machine is editor/mirror.
- **Core promise:** bounded automation, not unconstrained AI execution.
- **Strategy posture:** multi-timeframe sleeves + sector/geographic overlays + CIO directive artifacts for operator review.

## 2) System Boundaries

- **Broker:** Alpaca (`paper-api.alpaca.markets` by default).
- **Data:** yfinance for market/news enrichment, local JSON/JSONL artifacts under `data/`.
- **Control plane:** Flask dashboard + APIs in `dashboard/command_center.py`.
- **Orchestrator:** `orchestrator.py` is the workflow entrypoint and CLI.
- **Policy layer:** `config/policy_profiles.json` (risk/screening/execution profile knobs).
- **Runtime layer:** `config/fortress_runtime.yaml` (agent toggles, defaults, llm hints).

## 3) Core Runtime Flows

### A) Daily Screening Flow (`orchestrator.py screen`)

1. `agents/screener_agent.py::run_screener()`
2. candidate enrichment (vision/news/fundamental paths)
3. `agents/entry_agent.py::evaluate_entry()`
4. risk checks (`agents/risk_guardian.py`)
5. pre-trade compliance (`utils/pre_trade_gate.py`)
6. execution or queue (`submit_approved_screening_trade()` / pending queue)
7. persist artifacts:
   - `data/daily_signals_YYYYMMDD.json`
   - `data/operational_runs.jsonl`
   - `data/trust_ledger.jsonl`

### B) Position Monitoring (`orchestrator.py monitor`)

- Calls `agents/exit_monitor.py::monitor_positions()`
- Generates and attempts exits
- Persists `data/exit_signals_YYYYMMDD.json`

### C) Intraday Sniper (`orchestrator.py snipe`)

- Calls `agents/intraday_sniper.py`
- Applies risk + pre-trade + execution mode controls
- Logs via `logs/sniper.log`

### D) SPY Swing (`orchestrator.py spy_swing`)

- Calls `agents/spy_intraday_swing.py`
- Shadow by default; optional execute path

### E) Fortress Hedge/Regime (`orchestrator.py fortress`)

- Calls `agents/fortress_orchestrator.py`
- Produces `data/fortress_report_*.json`
- Drives commodities/forex/theta/dividend/pairs/vix sleeve recommendations

### F) HITL Flush (`orchestrator.py execute_pending`)

- Reads `data/pending_execution_queue.json`
- Submits queued trades
- **Guard:** queue is preserved when market is closed (RTH check)

### G) Agentic Planning Artifacts (new orchestration commands)

- `orchestrator.py multi_timeframe` -> `data/multi_timeframe_plan_YYYYMMDD.json`
- `orchestrator.py sector_rotation` -> `data/sector_rotation_signal_YYYYMM.json`
- `orchestrator.py geographic_allocation` -> `data/geographic_allocation_plan_YYYYMMDD.json`
- `orchestrator.py scout_swarm` -> `data/scout_opportunity_queue_YYYYMMDD.json`
- `orchestrator.py analyst_ensemble` -> `data/analyst_consensus_YYYYMMDD.json`
- `orchestrator.py cio_cycle` -> `data/cio_directive_YYYYMMDD.json`

### H) Daily Intelligence Brief (`orchestrator.py generate_intelligence_brief`)

- Generates post-close self-QA + learning report artifacts:
  - `data/fortress_intelligence_brief_YYYYMMDD.json` (machine-readable)
  - `data/fortress_intelligence_brief_YYYYMMDD.md` (human-readable summary)
- Aggregates outcomes from PnL/decision logs plus agentic artifacts (CIO/scout/analyst/sector/geo).
- Runs rule-based self-diagnosis checks for:
  - unexecuted analyst BUY recommendations
  - scout conversion gaps
  - execution-layer and scheduler coverage gaps
- Produces forward-looking optimization queue and experiment suggestions.

### I) Recursive Self-Improvement Cycle (`orchestrator.py evolve`)

- Runs a 5-phase evolution loop and writes `data/recursive_evolution_YYYYMMDD_HHMMSS.json`:
  1. self-diagnosis from latest artifacts + blockers
  2. parameter auto-tuning proposal from realized outcomes
  3. strategy A/B allocation recommendation via Thompson sampling
  4. autonomous change plan (safe dry-run by default)
  5. meta-learning state update in `data/meta_learning_state.json`
- Writes operational telemetry to `logs/evolution.log`.
- Safety default: no automatic file changes unless `FORTRESS_EVOLUTION_ALLOW_WRITES=1`.
- Current operator setting (from `.env`): `FORTRESS_EVOLUTION_ALLOW_WRITES=1` (parameter auto-write path enabled).
  - Scope is intentionally limited to safe parameter patching (`data/current_params.json`).
  - `evolve` does not auto-commit or auto-deploy code changes.
- LLM pattern discovery extension:
  - when sufficient completed trades exist, `evolve` adds `llm_pattern_discovery` with discovered patterns + strategy proposal.

### J) LLM-First Reasoning Flow (`agents/llm_reasoning_engine.py`)

- Entry and stock-exit decisions are LLM-first when LLM provider is enabled.
- Entry prompt is **paper-trading aggressive**: judge the **current** setup; do not refuse buys because of unrelated past losses. Structured lessons from closed trades are injected via `utils/llm_learning_context.py` (from `data/llm_lessons.jsonl`).
- LLM response contract is strict JSON and persisted to `data/llm_reasoning_history.jsonl`.
- Decision trace for learning: `data/llm_decisions.jsonl` (links to `signal_id` after a BUY is logged; outcomes filled on full exit in `orchestrator.py` monitor path).
- Post-exit lesson extraction: `agents/llm_learning_agent.py` (uses configured `call_llm`; optional async thread via `FORTRESS_LLM_LEARNING_ON_EXIT`).
- Entry confidence floor default: `FORTRESS_LLM_ENTRY_MIN_CONFIDENCE` (default **0.55** for paper learning).
- Safety fallback remains active:
  - if provider is disabled/unavailable or response is malformed, deterministic fallback path executes.
- Provider routing:
  - `llm.provider=ollama|deepseek|none` in runtime config (`none` remains safest default).
- Cost/usage telemetry:
  - DeepSeek calls now log token usage and estimated USD cost into `data/api_costs.jsonl`.
  - Daily/monthly/lifetime summaries are available via `utils/cost_calculator.py`.
  - CLI usage report: `python3 scripts/report_llm_usage.py`.

## 4) Agent Inventory (High-Level)

- **Signal generation:** `screener_agent.py`, `intraday_sniper.py`, `spy_intraday_swing.py`
- **Entry/exit logic:** `entry_agent.py`, `exit_monitor.py`
- **Risk/compliance:** `risk_guardian.py`, `pre_trade_gate.py`, `operator_halt.py`
- **Regime/hedging:** `fortress_orchestrator.py`, strategy sleeves (`bond_manager.py`, `vix_insurance.py`, etc.)
- **Allocation/planning managers:** `day_trading_manager.py`, `swing_trading_manager.py`, `position_trading_manager.py`, `sector_rotation_manager.py`, `geographic_allocation_manager.py`
- **Agentic overlay:** `scouts/*`, `analysts/*`, `cio_agent.py`
- **Self-improvement/QA intelligence:** `intelligence_brief_generator.py`
- **Recursive evolution engine:** `recursive_evolution.py` (includes `llm_learning_review` batch step)
- **LLM reasoning agent:** `llm_reasoning_engine.py`
- **LLM learning loop:** `llm_learning_agent.py`, `utils/llm_decision_tracker.py`, `utils/llm_learning_context.py`
- **Audit/governance:** `bot_audit_agent.py`, `drift_detector.py`, `error_detective.py`
- **Adaptation/analysis:** `performance_analyzer.py`, `walk_forward_validator.py`, `meta_architect.py`

## 5) Risk, Safety, and Compliance Controls

- **Paper-first safety:** `ALPACA_BASE_URL` check (`paper` required unless live-ack provided).
- **Pre-trade gate:** notional/qty caps + halt checks (`utils/pre_trade_gate.py`).
- **Execution mode gate:** autonomous vs HITL (`utils/execution_mode.py`).
- **Circuit breaker / strict mode:** consecutive-loss based reductions/halts (`agents/risk_guardian.py`).
- **Risk state resilience:** stale persisted risk streak state auto-resets by default (configurable env window).
- **Policy profiles:** max positions, max position pct, total risk pct, daily/weekly loss limits (`config/policy_profiles.json`).
- **Operator halt:** file/API-driven kill switch (`utils/operator_halt.py` + dashboard endpoints).
- **Volatility-adaptive sizing:** counter-cyclical max position cap from latest VIX tier (`utils/volatility_adaptive_sizing.py` + risk_guardian integration).
- **Smart execution layer:** option order planning prefers limit orders when entry premium is known (`utils/smart_execution.py`).

## 6) Current Default Config Posture

- `config/fortress_runtime.yaml`
  - `defaults.portfolio_value_usd: 20000`
  - `agents.spy_intraday_swing.default_equity_usd: 20000`
  - `llm.provider: none`
- `config/policy_profiles.json`
  - active profile default: `opportunistic`
  - default risk profile includes `max_positions=6`, `max_position_size_pct=3.5`, `max_total_risk_pct=8.0`
- `.env.example`
  - paper API URL
  - optional `FORTRESS_PORTFOLIO_VALUE=20000`
  - entry window extension + RSI tuning knobs documented
  - execution mode and pre-trade gate control knobs documented

### Entry/Risk behavior defaults (as of current build)

- Entry stabilization default is permissive (`ENTRY_STABILIZATION_FACTOR` default `1.00` in code).
- Entry window end defaults to `16:00 ET` (via default extension path in `entry_agent`).
- Risk auto-reset defaults:
  - `FORTRESS_AUTO_RESET_RISK_GUARDIAN_STATE=1`
  - `FORTRESS_RISK_STATE_MAX_AGE_HOURS=24`
- Circuit-breaker persisted state file:
  - `data/risk_guardian_state.json` (authoritative)
  - note: `data/risk_state.json` is not used by `agents/risk_guardian.py`
- Manual reset command (paper-safe operational recovery):
  - `python3 -c "from agents.risk_guardian import reset_circuit_breaker; reset_circuit_breaker()"`

## 7) Operational Architecture

- **Scheduler:** cron (user crontab) runs `screen`, `monitor`, `snipe`, `fortress`, `execute_pending`, `generate_intelligence_brief`, and `evolve` (post-close).
- **Logs:** `logs/screener.log`, `logs/monitor.log`, `logs/sniper.log`, `logs/fortress.log`, etc.
- **Dashboard:** systemd service for command center (`deploy/systemd/` docs/templates).
- **State files:** all under repo `data/`.
- **Source of truth:** Oracle VM runtime + cron; Mac is code mirror (Oracle -> Mac sync script).

## 8) Command Center Coverage (Current)

- Command Center now surfaces:
  - screening funnel + top skip reasons
  - live safety status (halt, circuit state, strict mode, risk streak, auto-reset window)
  - hedging context + strategy gate metrics
  - agentic artifact summary (CIO directive, scout queue, analyst consensus, multi-timeframe, sector rotation, geo allocation)
  - fortress intelligence brief panel (latest report status, executive summary, critical blockers, markdown preview)
  - recursive evolution status panel (latest evolution artifact, win-rate context, bandit allocations, apply-mode, meta-learning trend, evolution log tail)
  - LLM usage and spend panel (today/7d/lifetime calls + tokens + estimated USD, model breakdown, recent metered calls)
  - expanded runbooks including new agentic commands
- Remaining caveat:
  - data shown is artifact-driven; absence usually means command/cadence not run yet, not necessarily failure.

### Verification Snapshot (2026-03-27)

- **Broker smoke:** `python3 smoke_alpaca_paper_trade_cancel.py` passed (`AAPL` limit order submitted and canceled on Alpaca paper).
- **Executor dry safety check:** forced sector/geographic executor commands ran with trading halt enabled and were blocked by pre-trade gate as expected:
  - `pre_trade_gate: global_trading_halt` for `XLK/XLF/XLV` and `EFA/EEM/EWJ/VGK`
  - execution logs written to:
    - `data/sector_execution_log.jsonl`
    - `data/geographic_execution_log.jsonl`
- **Test suite status:** all current integration/unit tests green after agentic execution wiring.
- **Daily intelligence brief generation:** command succeeds locally and on Oracle VM:
  - `python3 orchestrator.py generate_intelligence_brief`
  - output files confirmed in `data/` with current date stamp.
- **Dashboard/API wiring:** `/api/intelligence_brief` returns latest report payload and Command Center panel renders summary + blockers.
- **Cron scheduling:** weekday 17:00 ET intelligence job installed on Oracle user crontab.
- **Circuit-breaker readiness validation:** local + Oracle runtime verified with:
  - pre-reset diagnosis: stale tripped state found in `data/risk_guardian_state.json`
  - post-reset status: `consecutive_losses=0`, `circuit_breaker_active=False`
  - end-to-end smoke chain (`scout_swarm -> analyst_ensemble -> cio_cycle -> screen -> execute_pending -> monitor -> generate_intelligence_brief`) completed successfully.

## 9) Known Improvement Opportunities (for External Review)

1. **Unified logging consistency:** some modules log to their own files while orchestrator logging may differ.
2. **Order-type intelligence:** stock/option execution strategy can be refined by session type (market/limit by liquidity/time).
3. **Calendar robustness:** explicit holiday/half-day handling beyond baseline checks.
4. **Schema hardening:** add stricter pydantic/dataclass validation for cross-agent payloads.
5. **Backtest/forward-test coupling:** standardize objective metrics from research artifacts into gating thresholds.
6. **Alerting:** strengthen incident alerts for stale core logs, queue age, and repeated broker rejects.
7. **Dependency isolation:** graceful fallback paths for optional providers (LLM/news endpoints).

## 10) External Review Checklist

Ask reviewers to evaluate:

- **Architecture**
  - Is separation of runtime config vs policy config clean?
  - Are agent responsibilities modular and testable?
- **Risk**
  - Are max exposure and position caps coherent at `$20k` default?
  - Are strict-mode and circuit-breaker transitions safe?
- **Execution**
  - Are autonomous submissions appropriately bounded?
  - Are after-hours and option constraints correctly handled?
- **Reliability**
  - Can cron/systemd fail silently? Are there watchdogs/alerts?
  - Are logs and artifacts sufficient for root-cause diagnosis?
- **Governance**
  - Is audit output actionable and faithful to runtime reality?
  - Are trust ledger / run registry records sufficient for postmortems?
- **Security/ops**
  - Secret handling, env hygiene, endpoint hardening, dashboard auth.

## 11) File Map (Critical References)

- `orchestrator.py` — main workflows and CLI
- `agents/screener_agent.py` — candidate generation
- `agents/entry_agent.py` — entry/option/stock gating
- `agents/exit_monitor.py` — exit decisions
- `agents/risk_guardian.py` — risk limits and circuit breaker
- `utils/volatility_adaptive_sizing.py` — VIX-tiered adaptive risk cap
- `utils/smart_execution.py` — order-type planning helper
- `agents/bot_audit_agent.py` — objective audit and diagnostics
- `agents/intelligence_brief_generator.py` — daily self-QA/learning brief generation
- `agents/recursive_evolution.py` — 5-phase recursive improvement cycle
- `agents/llm_reasoning_engine.py` — LLM-first entry/exit reasoning + pattern discovery
- `utils/pre_trade_gate.py` — final broker submission controls
- `utils/runtime_config.py` — runtime defaults and toggles
- `utils/policy_profile.py` + `config/policy_profiles.json` — policy layer
- `utils/pending_execution_queue.py` — HITL queue
- `dashboard/command_center.py` — operator APIs/UI
- `agents/scouts/` + `agents/analysts/` + `agents/cio_agent.py` — agentic overlay
- `agents/sector_rotation_manager.py` + `agents/geographic_allocation_manager.py` — allocation extensions
- `config/fortress_runtime.yaml` — runtime declarative config
- `.env.example` — operator environment template

## 12) Reviewer Notes

- This system is intentionally deterministic-first with optional LLM advisory paths.
- “Winning strategy” should be judged as **process quality + bounded risk + repeatability**, not guaranteed returns.
- External recommendations should preserve safety invariants: pre-trade gate, execution mode, policy guardrails, and paper-first defaults unless explicitly changed.

## 13) Pre-Open Readiness Runbook (Operator Quick Check)

Run this before RTH if there is any concern about stale state or overnight drift:

1. `python3 -c "from agents.risk_guardian import get_risk_status; print(get_risk_status())"`
2. Verify `circuit_breaker_active` is `False` and `consecutive_losses` is expected.
3. `python3 orchestrator.py scout_swarm && python3 orchestrator.py analyst_ensemble && python3 orchestrator.py cio_cycle`
4. `python3 orchestrator.py generate_intelligence_brief`
5. Confirm Command Center shows current brief and no unexpected critical blockers.
