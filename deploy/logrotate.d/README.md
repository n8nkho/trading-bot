# Fortress Log Rotation

## Install on Ubuntu VM

```bash
sudo cp deploy/logrotate.d/fortress /etc/logrotate.d/fortress
sudo logrotate --debug /etc/logrotate.d/fortress
sudo logrotate --force /etc/logrotate.d/fortress
```

## Verify

```bash
ls -lh /home/ubuntu/trading-bot/logs/risk.log
```

## “insecure permissions” / skipping all logs

If `sudo logrotate --force` prints `parent directory has insecure permissions`, the stanza must run as the repo user (the config includes `su ubuntu ubuntu`). After updating `/etc/logrotate.d/fortress`, run `sudo logrotate --force /etc/logrotate.d/fortress` again.

Optional hardening (tighter directory mode, still owned by `ubuntu`):

```bash
sudo chown ubuntu:ubuntu /home/ubuntu/trading-bot/logs
chmod 0755 /home/ubuntu/trading-bot/logs
```

## Schedule

logrotate is run automatically by the system daily via `/etc/cron.daily/logrotate`

No additional cron entry needed after install.
