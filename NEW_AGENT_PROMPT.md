# Prompt for New Agent (Session Handoff)

If the session was lost, paste the following to a new agent so it can continue from the current state.

---

**Context:** Fortress Trading Bot — autonomous paper-trading system (Alpaca), ~29+ agents, orchestrator-driven. Goals: near-zero loss, high win rate, strict quality filters.

**Current state (as of 2026-03-05):**
- **Command Center** (Flask, port 8083) shows **6 recommendations** from three sources:
  1. **Opportunity Analyzer** (`agents/opportunity_analyzer.py`) → `data/opportunity_recommendations.json` (equity screening: safe opportunities lost, criteria suggestions).
  2. **Hedging Opportunity Analyzer** (`agents/hedging_opportunity_analyzer.py`) → `data/hedging_recommendations.json` (missed hedge opportunities: bonds, VIX, commodities, pairs).
  3. **Defensive Universe Scanner** (`agents/defensive_universe_scanner.py`) → `data/defensive_recommendations.json` + `data/defensive_watchlist.json` (low-beta defensive names).
- **Fallback marker:** `git checkout fallback-post-command-center-recommendations-20260305` restores this state.
- **Refresh recommendations and restart dashboard:**  
  `bash scripts/refresh_command_center_recommendations.sh`  
  Then hard-refresh the browser to see all 6 (or more) recommendations.
- **Docs:** `docs/INTELLIGENT_AGENTS_REVIEW.md` describes opportunity/hedging analyzers and ideas for future agents (defensive scanner, regime alignment, etc.).

**What to do next (examples):**
- Add or change recommendation sources: update `dashboard/command_center.py` `get_recommendations()` and ensure the corresponding agent writes JSON under `data/` with a `recommendations` list (each item: `title`, `body`, `action`, `severity`).
- Add a new agent: follow patterns in `agents/opportunity_analyzer.py` or `agents/hedging_opportunity_analyzer.py`; add orchestrator command and cron if needed; wire Command Center if it should show in RECOMMENDATIONS.
- Roll back: use the `Rollback` section in `PROJECT_CONTEXT.md` (e.g. `git checkout fallback-post-command-center-recommendations-20260305`).

**Key paths:** `dashboard/command_center.py`, `agents/opportunity_analyzer.py`, `agents/hedging_opportunity_analyzer.py`, `agents/defensive_universe_scanner.py`, `data/opportunity_recommendations.json`, `data/hedging_recommendations.json`, `data/defensive_recommendations.json`, `scripts/refresh_command_center_recommendations.sh`, `PROJECT_CONTEXT.md`.
