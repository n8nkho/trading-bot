# Support Playbook (Retail / Operator)

## Dashboard won’t load
- Confirm process: `python3 dashboard/command_center.py` (or systemd unit).
- Check port 8083 not in use; restart after deploy.

## New API route 404 but `grep` finds it in `command_center.py`
Usually a **stale** `python3 …/dashboard/command_center.py` (nohup/manual) still owns **8083** while systemd restarted a **different** process (or the unit failed to bind). **`curl` hits the old interpreter.**

1. `sudo ss -ltnp | grep 8083` or `sudo lsof -i :8083` — note PID / command line.
2. From repo root: **`sudo ./scripts/restart_dashboard_systemd.sh`** (kills port + stray `command_center.py`, then `systemctl restart fortress-dashboard`).
3. Re-test: `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8083/api/billing/proof_links_status` → **200**.

`./deploy_to_oracle.sh` with `--service fortress-dashboard` also frees **8083** before restart (same idea).

## Validation errors in System Health
- Run Pristine **Run** in UI or `python3 smoke_deploy_import_gate.py` on the server.
- Fix missing optional deps per error text.

## Stale screening / agents
- `crontab -l` — ensure `orchestrator.py screen`, `monitor`, `snipe`, `fortress` lines exist.
- Check `logs/cron_heartbeat.log` mtime.

## System health: Cron shows red
The Command Center scans the **process user’s** `crontab -l`, **`/var/spool/cron/crontabs/<repo-owner>`** (owner of the app directory — fixes **systemd running as `root`** while jobs are under **`ubuntu`**), plus **`/etc/crontab`** and **`/etc/cron.d/*`**. It looks for job text that mentions this repo’s **absolute path** (from the running app), `~/trading-bot`, `/trading-bot/`, or scripts like **`orchestrator.py`** / **`run_strategies.py`**.

- **Still red?** Your lines may use a **wrapper** with no path and no script name above. Add a unique substring to each line, or set in **systemd** / `.env` loaded by the dashboard:
  - `FORTRESS_CRON_MARKERS=my_wrapper.sh,run_daily` (comma-separated substrings that appear in cron).
- **Debug payload:** set `FORTRESS_CRON_DEBUG=1` in the environment for `fortress-dashboard`, restart, then open **`/api/health`** (alias: **`/api/system_health`**) and check **`cron_debug.aggregate_chars`**. If **`aggregate_chars` is 0**, nothing was read (permissions or no cron files).

## Command Center shows 0 positions but Alpaca has open positions
The UI **prefers live broker positions** from Alpaca (`/api/performance`, `/api/positions`). If Alpaca keys are missing or the API errors, it falls back to **`data/positions.json`** only.

- **Reconcile file to broker:** from repo root run `python3 sync_alpaca.py` (uses **`ALPACA_BASE_URL`** for paper vs live).
- **Mismatch hint:** when broker and file differ, JSON includes `positions_broker_file_mismatch` and `positions_mismatch_hint`.

## P&L mismatch
- Confirm `data/pnl_ledger.jsonl` updates after sells; monitor reconciliation logs.

## Policy rollback stuck
- Inspect `data/policy_rollback_state.json`.
- Clear via `POST /api/policy/clear_rollback` when appropriate.

## Escalation
- Capture: latest `/api/trust_report`, `logs/orchestrator.log` tail, Alpaca order IDs.
