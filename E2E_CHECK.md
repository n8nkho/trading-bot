# End-to-End Overnight Check (March 1, 2026)

## Server
- **Timezone:** America/New_York (EST) ✓
- **Cron:** Uses server local time, so 3 AM = 3 AM ET ✓

## Overnight Flow (Mon–Fri)

| Time (ET) | Cron | Command | Status |
|-----------|------|---------|--------|
| 2:55 AM | Preload | `python -c "from agents.llama_watchdog import preload_models; preload_models()"` | ✓ |
| 3:00 AM | Overnight screen | `orchestrator.py screen` → screener.log | ✓ |
| 9:00 AM | Sync starts | `sync_alpaca.py` every 5 min | ✓ |
| 9:00 AM | Monitor starts | `orchestrator.py monitor` every 5 min | ✓ |
| 9:00 AM | Sniper starts | `orchestrator.py snipe` every min | ✓ |
| 10:30 AM | Morning screen | `orchestrator.py screen` | ✓ |
| 1:00 PM | Midday screen | `orchestrator.py screen` | ✓ |
| 3:00 PM | Late screen | `orchestrator.py screen` | ✓ |

## Verified
- ✓ ALPACA_API_KEY set
- ✓ Ollama responding (11434)
- ✓ PAPER_TRADING_AUTO_EXECUTE = True
- ✓ Screener adds current_price to candidates
- ✓ orchestrator momentum command added (was missing)
- ✓ sync_alpaca, monitor use project-root paths
- ✓ Unknown commands now exit with error (no silent no-op)

## Cron Paths
All use `/home/ubuntu/trading-bot/venv/bin/python` and `cd /home/ubuntu/trading-bot` ✓

## Monday March 2
3:00 AM ET screening will run. Auto-execution will place trades if qualified candidates found (5–15% drop, RSI <40, volume >1.5x, confidence ≥70%).
