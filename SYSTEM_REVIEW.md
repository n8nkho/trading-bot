# Fortress Trading Bot – End-to-End System Review

**Review date:** March 1, 2026  
**Scope:** Inconsistencies and potential conflicts across config, data flow, API usage, and code paths.

---

## 1. CRITICAL BUGS (Fix First)

### 1.1 Auto-execution never gets price → all candidates skipped
- **Where:** `orchestrator.py` auto-execution (lines ~1258–1318), `agents/screener_agent.py` (candidate dict ~245–252).
- **Issue:** Screener builds candidates with `ticker`, `drop_pct`, `rsi`, `volume_ratio`, `news`, `analysis`, `vision_signal` but **does not set `current_price`**. Orchestrator filters with `current_price = candidate.get('current_price', 0)` and skips when `not current_price or current_price <= 0`, then later uses `candidate['current_price']` for execution.
- **Effect:** Every candidate is skipped with reason "No valid price data"; auto-execution never places trades.
- **Fix:** In `screener_agent.py`, add `'current_price': latest_close` (or equivalent from `stock_data['Close'].iloc[-1]`) to each candidate dict when appending to `candidates`.

### 1.2 IndexError in fundamental analysis result handling
- **Where:** `orchestrator.py` lines 448–449 inside `analyze_candidate()`.
- **Issue:** `tasks` has two elements (Grok, Fundamental), so `results` has indices 0 and 1. Code uses `results[2]` for fundamental failure check.
- **Effect:** When fundamental analysis is run (confidence ≥ 0.85), `isinstance(results[2], Exception)` can raise `IndexError`.
- **Fix:** Use `results[1]` for the fundamental result (index 1), not `results[2]`.

### 1.3 Duplicate `run_fortress()` and recursive crash on error
- **Where:** `orchestrator.py`: first `run_fortress()` at ~765–784, second at ~800–826.
- **Issue:** Second definition overwrites the first. On exception, the second calls `run_fortress()` again → infinite recursion and stack overflow.
- **Fix:** Keep a single `run_fortress()`; in the `except` block log and optionally re-raise or return `None`, do **not** call `run_fortress()`.

---

## 2. ENVIRONMENT / API KEY INCONSISTENCIES

### 2.1 Alpaca: two naming conventions
- **ALPACA_* (used by most):** `orchestrator.py`, `sync_alpaca.py`, `check_tsla.py`, `bond_manager.get_client()`, `vix_insurance` (inside get_client).
- **APCA_* (Alpaca legacy):** `agents/fortress_orchestrator.py` line 61 (`get_portfolio_status()`), `agents/bond_manager.py` lines 16–17 (module-level, unused), `agents/vix_insurance.py` lines 18–19 (module-level).
- **Effect:** If `.env` only has `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` (as in PROJECT_CONTEXT.md), `fortress_orchestrator.get_portfolio_status()` gets `None` and will fail when creating `TradingClient`. Same for any code that only reads `APCA_*`.
- **Fix:** Use one convention project-wide. Prefer `ALPACA_*` and replace all `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` with `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`, or document that both must be set.

### 2.2 Grok / XAI API key name
- **Where:** `utils/grok_sentiment.py` line 30 uses `os.getenv("XAI_API_KEY")`. PROJECT_CONTEXT.md and .env example use `GROK_API_KEY`.
- **Effect:** With only `GROK_API_KEY` set, sentiment is skipped ("no API key").
- **Fix:** Use `os.getenv("GROK_API_KEY")` or `os.getenv("XAI_API_KEY")` and document the single name (e.g. support both: `os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")`).

---

## 3. DATA PATHS AND SCHEMAS

