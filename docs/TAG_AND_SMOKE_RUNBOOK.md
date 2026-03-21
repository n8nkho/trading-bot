# Tag v1.0.3 + run smokes (operator copy/paste)

**Order:** (1) Deploy so Oracle matches the commit you want to ship → (2) Run smokes **on Oracle** → (3) Tag **on Mac** (or any machine with Git + clean tree) → (4) Push tag if you use GitHub/GitLab.

`VERSION` in the repo should read **`1.0.3`** before you tag.

---

## Part A — On Oracle (SSH)

```bash
cd ~/trading-bot
source venv/bin/activate
set -e

# --- Fast / no live broker required ---
python3 smoke_deploy_import_gate.py
python3 smoke_pre_trade_gate.py
python3 smoke_trust_ledger_chain.py
python3 smoke_operator_morning_brief.py
python3 smoke_operator_run_registry.py
python3 smoke_tradingview_webhook.py
python3 smoke_risk_state_persistence.py
python3 smoke_order_filled_gate.py
python3 smoke_exit_monitor_option_chain_cache.py
```

**Alpaca paper (needs real keys in `.env`):** skips with exit 0 if keys missing.

```bash
python3 smoke_alpaca_paper_trade_cancel.py
```

**Heavy E2E (network, yfinance, long):** skip live screener to save time:

```bash
SMOKE_SKIP_LIVE_SCREENER=1 python3 smoke_test_end_to_end.py
```

If any command prints `[FAIL]` or exits non-zero, **fix before tagging**.

---

## Part B — On your Mac (in the repo)

**1. Confirm clean tree and version**

```bash
cd ~/Downloads/trading-bot
git status
cat VERSION
```

You want **`nothing to commit, working tree clean`** and **`1.0.3`**.

**2. Same commit as Oracle (optional check)**

Your deploy already synced Mac → Oracle. Optionally on Oracle: `cd ~/trading-bot && git rev-parse HEAD` and on Mac: `git rev-parse HEAD` — they match only if Oracle has a full Git clone; if not, rely on “just deployed” timing.

**3. Create the annotated tag**

```bash
git tag -a v1.0.3 -m "Release v1.0.3: licensing gates, universe cap, Stripe webhook"
```

**4. Show the tag**

```bash
git show v1.0.3 --stat
```

**5. Push the tag** (only if `origin` exists)

```bash
git push origin master
git push origin v1.0.3
```

If you have **no remote**, the tag still exists **locally** — zip from this folder at this commit for customers.

---

## Part C — Customer install pointer

Give buyers **`v1.0.3`**:

```bash
git checkout v1.0.3
```

See **`docs/INSTALL_LOCAL.md`**.
