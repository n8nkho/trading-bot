# Roadmap: Robustness + No-Brainer Seller

**Goal:** Fix gaps (backtesting, incomplete agents) and productize so the bot is a clear, low-friction sell for retail: "You own it, you run it, your account, your control."

---

## Part A: Robustness (so it’s credible to sell)

### A1. Backtesting (high impact)

**Current:** `backtest/replay.py` only replays existing `daily_signals_*.json` and computes stop/target outcomes; no full strategy backtest on historical data.

**To add:**

| Task | What | Effort |
|------|------|--------|
| **Historical screener backtest** | For a date range, run screener logic (drop/RSI/volume filters) on historical OHLCV (yfinance or Alpaca); record "would-have-qualified" candidates; then compute outcome (stop hit / target hit / still open) over N days. Output: win rate, avg P&L per trade, max drawdown. | Medium |
| **Reuse existing replay** | Keep `replay.py` as "replay past runs"; add `backtest/strategy_backtest.py` that (1) loads historical data, (2) applies current params, (3) simulates entries/exits with current stop/target. | Medium |
| **Single entry point** | e.g. `python backtest/run_backtest.py --start 2025-01-01 --end 2025-03-01 --strategy screener` prints summary + optional CSV/JSON. | Small |

**Outcome:** You can say "backtested on N months of data, X% win rate, Y% avg return per trade" and show a report. No-brainer: buyers see evidence, not just live hope.

---

### A2. Agent audit and status (medium impact)

**Current:** 29+ agents; some are full (screener, exit_monitor, risk_guardian, fortress_orchestrator, opportunity_analyzer, etc.), others are stubs or partial.

**Stub / partial (fix or document):**

| Agent | Status | Action |
|-------|--------|--------|
| **forex_sniper** | Hardcoded `YOUR_OANDA_API_KEY`; pseudo-code (e.g. `fetch_eur_usd_chart()` undefined). | Either: (1) Implement with env vars + real OANDA calls and document "optional, needs OANDA account", or (2) Mark "experimental/disabled" in docs and skip in run_strategies if not configured. |
| **inefficiency_trader** | All helpers return placeholders (eod_imbalance, options_pinning, etc.). | Either: implement at least one (e.g. index rebalancing from a public source) or clearly label "template only – implement per your data source" and return empty list by default. |
| **flow_tracker** | Sample/mock data. | Document "sample data; plug in your options flow feed" or gate behind a config flag "flow_tracker_enabled". |

**Recommended:** Don’t implement every stub before selling. Instead:

1. **Tier agents:** "Core" (screener, exit_monitor, risk_guardian, fortress, regime, universe_builder, sniper, Command Center) = fully supported. "Extended" (momentum, trump, merger_arb, smart_money, etc.) = documented as "included, use at your discretion." "Experimental" (forex_sniper, inefficiency placeholders, flow_tracker) = listed in docs as optional/template.
2. **Health check** already validates core imports; add a simple `python -c "from agents.forex_sniper import ..."`-style smoke test for each agent and document which are expected to fail if not configured.
3. **Run_strategies / main_loop:** Ensure no strategy is required for "basic" operation; optional strategies fail gracefully (log + skip) so one broken agent doesn’t kill the stack.

**Outcome:** Clear "what’s production vs optional," fewer support surprises, and you can sell on "core is robust; extended strategies included as bonus."

---

### A3. Operational robustness (quick wins)

| Task | What | Effort |
|------|------|--------|
| **Circuit breaker visibility** | Command Center already shows circuit breaker; add one line in dashboard: "Trading paused after N consecutive losses (reset in risk_status)." | Small |
| **Backtest in health check** | Optional: `check_health.py` can run a 1-day backtest dry run (no orders) and report "Backtest module: OK." | Small |
| **Outcome records** | Keep filling `outcome_records.jsonl` from live runs; pattern_miner and replay use it. Ensures backtest and "self-improving" story stay aligned. | Done / ongoing |

---

## Part B: No-brainer seller (product and positioning)

### B1. One-line pitch

- **"Fortress is automated swing/mean-reversion and risk control for retail. You buy the software, run it on your server, connect your broker. Your account, your keys, your control. We don’t touch your money."**

Use this everywhere: license page, docs, Command Center footer.

---

### B2. First-run experience (low friction)

