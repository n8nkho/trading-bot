# Fortress Trading Bot – Session Handoff

**Last updated:** March 14, 2026

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

## Completed (March 14, 2026 – Error Detective + Pristine)

- **Error Detective–driven fixes:**
  - **risk_guardian:** TypeError (float + NoneType) – equity, today_pnl, adjusted_value and position/sector values now normalized with `(x or 0)` / `float(...)`.
  - **command_center:** TypeError in total_pnl – use `float(perf.get("total_pnl") or 0) + unrealized_pnl`.
  - **performance_analyzer:** KeyError `'decision'` – only process log lines with valid `decision` and `outcome` dicts; skip malformed lines.
  - **exit_monitor:** None decision – if `evaluate_exit`/`check_option_exit` returns None/non-dict, treat as HOLD and use `.get()` for logging.
  - **Alpaca auth (ValueError: You must supply a method of authentication):** Guarded TradingClient creation in `orchestrator.py`, `sync_alpaca.py`, `dashboard/command_center.py` (test_connection + get_recent_orders), and `agents/fortress_orchestrator.py` – try/except ValueError or missing keys; return None / friendly error / empty data instead of crashing.
- **Universe:** `config/universe_tickers.py` (lightweight `get_sp500_tickers`) and regime_center/exit_monitor fixes from prior session remain in place.

## Completed (March 14, 2026 – Next steps done)

- **1. Error Detective:** Fixes are in place; the 31 reported errors are from existing log lines (last 7 days). New runs should not reproduce them once logs rotate. Run `python3 agents/error_detective.py` periodically to confirm (use `python3` if `python` is not available).
- **2. Env for paper trading:** `check_health.py` now has a **2.5 ALPACA (paper trading)** section: reports "Alpaca keys: SET" or "NOT SET" (no values printed). Missing/invalid keys remain handled without tracebacks in orchestrator, sync, Command Center, fortress_orchestrator.
- **3. exit_monitor without screener:** News is **lazy-imported** inside the function that needs it. `exit_monitor` loads and `monitor_positions` is importable without scipy/screener_agent; news check runs only when that code path executes and logs a warning if screener is unavailable.
- **4. API robustness:** **Wash trade:** `orchestrator.execute_buy_order` now catches Alpaca errors containing "wash trade" or "40310000", logs a WARNING with guidance ("Use complex orders or cancel the existing order first"), and returns the error dict. **yfinance 401:** Already non-fatal; `utils/provider_safety.py` has a yfinance circuit breaker for optional use in hot paths.
- **5. Sync log SyntaxError:** Confirmed `logs/sync.log` is written by cron: `sync_alpaca.py >> logs/sync.log 2>&1`. `sync_alpaca.py` compiles cleanly; any SyntaxError in the log is historical (e.g. old traceback).
- **6. Health and smoke tests:** `check_health.py` passes (incl. new Alpaca section); `run_strategies.py inefficiency` and `from agents.exit_monitor import monitor_positions` succeed.

## Pristine verification (confirm bot is clean)

Run from project root:

```bash
python3 scripts/confirm_pristine.py
```

This checks: **exit_monitor**, **risk_guardian**, **performance_analyzer** imports; **run_strategies.py inefficiency** and **sector**; and **check_health.py**. All must pass (exit 0). Optional: then run `python3 agents/error_detective.py` and treat the 31 log entries as historical until new logs overwrite them.

## Solver agent (review errors → re-test → ensure pristine)

**agents/solver_agent.py** runs periodically to: (1) run Error Detective (scan logs, last 7 days), (2) run Pristine verification, (3) run Health check, (4) run Compliance checklist, (5) build recommendations from a playbook (no automatic code changes). Writes **logs/solver_report.json** and **logs/solver_report.txt**.

- Run: `python3 agents/solver_agent.py [--days 7]`
- Command Center: **System Health** shows last Solver result (Pristine OK/FAIL, error count); **Agent Activity** lists Solver Agent; **GET /api/solver** returns full report.
- Cron (optional): e.g. weekly `0 4 * * 0 cd /home/ubuntu/trading-bot && python3 agents/solver_agent.py --days 7 >> logs/solver_agent.log 2>&1`

## Next steps (optional / ongoing)

- Run Error Detective after a few days of new logs to confirm no new error patterns.
- Command Center: refresh after changes to see latest agent activity and performance.
- If yfinance 401 spikes: consider using `provider_safety.guarded_call("yfinance", fn)` in critical data-fetch paths.

---

## Monetization & licensing

*More updates planned before selling; this section will be revised.*

