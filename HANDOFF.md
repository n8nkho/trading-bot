# Fortress Trading Bot – Session Handoff

**Last updated:** March 7, 2026

When resuming work, read this file first, then `PROJECT_CONTEXT.md` and `SYSTEM_REVIEW.md`.

**Auto-update:** A Cursor rule (`.cursor/rules/handoff-update.mdc`) instructs the AI to update this file when you say "resume"/"continue" or after completing substantial work. The AI cannot detect idle time, so it updates on your next message.

---

## Resume prompt (copy & paste)

```
Resume Fortress Trading Bot. Read HANDOFF.md, PROJECT_CONTEXT.md, and SYSTEM_REVIEW.md.
Continue from there. [Add your specific task if any.]
```

Or with file refs: `@HANDOFF.md @PROJECT_CONTEXT.md @SYSTEM_REVIEW.md`

---

## Completed this session

### Fixes
- Screener: added `current_price` to candidates (auto-execution was skipping all)
- Orchestrator: fixed `results[2]` IndexError in fundamental analysis
- Orchestrator: removed duplicate `run_fortress()` and recursion bug
- Env vars: fortress, vix_insurance, bond_manager use ALPACA_* only
- grok_sentiment: supports GROK_API_KEY and XAI_API_KEY
- run_strategies: smartmoney graceful "disabled", import removed
- exit_monitor: removed duplicate code, project-root paths
- sync_alpaca, dashboard: robust paths

### New: Command Center dashboard
- `dashboard/command_center.py` – Flask app on port 8083 (or `COMMAND_CENTER_PORT=…`)
- `dashboard/templates/command_center.html` – single-page UI
- Sections: System health, Agent activity, Trading performance, News, Recommendations, Live activity feed
- APIs: `/api/health`, `/api/agents`, `/api/performance`, `/api/news`, `/api/recommendations`, `/api/feed`
- Run: `python dashboard/command_center.py`
- Oracle Console: open port 8083 for external access

### Verified
- Paper trade placed and cancelled successfully
- Health check passes
- Fortress command works

---

## Completed (March 7, 2026)

- **Smart Money Trader** – re-enabled; pandas fix in `check_structure_break`; cron `0 10 * * 1-5` confirmed
- **Improvements implemented:** (1) Daily profit target/pause (orchestrator + exit_monitor records to `data/daily_realized_pnl.jsonl`); (2) Inverse-vol sort for qualified candidates; (3) Regime alignment agent (`agents/regime_alignment.py`) → `data/regime_recommendations.json`; Command Center shows regime recs; refresh script includes regime_alignment
- **End-to-end tested:** check_health.py, run_strategies.py smartmoney, orchestrator status, regime_alignment; no linter errors; no contradictions (core objective: near-zero loss, high wins, varied risks)
- **Self-improving capability (full implementation):** (1) **Phase 1 outcome logging** in `opportunity_analyzer.py`: for signals 5+ days old, compute safe_win/stop_hit/open per candidate and append to `data/outcome_records.jsonl` (backfill current_price from yfinance when missing). (2) **Phase 2 pattern miner** `agents/pattern_miner.py`: reads outcome_records (12 weeks), buckets drop/RSI/volume/regime, aggregates safe_win rate, writes `data/discovered_patterns.json` and 0–2 items to `data/pattern_discovery_recommendations.json`; cron Sunday 2 AM. (3) Command Center shows pattern_discovery recommendations (up to 2). (4) Orchestrator saves `regime` in daily_signals for future outcome records. No automatic param changes; all suggestions advisory.

### Auto-refresh and News UI (March 7, 2026)
- **Automated refresh:** Command Center starts a daemon thread that runs the 6 recommendation agents (opportunity_analyzer, hedging_opportunity_analyzer, defensive_universe_scanner, regime_alignment, no_trade_analyzer, pattern_miner) 20 seconds after startup and then every 15 minutes. No pkill/restart—data files are refreshed so the dashboard stays current when you open it.
- **News impacting strategy:** Backend returns **top 10** items with **url** (from yfinance `clickThroughUrl`/`canonicalUrl`). Frontend: scrolling list (max-height 320px), each headline is a link to source when `url` is present; subtitle updated to “Top 10, scrollable”.

## Open / next

- **Fortress cron** – consider venv path
- **Auto-execution** – monitor first trades (March 2+)
- **Port config** – Command Center default 8083; Oracle firewall may need ingress rule

---

## Key paths

| What | Path |
|------|------|
| Main controller | `orchestrator.py` |
| Screener | `agents/screener_agent.py` |
| Command Center | `dashboard/command_center.py` |
| Config | `.env` (do not edit via AI) |
| Data | `data/positions.json`, `data/daily_signals_*.json`, `data/regime_recommendations.json`, `data/daily_realized_pnl.jsonl` |
| Regime alignment | `agents/regime_alignment.py` |
