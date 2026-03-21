# Distribution: three lanes

Use this doc so you always know **which lane** you are in.

**Follow the numbered checklist:** `docs/STEP_BY_STEP_LANES.md` Each lane has different **source of truth**, **secrets**, and **license** expectations.

| Lane | Who | Where code runs | Git / files of record | License (`FORTRESS_LICENSE_*`) |
|------|-----|-----------------|------------------------|--------------------------------|
| **1 — Personal** | You | **Bot + cron run on Oracle only**; **Mac** = default **Oracle → Mac** sync for Cursor | **Oracle** = edit, run, commit. **Default sync:** `scripts/sync_pull_from_oracle.sh` (Oracle → Mac). See `docs/SYNC_ORACLE_SOURCE_OF_TRUTH.md` | **`master`** in `.env` on **Oracle**. Mac `.env` only matters if you run code locally on the Mac. |
| **2 — Customer laptop** | Paying user | Their PC / Mac | **Tagged release** (e.g. `v1.0.0`) — zip or `git checkout` that tag | **`starter` / `pro` / `enterprise`** from purchase, or `license.json`. Never ship `master` to unpaid tiers. |
| **3 — Customer OCI** | Paying user (optional cloud) | Their Oracle VM / VPS | Same **tag** as lane 2 + `deploy_to_oracle.sh` / systemd docs | Same as lane 2 — tier per subscription, not `master`. |

---

## Step-by-step: what to do in which lane

### A. Daily work (you only) → **Lane 1**

1. **Run the personal bot on Oracle** (cron/systemd already target the VM — keep it that way).
2. SSH to Oracle; edit and commit in `~/trading-bot`.
3. On Mac (**default**): `./scripts/sync_pull_from_oracle.sh ubuntu@YOUR_IP` so your local folder matches Oracle (Cursor mirror).
4. Set in `.env` on **Oracle**: `FORTRESS_LICENSE_TIER=master` (see `.env.example`). Do not rely on the Mac for production runtime.

### B. Cut a version customers install → **Lanes 2 & 3**

1. On a clean tree (usually Oracle), run tests / smoke you care about.
2. Update `VERSION` and `CHANGELOG.md`.
3. Tag: `git tag -a v1.0.0 -m "Commercial baseline"` and push (if you use a remote).
4. Build **customer artifact** from that tag only (no `venv/`, `data/`, `.env`).
5. Document install: `README.md` + `docs/INSTALL_LOCAL.md` (local) and optional `deploy_to_oracle.sh` (OCI).

### C. Enforcing tiers in product → **Lanes 2 & 3** (behavior); **Lane 1** (you still use `master`)

- `config/license.py` + `config/tiers.py` implement plan resolution and limits.
- **You** keep `FORTRESS_LICENSE_TIER=master` so nothing is artificially limited.
- **Customers** get `starter`/`pro`/`enterprise` or a `license.json` from billing later.

### D. After “freeze for monetization”

- **Bugfixes** for sold version: `release/x.y` branch + patch tags.
- **New features**: `main` (or `develop`) → future tags `v1.1.0`, `v2.0.0`. Do not silently change the tree customers pinned to an old tag.

---

## Quick reference

| Question | Answer |
|----------|--------|
| Where do I commit today? | **Lane 1** → Oracle. |
| Where do I sync Mac from? | **Lane 1** → `sync_pull_from_oracle.sh` (safe default, no `--delete`). |
| What do customers download? | **Lane 2** (and 3) → **Named git tag** or release zip from that tag. |
| What tier is full internal access? | **Lane 1** → `master`. |

See also: `docs/SYNC_ORACLE_SOURCE_OF_TRUTH.md`, `deploy_to_oracle.sh`, `config/pricing_gates.json`.
