#!/usr/bin/env bash
# Install production crontab with CRON_TZ=America/New_York for RTH agent jobs.
# Root cause fix: TZ= on the command line does NOT shift cron schedule — only CRON_TZ does.
set -euo pipefail

TMP="$(mktemp)"
cat > "$TMP" << 'CRON'
# Trading-bot: operations (UTC schedule — VM system timezone)
*/15 * * * * cd /home/ubuntu/trading-bot && flock -n /tmp/trading-bot-live_health.lock env FORTRESS_CRON_ONCE=1 ./live_health.sh >> /home/ubuntu/trading-bot/logs/cron_health.log 2>&1
0 * * * * cd /home/ubuntu/trading-bot && flock -n /tmp/trading-bot-monitor.lock env FORTRESS_CRON_ONCE=1 ./monitor.sh >> /home/ubuntu/trading-bot/logs/monitor.log 2>&1
0 6 * * * cd /home/ubuntu/trading-bot && ./daily_health_report.sh >> /home/ubuntu/trading-bot/logs/daily_health.log 2>&1
0 7 * * 1-5 cd /home/ubuntu/trading-bot && /home/ubuntu/trading-bot/venv/bin/python scripts/generate_daily_ops_report.py >> /home/ubuntu/trading-bot/logs/daily_ops_report.log 2>&1
0 */2 * * * cd /home/ubuntu/trading-bot && /home/ubuntu/trading-bot/venv/bin/python check_health.py >> /home/ubuntu/trading-bot/logs/open_health.log 2>&1
0 * * * * cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh drift_detector python3 -m agents.drift_detector >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1
*/15 * * * * cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh ops_autofix python3 -m agents.ops_autofix_agent >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1

CRON_TZ=America/New_York
# Trading-bot + fortress-ai: RTH and ET-window jobs (schedules below are US/Eastern)
*/5 9-16 * * 1-5 cd /home/ubuntu/trading-bot && /home/ubuntu/trading-bot/venv/bin/python sync_alpaca.py >> /home/ubuntu/trading-bot/logs/sync.log 2>&1
*/30 9-16 * * 1-5 cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh regime_detector python3 -m agents.regime_detector >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1
*/20 9-16 * * 1-5 cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh sentiment_velocity python3 -m agents.sentiment_velocity_agent >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1
*/30 9-16 * * 1-5 cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh screener python3 -m agents.screener_agent >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1
*/30 9-16 * * 1-5 cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh options_flow python3 -m agents.options_flow_agent >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1
*/5 9-16 * * 1-5 cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh monitor >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1
45 8 * * 1-5 cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh morning_briefing python3 -m agents.briefing_agent >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1
0 8 * * 1-5 cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh earnings_intel python3 -m agents.earnings_intel_agent >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1
30 16 * * 1-5 cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh earnings_intel_close python3 -m agents.earnings_intel_agent >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1
35 14 * * 1-5 cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh screen >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1
5 15 * * 1-5 cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh screen >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1
10 17 * * 1-5 cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh recursive_evolution python3 orchestrator.py evolve >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1
*/30 9-16 * * 1-5 cd /home/ubuntu/fortress-ai && bash scripts/cron_run.sh sec_ingest python3 -m agents.domain_ingest.ingest_runner --source sec_edgar >> /home/ubuntu/fortress-ai/logs/cron_master.log 2>&1

CRON_TZ=UTC
0 */2 * * * cd /home/ubuntu/trading-bot && bash scripts/cron_run.sh regime_detector_offhours python3 -m agents.regime_detector >> /home/ubuntu/trading-bot/logs/cron_master.log 2>&1
0 */1 * * * cd /home/ubuntu/fortress-ai && bash scripts/cron_run.sh ingest_all python3 -m agents.domain_ingest.ingest_runner >> /home/ubuntu/fortress-ai/logs/cron_master.log 2>&1
0 17 * * 5 cd /home/ubuntu/fortress-ai && bash scripts/cron_run.sh cot_ingest python3 -m agents.domain_ingest.ingest_runner --source cot_report >> /home/ubuntu/fortress-ai/logs/cron_master.log 2>&1
CRON

crontab "$TMP"
rm -f "$TMP"
echo "Installed crontab with CRON_TZ=America/New_York for RTH jobs."
crontab -l | head -25
