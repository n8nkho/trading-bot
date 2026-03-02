# Fortress Trading Bot – Session Handoff

**Last updated:** March 1, 2026

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

## Open / next

- **Smart Money Trader** – disabled (pandas bug); fix or remove cron job
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
| Data | `data/positions.json`, `data/daily_signals_*.json` |
