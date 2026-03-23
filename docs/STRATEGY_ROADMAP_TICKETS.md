# Strategy roadmap — actionable tickets + ship workflow

This document turns **capital-first / consistency-first** objectives into **trackable engineering tickets**, with a **repeatable workflow**: **test → paper trade/cancel → commit → sync Mac**.

**Not investment advice.** Targets here are **design goals**, not promises of returns.

---

## A. North-star (what we are building toward)

- **Hard risk stops:** daily equity halt (~**−1%** configurable), optional **peak-to-trough** halt (**−3–5%** from rolling peak).
- **Sizing:** risk **≤1–2% of equity per trade** measured **at stop** (not only notional %).
- **Stops:** every trade has stop + take-profit; **ATR-aware** widening/tightening where configured.
- **Behavior after loss:** **cooldown** after stop; **circuit / streak** logic that counts **meaningful events** (not one burst of ledger lines).
- **Regime:** **risk-off** → **no new long risk** or **reduced size** (config + policy profile).
- **Execution honesty:** no claim of **cross-exchange arb** or **classic market making** until those systems exist.

**Out of scope for Phase 1 tickets:** true multi-exchange arb, professional MM, full grid engine (backlog only).

---

## B. Ship workflow (every meaningful change)

Use this **every time** you implement a ticket (or group of small tickets).

### B1 — On Mac (or your dev machine), before commit

```bash
cd ~/Downloads/trading-bot   # your path
source venv/bin/activate 2>/dev/null || true

# Fast gates (no broker required for most)
python3 smoke_deploy_import_gate.py
python3 smoke_pre_trade_gate.py
python3 smoke_risk_state_persistence.py
```

### B2 — Alpaca paper: place + cancel (proves keys + trading client)

Requires **`ALPACA_*`** in `.env` and **paper** URL.

```bash
python3 smoke_alpaca_paper_trade_cancel.py
```

Expect **`[OK]`** / exit **0**. If skip (no keys), run on **Oracle** where `.env` is complete.

### B3 — Commit (+ push if you use GitHub)

```bash
git add -A
git status
git commit -m "feat(risk): <ticket id> short description"
git push origin master:main
```

**Do not** put `# comments` on the same line as `git push` (zsh/git refspec issues).

### B4 — Deploy to Oracle (Lane 1 production bot)

```bash
./deploy_to_oracle.sh --host YOUR_ORACLE_IP --user ubuntu \
  --remote-dir /home/ubuntu/trading-bot \
  --venv /home/ubuntu/trading-bot/venv \
  --service fortress-dashboard
```

### B5 — Re-run smokes on Oracle (recommended)

```bash
ssh ubuntu@YOUR_ORACLE_IP
cd ~/trading-bot && source venv/bin/activate
python3 smoke_deploy_import_gate.py
python3 smoke_alpaca_paper_trade_cancel.py
```

### B6 — Sync Oracle → Mac (Cursor mirror)

On **Mac**:

```bash
./scripts/sync_pull_from_oracle.sh ubuntu@YOUR_ORACLE_IP
```

This **does not** pull `data/` or `.env` — only code + `reports/ops_daily/` exports. See `docs/SYNC_ORACLE_SOURCE_OF_TRUTH.md`.

### B7 — Optional heavy E2E (before tag / major release)

```bash
SMOKE_SKIP_LIVE_SCREENER=1 python3 smoke_test_end_to_end.py
```

Full tag discipline: `docs/TAG_AND_SMOKE_RUNBOOK.md`.

---

## C. Actionable tickets

### Phase 1 — Risk & behavior (highest leverage)