**Your copy (master)**  
- `data/` is gitignored. When **no** `data/license.json` exists, the app treats the install as **master** (full access). Your bot stays master without any license file. Optionally create `data/license.json` with `{"tier": "master", "name": "Master (internal)"}` and no signature for clarity—only on your machine, not in git.

**What’s in place**  
- **Tiers:** `config/tiers.py` — **Master** (vendor only, never sold) + **4 customer tiers**: Starter (base), Growth, Pro, Enterprise. Highest customer tier is always a subset of Master. Helpers: `is_master()`, `is_customer_tier()`, `CUSTOMER_TIERS_ORDERED`.  
- **License:** `config/license.py` reads `data/license.json`; missing file → master; invalid/expired signature → downgrade to starter.  
- **Signed licenses:** `scripts/generate_license.py` — generate customer licenses:  
  `python3 scripts/generate_license.py pro "Customer Name" 2026-12-31`  
  Paste output into **their** `data/license.json`; they never get the signing secret.  
- **Gating:** run_strategies, orchestrator, backtest, Fortress, Command Center use `strategy_allowed()`, `backtest_allowed()`, `fortress_allowed()`, etc.  
- **Command Center:** Shows license tier in System Health; upgrade banner for Starter / invalid license.  
- **Customer risk:** `config/customer_settings.py` + `data/customer_settings.json` (bounded position size, stops, max trades).  
- **Docs:** `docs/LICENSING.md` — overview, generating licenses, keeping master separate. **`docs/TIER_COMPATIBILITY.md`** — updates compatible with all tiers; tier upgrade = new license only; developer rules so patches and upgrades never break a tier.
- **Dashboard by tier:** Same Command Center codebase; visibility aligned to tier. Backend passes `show_fortress_agent`, `show_backtest_health` in `health.license`; frontend shows “Plan: …” in header, hides Fortress Hedging agent row for Starter/Growth, and shows hedging recommendations as “Upgrade to Pro” when Fortress not allowed.

**Before selling (planned updates)**  
- ~~Move signing secret to env~~ **Done.** **Random key pair (no hardcoded secret):** Run `python scripts/generate_license_keypair.py` once; creates `data/.license_private.pem` (gitignored) and `config/license_public.pem` (committed). New licenses use Ed25519; verification uses public key only. Legacy HMAC (LICENSE_SIGNING_SECRET) still supported for old licenses.  
- **Pricing:** Suggested bands in **docs/PRICING_AND_WTP.md**; list prices in **config/pricing.py** (Starter $49/mo → Enterprise $399/mo). Update when you lock final numbers.  
- ~~Customer build packaging~~ **Done.** **scripts/build_customer_package.sh** produces `dist/fortress-$(VERSION).tar.gz` (excludes data/, .env, venv, .git, dist/, logs/). **data/customer_settings.json.example** added; copy to `data/customer_settings.json` to tune.  
- Later: payment integration (Stripe/Paddle, etc.) and license delivery on purchase.

**Customer flow**  
- Same codebase; you issue each customer a signed `data/license.json` for their tier. They deploy with that file only; no master license, no signing secret.

**Shipping updates without breaking customer installs**  
- **Strategy:** `docs/UPDATES_AND_SUPPORT.md` — versioned releases, additive-only minor/patch, backup-before-update, one supported update path.  
- **Update script:** `scripts/apply_update.sh /path/to/fortress-1.2.0.tar.gz` — backs up `data/` and `.env`, unpacks release (excluding data/.env/venv), restores backup, runs `check_health.py`. Build tarball from project root with `tar czf fortress-X.Y.Z.tar.gz -C /path/to/trading-bot .` so there is no top-level folder.  
- **Compatibility check:** `python3 scripts/check_compatibility.py` — validates VERSION and optional license.json; use before/after update or for support.  
- **Add-ons:** New optional features can ship as files in `customer_addons/` (see `docs/ADDONS.md`); core unchanged, no full upgrade required.

---

## Open / next (unchanged)

- **Fortress cron** – consider venv path
- **Auto-execution** – monitor first trades (March 2+)
- **Port config** – Command Center default 8083; Oracle firewall may need ingress rule
- **LLM performance** – Llama watchdog reports suboptimal latency (timeouts around 30s) but healthy; continue to monitor and tune if it worsens
- **External data quirks** – yfinance occasional 401 \"Invalid Crumb\" and news items missing `title` are logged but handled as non-fatal warnings

---

## Completed (March 13, 2026)