### 3.1 Positions file path
- **Orchestrator:** `POSITIONS_FILE = DATA_DIR / "positions.json"` with `DATA_DIR = Path("data")` (project-root relative).
- **exit_monitor:** `positions_file = 'data/positions.json'` (string, relative to cwd).
- **sync_alpaca:** `open('data/positions.json', 'w')` (relative to cwd).
- **dashboard/app.py:** `DATA_DIR = Path('../data')` for decisions/risk; positions loaded from **absolute** `Path('/home/ubuntu/trading-bot/data/positions.json')`.
- **Effect:** If scripts are run from a different cwd (e.g. `dashboard/` or `agents/`), `data/positions.json` may not resolve to the same file. Dashboard is mixed (absolute for positions, relative for others).
- **Fix:** Prefer a single root (e.g. `Path(__file__).resolve().parent.parent / "data"` in scripts that need it), or always run from project root and document it.

### 3.2 Position schema
- **sync_alpaca.py** writes: `ticker`, `qty`, `entry_price`, `current_price`, `pnl`, `pnl_pct`, `entry_time`, `cost_basis`.
- **Orchestrator** adds positions with: `ticker`, `shares`, `entry_price`, `entry_date`, `order_id`, `sector`, `stop_loss_pct`, `take_profit_pct`, `auto_executed`.
- **exit_monitor** expects: `ticker`, `entry_price`, `qty` or `shares`, `entry_time` or `entry_date`.
- **Effect:** Mix of `qty` vs `shares` and `entry_time` vs `entry_date` is already handled in exit_monitor. Different keys from sync vs orchestrator are mostly compatible; ensure any consumer that expects `current_price` on the position (e.g. for display) knows it may be absent for orchestrator-added positions until next sync.

### 3.3 Dashboard relative paths
- **dashboard/app.py:** `DATA_DIR = Path('../data')`, `log_dir = Path('../logs')`. Depends on cwd; if app is run from project root, `../data` goes outside the project.
- **Fix:** Resolve paths from `app.py`’s directory, e.g. `Path(__file__).resolve().parent.parent / "data"`.

---

## 4. DEAD / REDUNDANT CODE AND IMPORTS

### 4.1 run_strategies.py still imports smart_money_trader
- **Where:** `run_strategies.py` line 8: `from agents.smart_money_trader import smart_money_strategy`.
- **Issue:** Smart Money strategy is commented out (lines 38–43), but the import runs at load time. If that module has the pandas bug (e.g. lines 125–128), importing `run_strategies` can crash.
- **Fix:** Remove the import (and the commented block) until the bug is fixed, or guard with try/except and document.

### 4.2 exit_monitor.py duplicate `monitor_positions`
- **Where:** First at ~27–76, second at ~175–224. There is also an orphaned docstring (~77–84) between the first and `check_option_exit`.
- **Effect:** Second definition wins; first is dead code. Confusing for maintenance.
- **Fix:** Delete the first `monitor_positions` and the orphaned docstring; keep a single definition.

### 4.3 bond_manager.py redundant and wrong env
- **Where:** Lines 16–17: `api_key = os.getenv("APCA_API_KEY_ID")`, `secret_key = os.getenv("APCA_API_SECRET_KEY")` at module level; never used. `get_client()` uses `ALPACA_*`.
- **Where:** Lines 51–56: multiple `client = get_client()` in `get_current_bond_position()` (redundant).
- **Fix:** Remove module-level APCA_* and extra `get_client()` calls.

---

## 5. FORTRESS ORCHESTRATOR / BOND MANAGER

- **fortress_orchestrator:** Uses `APCA_*` for Alpaca; calls `bond_manager.get_market_regime`, `vix_insurance`, `commodity_trader`, etc. With ALPACA_* only, `get_portfolio_status()` fails.
- **bond_manager.get_client()** uses `ALPACA_*` and `paper=True`; fortress_orchestrator does not pass `paper=True` when creating `TradingClient` (Alpaca SDK may default to paper if base URL is paper).
- **Documentation:** PROJECT_CONTEXT says "Fortress Orchestrator disabled (bond_manager.py line 20 - client at module level)". The more accurate blocker is fortress_orchestrator using `APCA_*` and thus failing when only `ALPACA_*` is set.

---

## 6. EXIT MONITOR VS ORCHESTRATOR EXECUTION

