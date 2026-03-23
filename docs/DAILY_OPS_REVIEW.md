# Daily ops review (pre–go-live discipline)

Goal: every day you (and Cursor) can review **the same facts** the bot produced — without SSH paste marathons — before you harden Lane 1 and ship to customers.

## 0. Autonomous daily loop (minimal manual tracking)

You do **not** need a personal trading diary. Let the VM build the snapshot; you only **pull + chat with Cursor** after hours.

| Step | Where | What |
|------|--------|------|
| **A. Schedule** | **Oracle** | Cron runs `generate_daily_ops_report.py` once per day after the session you care about (see `reports/ops_daily/README.md` for an example line). |
| **B. Pull** | **Mac** | When you’re ready to review (evening): `./scripts/sync_pull_from_oracle.sh ubuntu@YOUR_HOST` — brings `reports/ops_daily/LATEST.md` + `LATEST.json`. |
| **C. Review** | **Cursor** | Open or attach **`reports/ops_daily/LATEST.md`** (and optionally `LATEST.json`) and ask the AI to summarize PnL, errors, and risk flags. |
| **D. Truth check** | **Alpaca** | Still glance at **Paper** P&amp;L in the broker UI for the same day — reports are from bot files; broker is source of truth for money. |

The generator always refreshes **`LATEST.md` / `LATEST.json`** to match the latest dated `YYYY-MM-DD.*` run so you never hunt for filenames.

## 1. On Oracle (once per day or via cron)

```bash
cd /home/ubuntu/trading-bot
./venv/bin/python3 scripts/generate_daily_ops_report.py
```

This writes:

- `reports/ops_daily/YYYY-MM-DD.json` — machine-readable bundle  
- `reports/ops_daily/YYYY-MM-DD.md` — human-readable summary  

Data sources (read-only): `data/pnl_ledger.jsonl`, `data/last_screening_meta.json`, tails of `logs/orchestrator.log` and common dashboard/fortress logs.

## 2. Pull to your Mac (Cursor workspace)

```bash
cd ~/Downloads/trading-bot   # your path
./scripts/sync_pull_from_oracle.sh ubuntu@YOUR_ORACLE_IP
```

`sync_pull_from_oracle.sh` **does not rsync `data/`**, but it **does** sync `reports/`, so the daily files appear locally.

## 3. Review with Cursor / AI

1. Open `reports/ops_daily/LATEST.md` (or today’s `.md`).  
2. Optionally attach `reports/ops_daily/LATEST.json` for structured questions.  
3. Ask concrete questions, e.g.  
   - “Summarize realized PnL and last screening strict_mode.”  
   - “Any errors in log tails?”  
   - “Does ledger by_day match what I expect for this week?”

**Do not** paste API keys. Reports should not contain `.env` secrets; still treat **tickers + PnL + order IDs** as sensitive for public sharing.

## 4. Cross-check (source of truth)

Command Center and the ledger are **app views**. For money at risk, always reconcile with **Alpaca** (paper or live) for the same dates.

## 5. Optional: `stdout` only

```bash
./venv/bin/python3 scripts/generate_daily_ops_report.py --stdout-json | head -c 20000
```

Useful for a quick pipe without writing files (e.g. debugging).

## Related docs

- `docs/LANE1_OPERATOR_CHECKLIST.md` — deploy + tier sanity  
- `docs/SUPPORT_PLAYBOOK.md` — P&L / cron / dashboard quirks  
- `docs/SYNC_ORACLE_SOURCE_OF_TRUTH.md` — pull safety (no `.git` wipe)  
