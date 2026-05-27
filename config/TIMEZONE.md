# System timezone

**All times on this stack are US Eastern (`America/New_York`). Nothing else.**

See also the fortress-ai sibling: `/home/ubuntu/fortress-ai/config/TIMEZONE.md`.

## Canonical source

| Item | Location |
|------|----------|
| Registry | `config/system_timezone.json` |
| Python API | `utils/system_time.py` |
| Env override | `FORTRESS_SYSTEM_TZ=America/New_York` |
| Cron | `CRON_TZ=America/New_York` (`scripts/install_production_crontab.sh`) |

## Rules for new code

1. Use `utils.system_time` — never `datetime.now(timezone.utc)`.
2. Cron and RTH logic use US/Eastern only.
