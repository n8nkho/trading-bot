# Oracle is the source of truth (code)

## Default workflow (your setup)

| What | Where |
|------|--------|
| **Personal bot runs** | **Oracle only** — `orchestrator.py`, dashboard, agents, **all cron jobs** and systemd units point at `~/trading-bot` on the VM. |
| **Default sync direction** | **Oracle → Mac** — refresh your Mac copy with `scripts/sync_pull_from_oracle.sh` so Cursor matches production code. |
| **Mac role** | **Mirror + editor** — not a second production runtime. Avoid running the same trading cron or “live” bot on the Mac unless you explicitly mean a throwaway test. |
| **Mac → Oracle** | **On purpose only** — when you need to push a tree from the Mac to the server, use `deploy_to_oracle.sh`; then return to editing on Oracle as truth. |

Production **code** you care about should be edited, run, and committed on the **Oracle** VM (`~/trading-bot`). Your Mac is a **convenience mirror** for Cursor / reading — **not** a second canonical git remote unless you use a shared host (GitHub).

---

## Safe pull: Oracle → Mac (default)

From your **Mac**, in this repo:

```bash
chmod +x scripts/sync_pull_from_oracle.sh
./scripts/sync_pull_from_oracle.sh ubuntu@YOUR_ORACLE_IP
```

This script:

- **Does not use `rsync --delete` by default** — so it will **not** delete your Mac’s **`.git/`** when Oracle has no git tree (normal: `deploy_to_oracle.sh` excludes `.git/`).
- **Excludes** pulling: `venv/`, `data/`, `.env`, `logs/*.log`, **`.git/`** from the server (never overwrite Mac git with server junk).

Stale files that you deleted on Oracle may still exist on the Mac until you remove them manually — that is intentional (safe default).

### Optional prune (`SYNC_PULL_DELETE=1`)

Only if you **must** mirror deletions and you have **rsync 3+** on the Mac (Homebrew `rsync`):

```bash
SYNC_PULL_DELETE=1 ./scripts/sync_pull_from_oracle.sh ubuntu@YOUR_ORACLE_IP
```

Uses rsync **`protect`** filters for `.git/`, `.env`, `.cursor/`. If your rsync is too old, the script exits with an error instead of corrupting git.

---

## What went wrong if you used `--delete` without protection

`deploy_to_oracle.sh` **does not** upload `.git/` to Oracle. So Oracle either has **no** `.git` or an **incomplete** one.

Running **`rsync --delete`** from Oracle → Mac makes rsync **remove everything on the Mac that is not on Oracle**, including your **entire `.git`** — then copy whatever partial `.git` exists on Oracle → **broken / inconsistent git on the Mac**.

### Recovery on Mac

1. **Time Machine / backup** — restore `~/Downloads/trading-bot/.git` if you can.
2. **Remote you used to push** — `git clone` fresh, copy `.env` from `.env.example` again, then run **safe** `sync_pull_from_oracle.sh` (no delete) to overlay Oracle code.
3. **No backup** — clone a new directory, pull Oracle code with the fixed script, re-add remotes, and treat Oracle + any tags on server as reference.

---

## Mac → Oracle (overwrite server)

When you **intentionally** deploy from the Mac:

```bash
./deploy_to_oracle.sh --host ... --user ubuntu --remote-dir /home/ubuntu/trading-bot ...
```

After that, **Oracle is ahead** of whatever was only on the Mac; continue editing on Oracle for truth.

---

## Related

- `docs/OPERATOR_RUNBOOKS.md` — operator loop + sync blurb
- `deploy_to_oracle.sh` — pushes code **without** `.git/`
