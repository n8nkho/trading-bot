# Fortress Add-Ons (Customer Extensions)

You may extend the bot **only** through the add-on API. Do not modify core files in `agents/`, `orchestrator.py`, `config/` (except allowed config files), or other delivered code.

## How add-ons work

1. Create a directory `customer_addons/` in the project root (if it does not exist).
2. Add one or more Python files (e.g. `my_hooks.py`). Do not use names starting with `_`.
3. Each module can define a **`register(env)`** function. The loader passes an `env` object with which you subscribe to hooks.

## Available hooks

- **`env.on_screen_done(fn)`**  
  Your function `fn(candidates: list)` is called after daily screening. You cannot change the candidates; use this to log, notify, or send to an external system.

- **`env.on_before_trade(fn)`**  
  Your function `fn(decision: dict) -> dict | None` is called before a trade is submitted. Return a modified decision dict to alter the trade (e.g. adjust size within your limits), or `None` to leave it as-is. The next add-on receives the updated decision.

- **`env.on_after_trade(fn)`**  
  Your function `fn(decision: dict, outcome: str)` is called after a trade is logged. Use for analytics or alerts.

## Example

```python
# customer_addons/my_hooks.py
def register(env):
    def after_screen(candidates):
        print(f"Screening complete: {len(candidates)} candidates")
    env.on_screen_done(after_screen)

    def before_trade(decision):
        # Optional: cap size for your risk
        if decision.get("position_size", 0) > 1000:
            decision = dict(decision)
            decision["position_size"] = 1000
            decision["shares"] = int(1000 / decision.get("entry_price", 1))
        return decision
    env.on_before_trade(before_trade)
```

## Allowed configuration (no code change)

- **`data/customer_settings.json`** – Bounded risk parameters (position size min/max, stop loss %, max trades per day, etc.). Allowed ranges are enforced; you cannot exceed them. See `data/customer_settings.json.example`.
- **`.env`** – Your API keys and environment variables (never commit these).
- **`config/watchlist.json`** – Your watchlist (within tier limits).

## Where hooks run (core)

- **on_screen_done** – Called at the end of the daily screening workflow (orchestrator), with the candidates list (read-only).
- **on_before_trade** – Called for each approved trade before the order is sent to the broker; your returned dict is used for that execution.
- **on_after_trade** – Called (1) after the decision is logged (`outcome="logged"`) and (2) after the order is executed successfully (`outcome="executed"`).

## What you must not do

- Edit any file under `agents/`, `config/*.py`, `orchestrator.py`, `run_strategies.py`, `backtest/`, or other core modules.
- Remove or bypass license checks, integrity checks, or tier gates.
- Redistribute or copy the core software.

Violations may result in loss of support and license termination.
