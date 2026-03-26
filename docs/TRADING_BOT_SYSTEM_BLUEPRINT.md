# Trading Bot System Blueprint

This document is a single-source blueprint for external review of the Fortress trading bot system: architecture, controls, runtime behavior, and improvement targets.

## 1) Executive Snapshot

- **Primary objective:** paper-first, rules-driven autonomous trading with hard risk/compliance gates.
- **Current default book size:** `$20,000` (`config/fortress_runtime.yaml` + `utils/runtime_config.py`).
- **Execution posture:** supports `autonomous` and `human_in_loop` (`utils/execution_mode.py`).
- **Operating model:** Oracle VM is production runner; local machine is editor/mirror.
- **Core promise:** bounded automation, not unconstrained AI execution.

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

### F) HITL Flush (`orchestrator.py execute_pending`)

- Reads `data/pending_execution_queue.json`
- Submits queued trades
- **Guard:** queue is preserved when market is closed (RTH check)

## 4) Agent Inventory (High-Level)

- **Signal generation:** `screener_agent.py`, `intraday_sniper.py`, `spy_intraday_swing.py`
- **Entry/exit logic:** `entry_agent.py`, `exit_monitor.py`
- **Risk/compliance:** `risk_guardian.py`, `pre_trade_gate.py`, `operator_halt.py`
- **Regime/hedging:** `fortress_orchestrator.py`, strategy sleeves (`bond_manager.py`, `vix_insurance.py`, etc.)
- **Audit/governance:** `bot_audit_agent.py`, `drift_detector.py`, `error_detective.py`
- **Adaptation/analysis:** `performance_analyzer.py`, `walk_forward_validator.py`, `meta_architect.py`

## 5) Risk, Safety, and Compliance Controls

- **Paper-first safety:** `ALPACA_BASE_URL` check (`paper` required unless live-ack provided).
- **Pre-trade gate:** notional/qty caps + halt checks (`utils/pre_trade_gate.py`).
- **Execution mode gate:** autonomous vs HITL (`utils/execution_mode.py`).
- **Circuit breaker / strict mode:** consecutive-loss based reductions/halts (`agents/risk_guardian.py`).
- **Policy profiles:** max positions, max position pct, total risk pct, daily/weekly loss limits (`config/policy_profiles.json`).
- **Operator halt:** file/API-driven kill switch (`utils/operator_halt.py` + dashboard endpoints).

## 6) Current Default Config Posture

- `config/fortress_runtime.yaml`
  - `defaults.portfolio_value_usd: 20000`
  - `agents.spy_intraday_swing.default_equity_usd: 20000`
  - `llm.provider: none`
- `config/policy_profiles.json`
  - active profile default: `balanced`
  - risk profile includes `max_positions=5`, `max_position_size_pct=3.0`, `max_total_risk_pct=7.0`
- `.env.example`
  - paper API URL
  - optional `FORTRESS_PORTFOLIO_VALUE=20000`

## 7) Operational Architecture

- **Scheduler:** cron (user crontab) runs `screen`, `monitor`, `snipe`, `fortress`, `execute_pending`.
- **Logs:** `logs/screener.log`, `logs/monitor.log`, `logs/sniper.log`, `logs/fortress.log`, etc.
- **Dashboard:** systemd service for command center (`deploy/systemd/` docs/templates).
- **State files:** all under repo `data/`.

## 8) Known Improvement Opportunities (for External Review)

1. **Unified logging consistency:** some modules log to their own files while orchestrator logging may differ.
2. **Order-type intelligence:** stock/option execution strategy can be refined by session type (market/limit by liquidity/time).
3. **Calendar robustness:** explicit holiday/half-day handling beyond baseline checks.
4. **Schema hardening:** add stricter pydantic/dataclass validation for cross-agent payloads.
5. **Backtest/forward-test coupling:** standardize objective metrics from research artifacts into gating thresholds.
6. **Alerting:** strengthen incident alerts for stale core logs, queue age, and repeated broker rejects.
7. **Dependency isolation:** graceful fallback paths for optional providers (LLM/news endpoints).

## 9) External Review Checklist

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

## 10) File Map (Critical References)

- `orchestrator.py` — main workflows and CLI
- `agents/screener_agent.py` — candidate generation
- `agents/entry_agent.py` — entry/option/stock gating
- `agents/exit_monitor.py` — exit decisions
- `agents/risk_guardian.py` — risk limits and circuit breaker
- `agents/bot_audit_agent.py` — objective audit and diagnostics
- `utils/pre_trade_gate.py` — final broker submission controls
- `utils/runtime_config.py` — runtime defaults and toggles
- `utils/policy_profile.py` + `config/policy_profiles.json` — policy layer
- `utils/pending_execution_queue.py` — HITL queue
- `dashboard/command_center.py` — operator APIs/UI
- `config/fortress_runtime.yaml` — runtime declarative config
- `.env.example` — operator environment template

## 11) Reviewer Notes

- This system is intentionally deterministic-first with optional LLM advisory paths.
- “Winning strategy” should be judged as **process quality + bounded risk + repeatability**, not guaranteed returns.
- External recommendations should preserve safety invariants: pre-trade gate, execution mode, policy guardrails, and paper-first defaults unless explicitly changed.
