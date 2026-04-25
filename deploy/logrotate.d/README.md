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

## Schedule

logrotate is run automatically by the system daily via `/etc/cron.daily/logrotate`

No additional cron entry needed after install.
