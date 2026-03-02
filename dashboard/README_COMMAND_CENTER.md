# Fortress Command Center

World-class agentic dashboard: system health, agent activity, trading performance, strategy-impacting news, and recommendations.

## Run

```bash
cd /home/ubuntu/trading-bot
source venv/bin/activate
python dashboard/command_center.py
```

Open **http://localhost:8083** (default). To use another port: `COMMAND_CENTER_PORT=8082 python dashboard/command_center.py`. SSH tunnel: `ssh -L 8083:localhost:8083 ubuntu@<server>`.

## Features

- **System health** – Ollama, dashboard, cron, disk, risk status, data files
- **Agent activity** – Per-agent last run, fresh/stale status, last log line
- **Trading performance** – Positions, win rate, P&L, recent trades, latest screening summary
- **News impacting strategy** – Headlines from latest screening candidates
- **Recommendations** – Error report summary, circuit breaker, stale agents, improvement/weekly reports
- **Live activity feed** – Recent log lines from key agents

## API (JSON)

- `GET /api/health`
- `GET /api/agents`
- `GET /api/performance`
- `GET /api/news`
- `GET /api/recommendations`
- `GET /api/feed`

Auto-refresh: 60 seconds. Use **Refresh** for immediate update.
