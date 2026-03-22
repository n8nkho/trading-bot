# Lane 1 hardening (B) + housekeeping (D)

## B — Harden Oracle

### 1. Kernel reboot (when convenient)

If login shows **`System restart required`**:

```bash
sudo reboot
```

After reboot, confirm dashboard:

```bash
sudo systemctl status fortress-dashboard --no-pager
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8083/proof
```

### 2. One-command deploy **with** dashboard restart

From your **Mac** (repo root), use **`--service`** so you don’t forget the restart:

```bash
./deploy_to_oracle.sh \
  --host 132.226.33.49 \
  --user ubuntu \
  --remote-dir /home/ubuntu/trading-bot \
  --venv /home/ubuntu/trading-bot/venv \
  --service fortress-dashboard
```

Adjust **host** if your IP changes. `--venv` runs remote steps inside the venv (import gate + `record_version.py`); if your venv path differs, fix it.

### 3. Optional security

- **Firewall:** only **22** (SSH) and **8083** (or **443** if you proxy) from trusted IPs.
- **HTTPS:** terminate TLS on Nginx/Caddy and proxy to `127.0.0.1:8083` for public `/proof` and webhooks.

---

## D — Housekeeping rhythm

| When | On Mac | On Oracle |
|------|--------|-----------|
| You changed code | `git add -A && git commit -m "..."` | — |
| Share / backup | `git push origin master` (tracks **origin/main**) | — |
| Ship runtime | `./deploy_to_oracle.sh ... --service fortress-dashboard` | optional: `curl` **200** on `/proof` |
| Cursor mirror | `./scripts/sync_pull_from_oracle.sh ubuntu@HOST` | — |

**Oracle has no `.git`** in `~/trading-bot` by design (deploy rsync). **GitHub + Mac** are source of truth.

See also: `docs/SYNC_ORACLE_SOURCE_OF_TRUTH.md`, `docs/LANE1_OPERATOR_CHECKLIST.md`.
