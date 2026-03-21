# Step-by-step: which lane am I in?

Use this as your default checklist. Keep **`docs/DISTRIBUTION.md`** open for the full table.

---

## Phase 0 — One-time setup (today)

| Step | What you do | Lane |
|------|-------------|------|
| 0.1 | Read `docs/DISTRIBUTION.md` | All (orientation) |
| 0.2 | On **Oracle**, add to `.env`: `FORTRESS_LICENSE_TIER=master` | **Lane 1** (personal) |
| 0.3 | **Personal bot stays on Oracle** (cron/systemd); Mac is mirror only. Mac `.env` / `master` only if you deliberately run Python on the Mac | **Lane 1** |
| 0.4 | Commit the new docs + `config/license.py` + `config/tiers.py` + `VERSION` on **Oracle** | **Lane 1** |

---

## Phase 1 — Your daily workflow

| Step | What you do | Lane |
|------|-------------|------|
| 1.1 | **Runtime:** orchestrator, dashboard, crons → **Oracle only** | **Lane 1** |
| 1.2 | Code, test, commit on **OCI** | **Lane 1** |
| 1.3 | **Default:** `./scripts/sync_pull_from_oracle.sh user@host` on Mac (Oracle → Mac) | **Lane 1** (mirror) |
| 1.4 | Never point customers at your Oracle `.env` or `master` tier | **Lanes 2–3** stay separate |

---

## Phase 2 — First commercial “frozen” release

| Step | What you do | Lane |
|------|-------------|------|
| 2.1 | Confirm smoke/tests on a **clean** tree (usually on Oracle) — **`docs/TAG_AND_SMOKE_RUNBOOK.md`** | **Lane 1** (prep) |
| 2.2 | Edit `VERSION` + `CHANGELOG.md` | **Lanes 2–3** artifact prep |
| 2.3 | `git tag -a v1.0.0 -m "Commercial baseline"` (version must match intent) | **Lanes 2–3** |
| 2.4 | Give customers **that tag** or a **zip built from that tag** | **Lane 2** (and **3** if they use OCI) |
| 2.5 | Customer `.env`: `FORTRESS_LICENSE_TIER=starter` (or pro/enterprise), **not** `master` | **Lanes 2–3** |
| 2.6 | Optional: customer `FORTRESS_LICENSE_PATH` → JSON like `docs/examples/license.example.json` | **Lanes 2–3** |

---

## Phase 3 — After freeze (upgrades only on new tags)

| Step | What you do | Lane |
|------|-------------|------|
| 3.1 | New features on `main` / `develop` → new tags `v1.1.0`, `v2.0.0` | **Lane 1** dev → **2–3** ship |
| 3.2 | Old tag `v1.0.0` only gets **patches** (security / license fixes) if you maintain a `release/1.0` branch | **Lanes 2–3** support |

---

## Quick “where am I?”

- **Typing on Oracle and committing?** → **Lane 1**
- **Packaging something for a buyer’s laptop?** → **Lane 2**
- **Same buyer wants it on their VM?** → **Lane 3** (same tier + same tag + deploy script)

---

## Next implementation steps (monetization)

These are still **mostly lanes 2–3** (enforcement); you verify on **lane 1** with `master` so nothing breaks for you.

1. ~~Wire **API routes / backtest / exports** to `config.tiers` via `utils/license_gates.py` (dashboard + CLI).~~ **Done in v1.0.1.**
2. ~~**Universe size caps** — screener + intraday sniper use `effective_max_universe_size()` / `apply_license_universe_cap()`; telemetry in `data/last_screening_meta.json` (`universe_license_cap`).~~ **Done in v1.0.2.**
3. **Stripe (done for webhooks)** — `POST /api/billing/stripe-webhook` + `utils/stripe_license_sync.py` + `docs/BILLING_STRIPE.md`. **You still do:** Stripe Dashboard products/prices, webhook URL, paste secrets into `.env`, `pip install stripe`, restart dashboard. **Paddle:** not implemented yet; same pattern possible later.

**Lane 1 execution steps (deploy, `.env`, tests):** `docs/LANE1_OPERATOR_CHECKLIST.md`

When you finish a phase, tick it in your own notes and move to the next row in this file.
