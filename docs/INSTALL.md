# Install Fortress / trading-bot (laptop or server)

## 1. Clone and install Python environment

```bash
cd /path/to/trading-bot
chmod +x scripts/*.sh
./scripts/install.sh
```

Optional: install and run verification in one step:

```bash
./scripts/install.sh --verify
```

Set a non-default tree:

```bash
INSTALL_ROOT=/opt/fortress ./scripts/install.sh
```

## 2. Configure secrets

Edit `.env` (created from `.env.example` on first install). At minimum, set Alpaca **paper** keys for safe testing.

## 3. Verify

```bash
./scripts/verify_install.sh          # import gate + smoke + dashboard parse
./scripts/verify_install.sh --quick  # import gate only
```

## 4. Run the Command Center (dashboard)

Ad-hoc (matches Oracle-style `nohup` flow):

```bash
./scripts/restart_dashboard.sh
```

Default URL: `http://0.0.0.0:8083/` (override with `COMMAND_CENTER_PORT`).

## 5. systemd (Linux VM / Oracle OCI)

For a persistent service as root:

```bash
sudo ./scripts/install_systemd.sh --now
```

See `deploy/systemd/README.md` for overrides (`FORTRESS_USER`, `FORTRESS_HOME`), logs, and uninstall.

**Note:** Cron jobs (screener, monitor, etc.) stay in your user crontab; systemd here only manages the web UI.

## 6. Deploy from your laptop (Oracle / remote VM)

Run from the **repo root on your Mac** (not on the VM — avoids rsync-to-self and double password prompts):

```bash
./deploy_to_oracle.sh \
  --host YOUR_PUBLIC_IP \
  --user ubuntu \
  --remote-dir /home/ubuntu/trading-bot \
  --venv /home/ubuntu/trading-bot/venv \
  --service fortress-dashboard
```

- **`--venv`** — activates that path **on the server** so `smoke_deploy_import_gate.py` uses the server venv.
- **`--service fortress-dashboard`** — restarts the dashboard after sync so the UI matches the new code.
- **`--install-deps`** — add if `requirements.txt` changed and you need `pip install` on the server.

**Drop password prompts** (run once on the laptop):

```bash
ssh-copy-id -p 22 ubuntu@YOUR_PUBLIC_IP
```

After deploy, the script prints **Next** steps (health `curl`, `systemctl status`).

## Troubleshooting

- **`./scripts/install.sh: No such file or directory` on the server** — The VM does not have the latest repo tree yet. Scripts only exist after you **sync** from your laptop or **pull** in git.
  - **Check:** `ls -la scripts/install.sh` (should show a file).
  - **From your laptop** (repo root, with your OCI host/user):  
    `./deploy_to_oracle.sh --host YOUR_IP --user ubuntu --remote-dir /home/ubuntu/trading-bot --venv /home/ubuntu/trading-bot/venv --service fortress-dashboard`
  - **Or on the server** (if you use `git` there): `cd ~/trading-bot && git pull`
  - Then: `chmod +x scripts/*.sh` and run install/verify/systemd again.
- **`sudo: ./scripts/install_systemd.sh: command not found`** — Usually the same as above (script missing). If the file exists, run with bash explicitly:  
  `sudo bash /home/ubuntu/trading-bot/scripts/install_systemd.sh --now`
- **Port in use:** `fuser -k 8083/tcp` or `sudo systemctl restart fortress-dashboard`
- **Stale UI after deploy:** `./scripts/restart_dashboard.sh` or `sudo systemctl restart fortress-dashboard`
- **Import errors:** Re-run `./scripts/install.sh` after pulling new code; then `./scripts/verify_install.sh`
