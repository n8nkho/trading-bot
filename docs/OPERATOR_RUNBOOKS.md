# Operator runbooks — Fortress

**Command Center** (`/` on the dashboard) is the primary operator console: health, **Performance & trading snapshot**, screening, safety, trust ledger, and **One-click runbooks** (API: `GET /api/runbooks`).

Print or PDF this file from your browser if you need an offline checklist.

---

## 1) First boot (any environment)

1. Copy env: `cp .env.example .env` and set **Alpaca paper** keys + URL.
2. Install: `./scripts/install.sh` then `./scripts/verify_install.sh`.
3. Start dashboard: `./scripts/restart_dashboard.sh` or systemd (`deploy/systemd/README.md`).
4. Open Command Center; complete **Setup** if prompted.
5. Optional: `FORTRESS_DASHBOARD_USER` / `FORTRESS_DASHBOARD_PASS` for HTTP Basic on the console.

---

## 2) Two execution products (autonomous vs human-in-the-loop)

Both use the **same codebase**. The difference is **when approved *entry* trades hit the broker**.

| Mode | `FORTRESS_EXECUTION_MODE` | Behavior |
|------|---------------------------|----------|
| **Autonomous** | `autonomous` (default) | After screening / sniper risk checks, **orders submit** (subject to pre-trade gate + halt). |
| **Human-in-the-loop** | `human_in_loop` (aliases: `hitl`, `manual`, `manual_approval`) | Approved entries are **queued** in `data/pending_execution_queue.json`. You **review**, then run **`python3 orchestrator.py execute_pending`** once to submit. |

**Notes:**

- **Exit monitor** (`python3 orchestrator.py monitor`) still runs **autonomous** exits/stops in both modes unless you use **trading halt** — HITL only defers **new buys** from daily screening and intraday sniper.
- **Pre-trade gate** and **file/env halt** apply on `execute_pending` too.
- After `execute_pending`, the queue file is **cleared**; check logs and trust ledger for partial failures.

---

## 3) Daily operator loop (paper or live)

1. **Morning:** Command Center → **Operator Morning Brief**; confirm **Safety** / halt off (unless intentional).
2. **Screen:** `python3 orchestrator.py screen` (or cron with `run_strategies.py screen --execute`).
3. **HITL only:** Inspect `data/pending_execution_queue.json` → then `python3 orchestrator.py execute_pending`.
4. **Monitor:** `python3 orchestrator.py monitor` (exits / risk).
5. **Hedges (optional cadence):** `python3 orchestrator.py fortress`.
6. **Evidence:** `python3 scripts/export_audit_bundle.py` before material releases.

---

## 4) Legacy cron: `run_strategies.py`

Oracle / older crons may call `python3 run_strategies.py <label>` **without** `--execute` (no-op, exit 0).

To **actually run** the wired workflow:

```bash
python3 run_strategies.py inefficiency --execute   # → orchestrator screen
python3 run_strategies.py momentum --execute       # → orchestrator snipe
```

See table in `run_strategies.py` docstring for label → command mapping.

---

## 5) Performance & analytics

- **Canonical UI:** Command Center → **Performance & trading snapshot** (anchor `#performance-panel`).
- **Legacy URL:** `GET /performance` **redirects** to Command Center with that anchor.
- Per-strategy realized stats appear when **pnl ledger / sell decisions** have data.

---

## 6) Live trading (extra discipline)

1. Confirm `ALPACA_BASE_URL` is **not** paper only if you intentionally go live.
2. Set `FORTRESS_LIVE_TRADING_ACK=I_ACCEPT_LIVE_RISK` (required by pre-trade gate for non-paper).
3. Test **halt** (`POST /api/operator/halt` or Safety panel) and confirm **no** orders pass.
4. Run **paper** `execute_pending` / `screen` dry runs before enabling live.

---

## 7) Quick reference commands

| Goal | Command |
|------|---------|
| Daily screen | `python3 orchestrator.py screen` |
| Ops AutoFix (safe dry-run) | `python3 orchestrator.py ops_autofix --dry-run` |
| Ops AutoFix (apply) | `python3 orchestrator.py ops_autofix` |
| Install Ops AutoFix cron | `bash scripts/install_ops_autofix_cron.sh --dry-run` (or `--apply`) |
| Submit HITL queue | `python3 orchestrator.py execute_pending` |
| Exits | `python3 orchestrator.py monitor` |
| Hedges | `python3 orchestrator.py fort`… `fortress` |
| Health | `python3 check_health.py` |
| Verify install | `./scripts/verify_install.sh` |

---

## Related docs

- `docs/OPERATOR_EXCELLENCE.md` — trust / compliance surfaces
- `docs/TRADINGVIEW_WEBHOOK_SETUP.md` — signal ingest (not auto-trade)
- `docs/INSTALL.md` — VM / systemd install
