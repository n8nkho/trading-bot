# Lane 1 operator checklist (you + Oracle)

Use this after changes on your **Mac** or when onboarding a fresh VM. **Lane 1** = your personal bot runs on **Oracle**; Mac is mirror + Git.

---

## A. After you change code on the Mac

| Step | You run (on Mac, in repo folder) | What “good” looks like |
|------|-----------------------------------|-------------------------|
| A1 | `git add -A && git commit -m "short note"` | `git status` → clean |
| A2 | `./deploy_to_oracle.sh` *(your usual host/user flags — same as always)* | No rsync errors |
| A3 | *(Optional)* `git push` to GitHub/GitLab if you use a remote | Backup exists off the laptop |

Doc reference: `docs/SYNC_ORACLE_SOURCE_OF_TRUTH.md`.

---

## B. On Oracle (SSH as `ubuntu`)

| Step | You run | What “good” looks like |
|------|---------|-------------------------|
| B1 | `grep FORTRESS_LICENSE_TIER ~/trading-bot/.env` | Shows **`master`** for your live bot (not `starter`) |
| B2 | `ls ~/trading-bot/utils/license_gates.py` | File exists |
| B3 | `ls ~/trading-bot/utils/license_gates.py ~/trading-bot/config/tiers.py` | Both exist |

---

## C. One-time license / tier sanity check (Oracle)

**Only for testing** — then set `master` again.

```bash
cd ~/trading-bot
FORTRESS_LICENSE_TIER=starter python3 orchestrator.py fortress
```

- **Good:** JSON error on stderr, exit code **2**.
- **Bad:** Full Fortress report → code on VM is old; redeploy from Mac.

Restore:

```bash
# In .env on Oracle
FORTRESS_LICENSE_TIER=master
```

---

## D. Universe cap (Starter vs Pro)

Screener and intraday sniper respect **`config/tiers.py`** `max_universe_size` for your tier. **`master`** on Oracle = effectively unlimited.

After a screen run, optional:

```bash
cat ~/trading-bot/data/last_screening_meta.json | head -40
```

Look for **`universe_license_cap`**: `universe_truncated: true` means the watchlist was larger than your tier allows.

---

## E. Hardening + routine (B & D)

See **`docs/LANE1_HARDENING_AND_ROUTINE.md`** — deploy with **`--service fortress-dashboard`**, optional **`sudo reboot`**, **`git push`** rhythm.

---

## F. Daily rhythm (no Git crisis)

1. Work on **Oracle** when possible; commit there.  
2. **Oracle → Mac:** `./scripts/sync_pull_from_oracle.sh ubuntu@YOUR_IP` when you want Cursor up to date.  
3. After big edits on **Mac:** **A1 → A2** again.

---

## G. When you’re ready to sell (preview)

On **Oracle**, run the smoke/tests you trust → bump `VERSION` / `CHANGELOG.md` → `git tag` → that tag is **Lanes 2–3**. Details: `docs/STEP_BY_STEP_LANES.md` Phase 2.