- **Orchestrator flow:** `monitor_positions()` → `load_positions()` (orchestrator) → `monitor_exit_conditions()` (exit_monitor) → for each SELL signal, orchestrator calls `execute_sell_order()` (Alpaca) and updates `positions.json`.
- **Standalone exit_monitor (`__main__`):** Uses its own `load_positions()` and `execute_market_sell()`. `execute_market_sell()` only logs and sends SMS; it does **not** submit sell orders to Alpaca.
- **Effect:** If cron runs `agents/exit_monitor.py` directly instead of `orchestrator.py monitor`, exits would be logged but not executed. PROJECT_CONTEXT says "Position monitor (exits)" – ensure cron invokes `orchestrator.py monitor`, not the agent script directly.

---

## 7. MAIN.PY VS ORCHESTRATOR SCREENING

- **main.py:** Calls `run_screener()` and expects a list of dicts with `ticker`, `drop_pct`, `rsi`, `volume_ratio`, `news`, `analysis`. It prints `result['analysis']` (may be dict; printing is still valid). Screener return shape matches.
- **entry_agent.evaluate_entry()** expects `candidate['current_price']`. If entry_agent is ever called with raw screener output (no current_price), it will KeyError. Currently the only entry evaluation path is inside orchestrator after screener; orchestrator does not add current_price before any entry step that might use it, and the main screening path goes to auto-execution which we already flagged for missing current_price. So fixing screener to add current_price aligns both auto-execution and any future entry_agent use.

---

## 8. DOCUMENTATION / HELP

- **orchestrator.py:** Duplicate help line for `snipe` (lines 1471–1472). Remove one.

---

## 9. SUMMARY TABLE

| Category              | Severity   | Item                                              |
|-----------------------|-----------|----------------------------------------------------|
| Auto-execution        | Critical  | Screener does not set `current_price` → all skipped |
| Orchestrator          | Critical  | `results[2]` IndexError in fundamental handling   |
| Orchestrator          | Critical  | Duplicate `run_fortress()` + recursive call on error |
| Env / API             | High      | APCA_* vs ALPACA_* (fortress, bond_manager, vix)   |
| Env / API             | High      | GROK_API_KEY vs XAI_API_KEY in grok_sentiment      |
| Paths                 | Medium    | Dashboard and exit_monitor relative vs absolute    |
| Dead code             | Low       | run_strategies imports smart_money_trader          |
| Dead code             | Low       | exit_monitor duplicate monitor_positions           |
| bond_manager          | Low       | Unused APCA_* at module level, duplicate get_client |
| Cron                  | Verify    | Position monitor must run orchestrator.py monitor  |

---

**Recommended order of fixes:**  
1) Add `current_price` to screener candidates.  
2) Fix `results[2]` → `results[1]` in orchestrator.  
3) Remove duplicate `run_fortress()` and recursive call.  
4) Unify Alpaca env vars to ALPACA_* (and optionally support both).  
5) Unify or document Grok/XAI key name.  
6) Clean up dead/duplicate code and paths as above.

---

## FIXES APPLIED (March 1, 2026)

All critical bugs and most medium/low issues have been fixed:

- ✅ Screener adds `current_price` to candidates
- ✅ Orchestrator `results[2]` → `results[1]` for fundamental analysis
- ✅ Duplicate `run_fortress()` removed, recursion fixed
- ✅ fortress_orchestrator, vix_insurance, bond_manager: ALPACA_* only, dead code removed
- ✅ grok_sentiment: supports both GROK_API_KEY and XAI_API_KEY
- ✅ run_strategies: smartmoney handler added (graceful "disabled"), import removed
- ✅ exit_monitor: duplicate monitor_positions removed, project-root paths, cwd handling
- ✅ sync_alpaca: project-root paths for .env and positions.json
- ✅ dashboard/app.py, fortress_app.py: robust Path-based data/log dirs

**Cron note:** The fortress job at `0 0 * * 0` uses `python` (not full venv path). Consider updating to `/home/ubuntu/trading-bot/venv/bin/python` for consistency.
