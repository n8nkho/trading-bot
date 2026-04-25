# Fortress VM Deployment Checklist

## One-time setup (run in order)

### 1. Install log rotation

The logrotate stanza uses `su ubuntu ubuntu` so rotation works when `logs/` is writable by user `ubuntu` (avoids “insecure permissions” skips).

```bash
sudo cp deploy/logrotate.d/fortress /etc/logrotate.d/fortress
sudo logrotate --force /etc/logrotate.d/fortress
```

### 2. Install environment flags

```bash
bash deploy/install_env_flags.sh
source ~/.bashrc
```

### 3. Verify flags

```bash
env | grep FORTRESS
```

### 4. Install cron jobs

`crontab -e`

Add these lines:

```
# Fortress — reflection (5pm ET Mon-Fri)
0 17 * * 1-5 TZ=America/New_York cd /home/ubuntu/trading-bot && \
  /home/ubuntu/trading-bot/venv/bin/python -m agents.reflection_agent \
  >> /home/ubuntu/trading-bot/logs/reflection.log 2>&1

# Fortress — morning briefing (6am ET Mon-Fri)  
0 6 * * 1-5 TZ=America/New_York cd /home/ubuntu/trading-bot && \
  /home/ubuntu/trading-bot/venv/bin/python -m agents.briefing_agent \
  >> /home/ubuntu/trading-bot/logs/briefing.log 2>&1

# Cross-asset (5:30am ET — before briefing)
30 5 * * 1-5 TZ=America/New_York cd /home/ubuntu/trading-bot && \
  /home/ubuntu/trading-bot/venv/bin/python -m agents.cross_asset_agent \
  >> /home/ubuntu/trading-bot/logs/cross_asset.log 2>&1

# Regime detection (9:30am ET — market open)
30 9 * * 1-5 TZ=America/New_York cd /home/ubuntu/trading-bot && \
  /home/ubuntu/trading-bot/venv/bin/python -m agents.regime_detector \
  >> /home/ubuntu/trading-bot/logs/regime.log 2>&1

# Sentiment velocity (every 30 min during market hours)
*/30 9-16 * * 1-5 TZ=America/New_York cd /home/ubuntu/trading-bot && \
  /home/ubuntu/trading-bot/venv/bin/python -m agents.sentiment_velocity_agent \
  >> /home/ubuntu/trading-bot/logs/sentiment_velocity.log 2>&1

# Options flow (every 15 min during market hours)
*/15 9-16 * * 1-5 TZ=America/New_York cd /home/ubuntu/trading-bot && \
  /home/ubuntu/trading-bot/venv/bin/python -m agents.options_flow_agent \
  >> /home/ubuntu/trading-bot/logs/options_flow.log 2>&1

# Earnings intel (every 5 min during earnings window)
*/5 16-21 * * 1-5 TZ=America/New_York cd /home/ubuntu/trading-bot && \
  /home/ubuntu/trading-bot/venv/bin/python -m agents.earnings_intel_agent \
  >> /home/ubuntu/trading-bot/logs/earnings_intel.log 2>&1

# Prompt evolution (5:30pm ET — after reflection)
30 17 * * 1-5 TZ=America/New_York cd /home/ubuntu/trading-bot && \
  /home/ubuntu/trading-bot/venv/bin/python -m agents.prompt_evolution_agent \
  >> /home/ubuntu/trading-bot/logs/prompt_evolution.log 2>&1

# Regime re-check (every 2 hours during market)
0 10,12,14,16 * * 1-5 TZ=America/New_York cd /home/ubuntu/trading-bot && \
  /home/ubuntu/trading-bot/venv/bin/python -m agents.regime_detector \
  >> /home/ubuntu/trading-bot/logs/regime.log 2>&1
```

### 5. Verify dry runs pass

```bash
python3 -m agents.critique_loop --dry-run
python3 -m agents.reflection_agent --dry-run
python3 -m agents.briefing_agent --dry-run
```

### 6. Monitor on first trading day

```bash
tail -f logs/critique.log &
tail -f logs/screener.log &
tail -f logs/briefing_$(date +%Y%m%d).log
```

## Feature flags reference

| Flag | Purpose |
|---|---|
| FORTRESS_CRITIQUE_LOOP_ENABLED=1 | Enables DeepSeek+xAI trade debate |
| FORTRESS_REFLECTION_ALLOW_WRITES=1 | Enables nightly reflection writes |
| FORTRESS_BRIEFING_ALLOW_WRITES=1 | Enables morning briefing writes |
| FORTRESS_RECURSIVE_SCREENER_ENABLED=1 | Enables L1-L4 screener |
| FORTRESS_RECURSIVE_SCREENER_LLM_DRY_RUN=1 | Skips L3 LLM (technical only) |
