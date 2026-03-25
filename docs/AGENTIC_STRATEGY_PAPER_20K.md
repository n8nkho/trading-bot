# Paper-first book, $20k default exposure, agentic roadmap

This document ties **operating mode**, **capital assumptions**, and **how autonomy should grow** without promising returns. A “winning” system here means **repeatable process**: gates first, evidence second, bounded automation third.

## Operating mode (non-negotiable)

- **Paper only** until you deliberately change `ALPACA_BASE_URL` and satisfy live safeguards (`FORTRESS_LIVE_TRADING_ACK`, pre-trade gate, operator halt).
- **Default book size** for screening and sizing paths is **$20,000** (`defaults.portfolio_value_usd` in `config/fortress_runtime.yaml`, or `FORTRESS_PORTFOLIO_VALUE` / `PORTFOLIO_VALUE`).
- **Per-order caps** remain independent: `FORTRESS_MAX_ORDER_NOTIONAL_USD` (default 25,000) and `FORTRESS_MAX_ORDER_QTY` in `utils/pre_trade_gate.py` — tune so a single fill cannot blow past your intended max risk.

## Strategy structure (what actually runs)

1. **Universe → screen** (`daily_screen`): produce ranked candidates under `policy_profiles.json` and current params (`data/current_params.json` where applicable).
2. **Intraday layers** (`intraday_sniper`, `spy_intraday_swing`): time-boxed, smaller-scope signals; log shadow outcomes where implemented (JSONL) before trusting size.
3. **Entry** (`entry_agent`): rules + windows; use `print_entry_skips` to debug why names do not fire.
4. **Risk & compliance** (`risk_guardian`, `pre_trade_gate`, halt file/API, regime checks): block or shrink actions before the broker sees them.
5. **Execution mode** (`FORTRESS_EXECUTION_MODE`): `human_in_loop` for staged rollout; `autonomous` only after shadow metrics and halts are trusted.

Keep **policy** (profiles, caps) and **runtime** (agent toggles, default equity) in separate layers so you can scale capital without rewriting agents.

## Future-proof agentic shape

Prefer **staged autonomy** over a single “do everything” agent:

| Phase | Behavior |
|-------|----------|
| Shadow | Propose and log only; compare to realized paper fills and slippage. |
| HITL | Queue approved intents (`execute_pending`); human confirms sizing and news. |
| Bounded auto | Submit only inside pre-trade notional/qty, execution mode, and trading halt state. |

**LLM usage** (`fortress_runtime.yaml` → `llm`): treat models as **advisory** unless explicitly wired to deterministic tools with the same gates as code paths. Version prompts and log which model advised which run (audit bundle / run registry).

**Extensibility**: new agents should expose (1) inputs, (2) outputs schema, (3) shadow log path, (4) `is_agent_enabled` key — so orchestrator can schedule them without forking core risk logic.

## Checklist after changing book size

- [ ] `config/fortress_runtime.yaml` — `defaults.portfolio_value_usd` and `spy_intraday_swing.default_equity_usd` aligned.
- [ ] Server `.env` — optional `FORTRESS_PORTFOLIO_VALUE=20000` if you override YAML.
- [ ] `FORTRESS_MAX_ORDER_NOTIONAL_USD` — still appropriate vs $20k book (e.g. cap single SPY swing below a fraction of book).
- [ ] `ALPACA_BASE_URL` contains `paper` on non-prod hosts.

## Related files

- `utils/runtime_config.py` — built-in default portfolio, YAML merge, env overrides.
- `config/policy_profiles.json` — risk / screening knobs per profile; top-level `book_reference` documents implied **$20k** dollar bands for the active **balanced** percentages (percents remain authoritative).
- `agents/entry_agent.py` — caps proposed stock notional by active profile `max_position_size_pct` so sizing stays consistent with `risk_guardian`.
- `utils/pre_trade_gate.py` — last-line submission caps and halt.