| ID | Title | Priority | Effort | Owner module(s) | Acceptance criteria |
|----|--------|----------|--------|----------------|---------------------|
| **T1** | **Daily equity halt (−1% configurable)** | P0 | M | `agents/risk_guardian.py`, `orchestrator.py`, pre-new-risk call sites | Read **session/day start equity** (Alpaca account or persisted); if **realized+unrealized today ≤ −1%** (config), **block new entries** and optionally **flatten** per policy; dashboard shows **halt reason**; unit/smoke or dry-run test. |
| **T2** | **Peak drawdown halt (−3–5% from peak)** | P0 | M | New small `utils/equity_peak_tracker.py` + risk checks | Persist **rolling peak equity**; if **current ≤ peak × (1 − X%)**, **halt new risk**; configurable **X**; survives restart (JSON under `data/`). |
| **T3** | **Consecutive losses = round-trips, not raw ledger lines** | P0 | S–M | `agents/risk_guardian.py`, `orchestrator.py` (`update_consecutive_losses`) | One **closed trade** (or one **position fully closed**) increments streak by **at most 1**; batch of partials same second does **not** spike streak to 5; existing smoke extended or new `smoke_consecutive_loss_semantics.py`. |
| **T4** | **Cooldown after stop-loss** | P1 | S | `data/cooldown_state.json` + entry gates | On exit with reason **STOP_LOSS** (or equivalent), set **no new entries until T+Δ**; configurable Δ; logged + visible in `/api/performance` or health. |
| **T5** | **ATR-aware stop width** | P1 | M | `agents/entry_agent.py`, exit/monitor, `config/` | Stop distance **scales with ATR** (bounds min/max %); **paper** test on one symbol documented in ticket notes. |
| **T6** | **Risk-based sizing (1–2% at stop)** | P1 | M | `agents/entry_agent.py`, `risk_guardian` | Position qty so **loss if stop hits ≈ 1–2% equity** (within slippage tolerance); max caps still apply. |
| **T7** | **Risk-off regime: block or reduce new longs** | P1 | M | `orchestrator.py` screening, `config/policy_profiles.json` | When Fortress/regime = **RISK_OFF** (or VIX > threshold), **skip new long entries** or **cut size**; config flags; one integration test or documented manual run. |
| **T8** | **Options entry failure policy** | P1 | S–M | Screening → entry pipeline | If **“No suitable option”** for all candidates: either **stock-only fallback** (if enabled) or **explicit no-trade** with ledger/trust event — **no silent asymmetry** vs exits. |

### Phase 2 — Observability & honesty

| ID | Title | Priority | Effort | Acceptance criteria |
|----|--------|----------|--------|---------------------|
| **T9** | **Dashboard: risk halt + cooldown + peak DD flags** | P2 | S | `/api/performance` or `/api/safety_status` exposes **daily_halt_active**, **cooldown_until**, **peak_dd_breached** |
| **T10** | **Customer-facing claims audit** | P2 | S | `docs/DISTRIBUTION.md` + `/proof` copy: **no** “arb / zero loss / guaranteed daily %” unless feature exists; link to this roadmap |

### Phase 3 — Backlog (explicitly not Phase 1)

| ID | Title | Notes |
|----|--------|--------|
| **B1** | Grid trading module | New engine; not Alpaca MM. |
| **B2** | True multi-venue arb | New integrations + latency + capital. |
| **B3** | Market making | Rebates, inventory, quoting loop — major build. |
| **B4** | DCA scheduler | Simple cron + fixed notional; optional product. |

---

## D. Suggested implementation order

1. **T3** (streak semantics) — reduces false **strict_mode** / circuit trips.  
2. **T1** + **T2** (daily + peak DD) — matches your **“stop the spiral”** objective.  
3. **T4** (cooldown) — complements T1/T2.  
4. **T6** + **T5** (sizing + ATR stops) — **per-trade** risk control.  
5. **T7** + **T8** (regime + options policy) — **fewer bad entries** in chop.  
6. **T9** + **T10** (visibility + marketing accuracy).

Each ticket should close with: **smokes green**, **`smoke_alpaca_paper_trade_cancel.py` green**, **commit**, **deploy**, **optional `sync_pull`**.

---

## E. Quick reference — commands

| Step | Command |
|------|---------|
| Import gate | `python3 smoke_deploy_import_gate.py` |
| Paper trade/cancel | `python3 smoke_alpaca_paper_trade_cancel.py` |
| Deploy | `./deploy_to_oracle.sh --host … --user ubuntu --remote-dir … --venv … --service fortress-dashboard` |
| Mac ← Oracle | `./scripts/sync_pull_from_oracle.sh ubuntu@HOST` |

---

## Related docs

- `docs/TAG_AND_SMOKE_RUNBOOK.md` — full smoke matrix + tagging  
- `docs/SYNC_ORACLE_SOURCE_OF_TRUTH.md` — who is source of truth  
- `docs/DAILY_OPS_REVIEW.md` — daily P&amp;L / log bundle for review  
- `docs/SUPPORT_PLAYBOOK.md` — positions / P&amp;L quirks  
