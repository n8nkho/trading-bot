# Classic entry window and production cron

## Entry window (orchestrator `screen`)

Classic Fortress only evaluates **BUY** candidates during the configured entry window (default **14:30–16:00 ET**, weekday). Screens outside this window may run but will not open new positions.

Production cron runs `screen` at:

| ET time | Purpose |
|---------|---------|
| **14:35** | First in-window screen after open |
| **14:50** | Early-window refresh |
| **15:05** | Mid-window refresh |
| **15:35** | Late-window refresh (before window close) |

`monitor` runs every **5 minutes** during **09:00–16:59 ET** weekdays for stops and position management.

## Install production crontab

```bash
cd /home/ubuntu/trading-bot
# Edit REPO= if your clone path differs
crontab deploy/cron/trading-bot.production.crontab
```

Reference copy: `deploy/cron/trading-bot.production.crontab`  
Example / legacy notes: `deploy/cron/trading-bot.crontab.example`

## Heartbeats

Jobs in `deploy/cron_manifest.json` are checked by the dashboard via `utils/cron_heartbeat.py`. RTH-only jobs (`9-16` weekdays) are not flagged stale on weekends or outside ~09:30–16:00 ET.

## Manual recovery

```bash
./scripts/cron_run.sh screen
./scripts/cron_run.sh monitor
```
