# Fortress systemd (production VM / OCI)

## Prerequisites

- Run `./scripts/install.sh` and `./scripts/verify_install.sh` as the deployment user (e.g. `ubuntu`).
- `.env` must be readable by that user (Alpaca paper keys, etc.).

## Install the dashboard unit (multi-user / server)

From the repo root, as **root**:

```bash
cd /home/ubuntu/trading-bot   # or your clone path
sudo ./scripts/install_systemd.sh --now
```

Customize user/path:

```bash
sudo FORTRESS_USER=ubuntu FORTRESS_HOME=/home/ubuntu/trading-bot ./scripts/install_systemd.sh --now
```

## Commands

```bash
sudo systemctl status fortress-dashboard
sudo systemctl restart fortress-dashboard
sudo journalctl -u fortress-dashboard -f
tail -f /home/ubuntu/trading-bot/logs/dashboard_systemd.log
```

**Prefer this restart** if you ever ran `./scripts/restart_dashboard.sh` (nohup) on the same host — it frees port **8083** first:

```bash
cd /home/ubuntu/trading-bot
sudo ./scripts/restart_dashboard_systemd.sh
```

## Troubleshooting: `Address already in use` / systemd crash loop

**Symptom:** `logs/dashboard_systemd.log` repeats *Port 8083 is in use*; `systemctl status` flaps; `curl /proof` may still return **200** (a **nohup** process is serving, not systemd).

**Cause:** Two dashboards: **systemd** + **manual** `nohup … command_center.py`.

**Fix:**

```bash
cd /home/ubuntu/trading-bot
sudo ./scripts/restart_dashboard_systemd.sh
```

With the unit enabled, use **`restart_dashboard_systemd.sh`**, not **`restart_dashboard.sh`**.

## Uninstall

```bash
sudo systemctl disable --now fortress-dashboard 2>/dev/null || true
sudo rm -f /etc/systemd/system/fortress-dashboard.service
sudo systemctl daemon-reload
```

## Cron vs systemd

Trading jobs (screen, monitor, snipe, fortress) are normally **cron** on this project. This unit only manages the **Command Center** web UI. Keep your existing `crontab` entries.

### Why `SupplementaryGroups=crontab` and no `NoNewPrivileges`

User crontabs live under `/var/spool/cron/crontabs/` (not world-accessible). We add **`SupplementaryGroups=crontab`** so Python can read the spool file by path. **`/usr/bin/crontab -l`** is **setgid `crontab`**; **`NoNewPrivileges=true`** blocks that setgid, so **`crontab -l` stays empty** under systemd and System health shows **Cron red** even with a valid user crontab. This unit **omits** `NoNewPrivileges` so **`crontab -l` works**.

If you **reinstall** the unit from an older template, run `sudo ./scripts/install_systemd.sh --now` again to refresh `/etc/systemd/system/fortress-dashboard.service`.

## Laptop (user session)

For a per-user install without sudo, use a **user** unit or keep `./scripts/restart_dashboard.sh` + `nohup`.

Example user unit path: `~/.config/systemd/user/fortress-dashboard.service` — copy the template, replace `@FORTRESS_HOME@` with `%h/trading-bot`, set `User=` lines appropriately (omit for user units), then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now fortress-dashboard
```