- **sync_alpaca.py** – Rewritten (was broken with SyntaxError); loads ALPACA_* from env/.env, writes `data/positions.json` at project root, preserves entry_time. Cron and Command Center Sync Alpaca now run successfully.
- **Productization / robustness (no behavior change to live trading):**
  - **Schemas:** `models/schemas.py` – dataclasses for Candidate, Position, Decision, OutcomeRecord, Recommendation, RegimeRecord (for future validation/backtest).
  - **Provider safety:** `utils/provider_safety.py` – in-memory circuit breakers for yfinance, Grok, OpenAI; opportunity_analyzer uses guarded_call for yfinance in outcome checks.
  - **Agent health:** `agents/agent_manager.py` writes `data/agent_health_snapshot.json` after each run for dashboards/meta-agents.
  - **Backtest:** `backtest/replay.py` – read-only replay of daily_signals for outcome stats; `python backtest/replay.py --days 30`.
  - **Tenant/license:** `config/tenancy.py`, `config/license.py`, `data/license.json` – single-tenant default, dev-unlimited plan; no enforcement yet.
  - **Meta-strategy analyzer:** `agents/meta_strategy_analyzer.py` → `data/meta_strategy_recommendations.json` (advisory only; reads decisions, outcomes, agent_health_snapshot).
- **Smoke tests:** Full system and Command Center smoke-tested; health check passes. Regime confirmed adaptive (no change needed).
- **Command Center:** Total P&L is lifetime realized from decisions_log + unrealized from positions (positions.json had no pnl until sync; sync now fixed).
- **Intraday sniper & Fortress hedging:** (1) Orchestrator sets CWD to project root at startup so cron has correct paths. (2) Snipe command appends a timestamp line to `logs/sniper.log` each run so Command Center “last run” is fresh. (3) `run_fortress()` logging fixed—result is the strategies dict; iterate it directly. (4) Unknown command prints clear message and lists all commands (snipe, fortress included). (5) Fortress cron is Sun/Wed 00:00 only; to run weekdays too add: `0 18 * * 1-5 cd /home/ubuntu/trading-bot && /home/ubuntu/trading-bot/venv/bin/python orchestrator.py fortress >> logs/fortress.log 2>&1`
- **Orchestrator last run:** Orchestrator now appends a line to `logs/orchestrator.log` at the start of every run so Command Center shows a current last run.
- **Agent activity list:** The 16 rows are cron/key agents with a dedicated log; add to `AGENT_LOGS` in `dashboard/command_center.py` to show more.
- **Committed (March 13, 2026 – evening):** Orchestrator log touch + absolute log path; screener dynamic universe (base + `data/universe_extra.json` + RISK_OFF defensive prepend); intraday sniper uses same universe as screener; `universe_size` in daily_signals for dashboard; `data/current_params.json` recreated with expanded range (drop -20% to -3%, RSI 42, vol 1.4x). **Marker:** git tag `pre-march14` at this commit. Backup: repo + tag; `data/` is gitignored so backup `data/` separately if needed.

---

## Completed (March 13, 2026 – ROADMAP_SELLER gaps + full test)

- **A1 Backtest:** `backtest/strategy_backtest.py` (historical screener backtest), `backtest/run_backtest.py` (single entry: `replay --days N`, `screener --days N`). Health check runs backtest smoke (replay 1 day) and reports "Backtest module: OK".
- **A2 Agent audit:** `agents/inefficiency_trader.py` – template only; returns `[]` and logs; no placeholder runs. `run_strategies.py` – each strategy wrapped in `_run_safe()` (try/except, log and exit 1 on failure); **lazy imports** per strategy so one broken dependency (e.g. scipy) does not block others (e.g. inefficiency, flow). Flow tracker already returns list; forex_sniper already env-gated (prior session).
- **A3 Ops:** `check_health.py` – positions support both list and `{"positions": [...]}`; new section 8 "Backtest module" smoke. Circuit breaker already visible in Command Center (risk.circuit_breaker_active).
- **B Seller:** `setup.sh` (venv, .env from .env.example if missing, data/config, health check); `.env.example` extended (OANDA, XAI_API_KEY, COMMAND_CENTER_PORT, Twilio); Command Center footer: disclaimer + version from `VERSION` file; `VERSION` (1.0.0); `EULA.md` (as-is, your responsibility, no custody); agent tiers (core / extended / experimental) in `PROJECT_CONTEXT.md`.
- **Full test:** Health check (incl. backtest smoke), `run_strategies.py inefficiency`, `flow`, `momentum`, `backtest/run_backtest.py replay --days 1`, `screener --days 5`; lint on changed files – no errors.

