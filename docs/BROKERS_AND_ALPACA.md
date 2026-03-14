# Brokers: Alpaca vs Others

## Short answer

**No.** The bot does **not** work the same way with a different broker today. It is built and tested for **Alpaca** (paper and live) only. Order execution, account info, and position sync all use the Alpaca API. Using another broker (e.g. Interactive Brokers, TD Ameritrade, Schwab) would require code changes and testing.

---

## What is tied to Alpaca today

| Area | How Alpaca is used |
|------|--------------------|
| **Order execution** | `orchestrator.py`: `execute_buy_order()` and `execute_sell_order()` use Alpaca’s `TradingClient` and `MarketOrderRequest`. |
| **Account info** | `get_account_info()` (buying power, equity, position count) comes from `alpaca_client.get_account()` and `get_all_positions()`. |
| **Position sync** | `sync_alpaca.py` pulls positions from Alpaca and writes `data/positions.json`. Cron and the dashboard use this file. |
| **Setup wizard** | The first-run wizard asks for **Alpaca** API key and secret and tests the connection with the Alpaca API. |
| **Dashboard** | Command Center “Sync Alpaca” and “Orders” use the Alpaca API. |
| **Other agents** | `fortress_orchestrator`, `bond_manager`, `vix_insurance` use the Alpaca client for portfolio/orders. |

So: **account data**, **placing/cancelling orders**, and **position sync** all go through Alpaca. The rest of the bot (screening, exit logic, risk, etc.) reads from `data/positions.json` and does not care where that file came from, but **getting** that data and **executing** trades is Alpaca-specific.

---

## If you want to support another broker later

You’d add a **broker adapter** so the rest of the bot stays the same:

1. **Define a small interface** (e.g. in `clients/broker_base.py`):
   - `get_account_info() -> dict` (buying_power, equity, position_count, etc.)
   - `submit_buy(ticker, shares, approximate_price=None) -> dict` (order_id, success, error)
   - `submit_sell(ticker, shares) -> dict`
   - `get_positions() -> list[dict]` (ticker, qty, entry_price, etc.)
   - Optionally: `get_orders()`, `cancel_order()`

2. **Implement the interface once per broker:**
   - `clients/alpaca_client.py` – wrap current Alpaca `TradingClient` usage.
   - `clients/ibkr_client.py` (or similar) – implement the same interface for the other broker’s API.

3. **Choose broker at runtime** via config or env (e.g. `BROKER=alpaca` or `BROKER=ibkr`). The orchestrator, sync script, and dashboard call the adapter instead of Alpaca directly.

4. **Setup wizard** would need to ask which broker and which credentials (e.g. Alpaca key/secret vs IBKR username/password + optional API keys).

Until that adapter exists and is tested, the bot is **Alpaca-only**.

---

## What to tell customers

- **Today:** “Fortress works with **Alpaca** (paper and live). You need an Alpaca account and API keys. We don’t support other brokers yet.”
- **If they ask for another broker:** “Right now we only support Alpaca. Support for other brokers may be added later; we’d announce it.”

Keeping the product **Alpaca-only** is the simplest and safest: one broker to test, one set of docs, and Alpaca’s API is straightforward and free for paper trading.