| Task | What | Effort |
|------|------|--------|
| **Setup script** | e.g. `./setup.sh` or `python setup.py`: (1) Check Python + venv, (2) Copy `.env.example` → `.env`, (3) Create `data/` and `config/watchlist.json` from template if missing, (4) Run `check_health.py` and print "Next: add Alpaca keys to .env and run screen once." | Small |
| **.env.example** | All required vars with placeholders (ALPACA_*, optional GROK, OANDA, etc.) and one-line comments. | Small |
| **Default paper-only** | Enforce paper broker URL by default; document "how to switch to live" without encouraging it in the first step. | Already there |
| **Command Center disclaimer** | One line in UI: "For educational/research use. You are responsible for your own trading and risk." | Small |

**Outcome:** Buyer gets to "green health check + one screening run" in minutes, not hours.

---

### B3. Safety and trust

| Task | What | Effort |
|------|------|--------|
| **EULA / Terms** | Short: "Software as-is; no guarantee of profit; you are solely responsible for trading and compliance; we don’t have access to your account." | Small (template) |
| **No custody** | Docs + UI: "We never hold your keys or execute on your behalf. The bot runs in your environment with your API keys." | Small |
| **Risk summary** | One page: "What Fortress does (screening, exits, risk limits, circuit breaker); what it doesn’t (advice, custody, latency competition)." | Small |

**Outcome:** Legal and narrative alignment with "no risk to you" and "customer owns and controls."

---

### B4. Packaging and delivery

| Task | What | Effort |
|------|------|--------|
| **License gating** | Use existing `config/license.py` + `data/license.json`: e.g. "Starter" (screener + exit + 1 strategy) vs "Pro" (all strategies + backtest). No need to phone home; local validation only. | Small |
| **Version + build** | Single place for version (e.g. `__version__` or `VERSION` file); show in Command Center footer: "Fortress v1.x – you own it, you run it." | Small |
| **Delivery** | Private repo clone or zip + license key; README: "Install deps, run setup, add keys, run screen." | You already have repo |

**Outcome:** Clear product identity and a simple "Starter vs Pro" story if you want tiered pricing.

---

### B5. Proof (backtest + narrative)

| Task | What | Effort |
|------|------|--------|
| **Backtest report** | Once A1 is done: run backtest for e.g. 6–12 months, save summary (win rate, avg P&L, max DD, number of trades). Ship as `backtest/reports/sample_report_YYYYMM.md` or PDF. | After A1 |
| **Positioning** | "Designed for retail: no latency race with institutions; edge is quality of setups and risk control, not speed." | Docs + pitch |

**Outcome:** "Backtested and built for retail" makes the value proposition obvious.

---

## Suggested order of work

1. **Quick wins (1–2 days)**  
   - B2: setup script, .env.example, Command Center disclaimer.  
   - B3: EULA snippet, no-custody line, one-page risk summary.  
   - B4: version in UI, license tier names (even if both tiers unlock everything at first).  
   - A2: Document agent tiers (core / extended / experimental) in PROJECT_CONTEXT or README.

2. **Backtest (3–5 days)**  
   - A1: Historical screener backtest script; run on 6–12 months; generate a single report.  
   - B5: Add sample backtest report to repo and reference it in the pitch.

3. **Agent cleanup (2–3 days)**  
   - A2: Forex_sniper: env vars + "disabled if no OANDA" or mark experimental.  
   - A2: Inefficiency: return empty or document "template."  
   - A2: Ensure run_strategies / main_loop don’t assume every strategy is fully implemented (graceful skip).

4. **Polish**  
   - A3: Circuit breaker line in dashboard; optional backtest smoke in check_health.  
   - B1: One-line pitch in README and Command Center.

---

## Summary

| Area | What makes it "no brainer" |
|------|----------------------------|
| **Robustness** | Real backtest report; core agents clearly supported; stubs documented or gated. |
| **Trust** | EULA + no custody + "you run it, your keys"; disclaimer in UI. |
| **Friction** | Setup script + .env.example + one-page "what it does / doesn’t do." |
| **Positioning** | One-line pitch + "retail, no latency race" + optional Starter/Pro tiers. |

After Part A (backtest + agent clarity) and Part B (setup, safety, packaging, pitch), the product is in shape to sell as: **robust, backtested, retail-focused software that the customer owns and runs with no risk to you.**