---

## Completed (Licensing and tiered deployments)

- **Tiers:** `config/tiers.py` – master (full), starter, pro, enterprise. Gate strategies, backtest, Command Center, Fortress, universe size.
- **License:** `config/license.py` – reads `data/license.json`, optional signature (HMAC) and expiry; invalid/expired downgrades to starter. `scripts/generate_license.py` to generate signed licenses.
- **Customer settings:** `config/customer_settings.py` – bounded risk params from `data/customer_settings.json` (position size, stop/target %, max trades, etc.); clamped to safe ranges.
- **Add-ons only:** `config/addon_loader.py` – loads `customer_addons/*.py` with `register(env)`; hooks `on_screen_done`, `on_before_trade`, `on_after_trade`. Core must not be modified.
- **Integrity:** `utils/integrity.py` + `scripts/build_manifest.py` – optional manifest of core file hashes; when license has `"integrity_check": true` and manifest exists, `get_plan()` runs the check and downgrades to Starter if core was modified. See **docs/PROTECTION_AND_ANTI_TAMPER.md** for copy/hack prevention summary.
- **Wiring:** Orchestrator uses `_effective_max_positions()` from customer_settings; Fortress gated by tier; run_strategies and backtest gate by tier. entry_agent uses customer position_size min/max.
- **Docs:** `docs/LICENSING.md`, `docs/ADDONS.md`; EULA updated (no modifying core; add-ons only).
- **Customer build next step:** Command Center shows **License** tier in System Health and an **upgrade banner** when tier is Starter or license invalid. Add-on hooks wired in orchestrator: `invoke_screen_done(candidates)` after screening; `invoke_before_trade(trade)` before each execution (approved_for_execution); `invoke_after_trade(decision, "logged")` after track_decision and `invoke_after_trade(trade, "executed")` after successful order.

---

## Agentic compliance (credential)

- **Frameworks:** Bot aligned with WEF *AI Agents in Action* (role, safeguards, oversight, transparency), UK agentic/consumer guidance, and EU AI Act–style transparency/oversight. See **docs/AGENTIC_COMPLIANCE.md** for mapping and one-page summary.
- **Checklist:** **scripts/compliance_checklist.py** runs 10 verifiable checks (defined role, decision logging, outcome tracking, safeguards, dry-run, bounded settings, dashboard, EULA, no custody, health verification). Use for self-attestation, RFPs, or certification prep.
- **API:** **GET /api/compliance** (Command Center) returns JSON report (`passed`, `total`, `all_passed`, `checks[]`) for audits or credential display.

---

## Key paths

| What | Path |
|------|------|
| Main controller | `orchestrator.py` |
| Screener | `agents/screener_agent.py` |
| Command Center | `dashboard/command_center.py` (or run as service: `sudo bash scripts/install_command_center_service.sh`) |
| Sync Alpaca | `sync_alpaca.py` |
| Config | `.env` (do not edit via AI) |
| Data | `data/positions.json`, `data/daily_signals_*.json`, `data/regime_recommendations.json`, `data/agent_health_snapshot.json`, `data/meta_strategy_recommendations.json` |
| Regime alignment | `agents/regime_alignment.py` |
| Schemas | `models/schemas.py` |
| Backtest | `backtest/run_backtest.py` (replay / screener), `backtest/replay.py`, `backtest/strategy_backtest.py` |
| Agentic compliance | `docs/AGENTIC_COMPLIANCE.md`, `scripts/compliance_checklist.py`, GET `/api/compliance` |
| Solver agent | `agents/solver_agent.py`, `logs/solver_report.json`, GET `/api/solver` |
| Tier pricing | `config/pricing.py`, `docs/PRICING_AND_WTP.md` |
| Differentiator (marketing) | `docs/DIFFERENTIATOR_MARKETING.md` – four pillars + **Simple steps (no technical experience needed)**; `scripts/verify_differentiators.py` + GET `/api/differentiators` + Command Center **Verify differentiators** panel |
| **Customer docs (non-technical)** | **docs/CUSTOMER_GUIDE.md** – main step-by-step guide; **docs/HOW_TO_UPDATE_FOR_CUSTOMERS.md** – update in minimal steps; .cursor/rules/customer-instructions.mdc – assume non-technical, dashboard-first, bare minimum |
| **Sell readiness** | **docs/SELL_READINESS_ANALYSIS.md** – packaging/selling checklist; must-do: move signing secret to env; should-do: build_customer_package.sh, customer_settings example |
