# Operator excellence — Fortress differentiator

This stack combines **three layers** that most retail bots omit:

## A — Operator UX / trust

| Artifact | Purpose |
|----------|---------|
| **`data/operational_runs.jsonl`** | Append-only **canonical screening runs** with `run_id`, terminal state, counts, and **release context** (`DEPLOY_COMMIT`, `git` head). |
| **`GET /api/operator_runs`** | Merged rows for the Command Center **Operator Run Registry** panel. |
| **`utils/market_calendar.py`** | NYSE **full-day closures** + RTH — powers accurate “after hours / holiday” messaging in the trust ledger. |
| **Trust ledger enrichment** | `screening_started` lines show **finished / failed / after-hours / stale** instead of implying “still running”. |

## B — Risk / compliance posture

| Control | Purpose |
|---------|---------|
| **`utils/pre_trade_gate.py`** | **Single choke point** before every Alpaca `submit_order` (stocks + options). |
| **`FORTRESS_TRADING_HALT=1`** | Hard stop — blocks all submissions, logs `pre_trade_gate_blocked` to trust ledger. |
| **`data/operator_trading_halt.json`** | **File kill switch** — same pre-trade block as env halt; toggled from **Safety** panel or `POST /api/operator/halt`. |
| **`FORTRESS_ALERT_WEBHOOK_URL`** | Optional Slack-style webhook — alert on halt on/off. |
| **`FORTRESS_DASHBOARD_USER` / `FORTRESS_DASHBOARD_PASS`** | Optional **HTTP Basic** on Command Center (health, setup, `/proof`, `/manifest.json` stay public). |
| **`/manifest.json` + PWA meta** | Installable / mobile-friendly shell for the dashboard. |
| **`GET /api/chart_bars`** | Daily OHLCV (yfinance) for the in-UI chart. |
| **`GET /api/backtest?refresh=1`** | Refreshes **`data/backtest_snapshot.json`** (illustrative SMA crossover); shown in **Trust report**. |
| **`GET /api/operator_brief`** | **Morning Brief** on the dashboard: session, macro (SPX/VIX/Nasdaq), rotating **policy/ops tip**, stack checklist, **book-aware** rows (`positions.json` + optional **Alpaca** open symbols). |
| **`POST /api/hooks/tradingview`** | **TradingView** (and similar) **alert webhook** → append-only **`data/tradingview_signal_queue.jsonl`** + **dashboard queue** panel. Optional **`FORTRESS_TV_WEBHOOK_SECRET`**. **Not auto-trade.** |
| **`config/policy_templates/`** + **`scripts/install_policy_template.py`** | Install **`operator_conservative`**, **`operator_balanced_kit`**, **`tv_signal_sleeve`** into `policy_profiles.json`. |
| **`docs/TRADINGVIEW_WEBHOOK_SETUP.md`** | Step-by-step TV URL + message format; **print → Save as PDF** for a portable guide. |
| **`chain_prev_sha256` on trust ledger lines** | Light **tamper-evidence** chain over append-only JSONL. |
| **`scripts/export_audit_bundle.py`** | ZIP ledger + runs + halt + backtest snapshot + SHA-256 manifest (optional S3 upload). |
| **`FORTRESS_MAX_ORDER_NOTIONAL_USD`** | Per-order estimated notional cap (stocks). |
| **`FORTRESS_LIVE_TRADING_ACK=I_ACCEPT_LIVE_RISK`** | Required if `ALPACA_BASE_URL` is **not** paper — prevents accidental live endpoints. |

## C — Research rigor

| Surface | Purpose |
|---------|---------|
| **`get_research_verdict()`** | Walk-forward headline: **stable / unstable / insufficient_data** with operator copy. |
| **Trust report panel** | Shows **Research verdict** next to drift / rollback / release. |
| **`smoke_alpaca_paper_trade_cancel.py`** | Proves **paper** path: limit order + cancel with **pre-trade gate** green. |

---

## Operator runbooks

Step-by-step modes (autonomous vs human-in-the-loop), cron mapping, and daily loop: **`docs/OPERATOR_RUNBOOKS.md`**.

## Verify

```bash
./scripts/verify_install.sh --quick   # import + registry + gate + trust-chain + morning-brief smokes
./scripts/verify_install.sh           # + e2e smoke + optional Alpaca cancel smoke (if keys set)
```

## Sync (Oracle)

```bash
./deploy_to_oracle.sh ... --service fortress-dashboard
```

---

**Differentiator in one line:** *Append-only run truth + calendar-aware trust copy + mandatory pre-trade gate + walk-forward verdict in the same operator console as your agents.*
