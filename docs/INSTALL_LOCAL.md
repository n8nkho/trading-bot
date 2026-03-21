# Install on a laptop / desktop (customer lane)

For **lane 2** (customer local install). Same **git tag** as cloud; different machine.

## Prerequisites

- Python 3.10+ (match what you test in CI / Oracle)
- Git (optional if installing from zip)

## Steps

1. **Get a release** — Checkout a tagged version (e.g. `git checkout v1.0.0`) or extract a release zip **from that tag only**.
2. **Install**
   ```bash
   chmod +x scripts/*.sh
   ./scripts/install.sh
   ./scripts/verify_install.sh
   ```
3. **Configure** — Copy `.env.example` → `.env`. Add Alpaca / keys per your runbook.
4. **License tier** — Set tier from purchase (do **not** use `master` for paid SKUs unless contract says so):
   ```bash
   FORTRESS_LICENSE_TIER=starter   # or pro / enterprise
   ```
   Or point to a file from billing automation:
   ```bash
   FORTRESS_LICENSE_PATH=/path/to/license.json
   ```
5. **Dashboard**
   ```bash
   ./scripts/restart_dashboard.sh
   ```
   On Linux servers prefer systemd: `docs/INSTALL.md`, `deploy/systemd/README.md`.

## Optional: same build on Oracle (lane 3)

Use `deploy_to_oracle.sh` from the **same tag** and the **same** `FORTRESS_LICENSE_*` values (or `license.json` on the VM).

See **`docs/DISTRIBUTION.md`** for the three-lane overview.
