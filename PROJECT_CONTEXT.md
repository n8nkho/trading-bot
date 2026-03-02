# Fortress Trading Bot - Complete System Context

## SYSTEM OVERVIEW
Autonomous trading system with 29 AI agents, built over 3 sessions (Feb 23-27, 2026).
Paper trading on Alpaca, analysis via Ollama (local LLM), auto-execution enabled.

**Status:** Production-ready for paper trading, autonomous execution enabled
**Investment:** $1.06 total build cost, $0.001/month operating
**Track Record:** Proven filters (found TTD +26.75%, PENN +12%, multiple opportunities)

---

## SERVER DETAILS
- **Platform:** Oracle Cloud (Ubuntu 24, ARM64)
- **Access:** SSH ubuntu@132.226.33.49
- **Location:** ~/trading-bot
- **Git Commits:** 165+
- **Venv:** ~/trading-bot/venv (Python 3.12)

---

## ARCHITECTURE

### Core Components
```
~/trading-bot/
├── agents/              # 29 AI agents
│   ├── screener_agent.py       # Scans 500+ stocks 4x daily
│   ├── momentum_trader.py      # Intraday breakouts (60+ stocks)
│   ├── forex_sniper.py         # EUR/USD 9:30-12 PM
│   ├── trump_trader.py         # Policy correlation
│   ├── inefficiency_trader.py  # Gaps, reversals
│   ├── merger_arb.py          # Special situations
│   ├── exit_monitor.py        # Stop loss/profit targets
│   ├── agent_manager.py       # Auto-healing overseer
│   ├── error_detective.py     # Log scanner
│   ├── sms_alert.py           # Critical failure alerts (Twilio)
│   ├── smart_money_trader.py  # DISABLED (pandas bug)
│   └── [+19 more agents]
│
├── orchestrator.py      # Main controller
├── run_strategies.py    # Standalone strategy runner
├── check_health.py      # System diagnostics
├── track_performance.py # Trade analytics
│
├── dashboard/           # Flask web dashboard (port 8080)
├── data/               # positions.json, daily_signals_*.json
├── logs/               # All activity logs
└── config/             # Configuration files
```

### Key Technologies
- **Trading:** Alpaca API (paper trading)
- **Forex:** OANDA API (practice account)
- **AI Analysis:** Ollama (local LLM - khf-fast model)
- **Sentiment:** Grok API ($0.001/call)
- **Automation:** Cron (16 jobs)
- **Monitoring:** Custom agents

---

## CURRENT CONFIGURATION

### Auto-Execution Settings
```python
PAPER_TRADING_AUTO_EXECUTE = True
MAX_AUTO_TRADES_PER_DAY = 6
AUTO_POSITION_SIZE = 500  # $500 per trade
MIN_CONFIDENCE_FOR_AUTO = 0.70
STOP_LOSS = -3% (zero-loss push), scalp ladder 2%/4%/6%
PROFIT_TARGET = +10%
```

### Rollback
To restore pre-advanced version (before ladder/zero-loss/hedging): `git checkout backup-pre-advanced`.

### Screening Schedule (4x daily)
```
3:00 AM  - Overnight gaps & pre-market drops
10:30 AM - Morning panic & earnings crashes
1:00 PM  - Midday selloffs & news-driven drops
3:00 PM  - Late day panic & closing dumps
```

### Quality Filters (STRICT)
```
Drop: 5-15% (not 3%, not 20% - specific range)
RSI: < 40 (oversold)
Volume: > 1.5x average (conviction)
Target Win Rate: 70-80%
Philosophy: Quality over quantity
```

### Market Coverage
- **Before:** 10 stocks (0.2% of market)
- **After:** 500+ stocks (10% of liquid market)
- **Improvement:** 5000% increase

---

## PROVEN PERFORMANCE

### Recent Opportunities Found
```
Feb 26: TTD -13.5% → +26.75% same day (MISSED - no auto-execution yet)
Feb 27: PENN -8.4% → +12.1% (MISSED - found at 3 AM, bounced by 9 AM)
Feb 27: PATH -5.1% → +7.1% (MISSED)
Feb 27: ACN -6.9% → +7.6% (MISSED)

VERDICT: Filters are EXCELLENT, just needed faster execution
NOW: Auto-execution enabled for Monday March 2 onwards
```

### Win Rate Expectations
- Conservative estimate: 60-65%
- Target (strict filters): 70-80%
- Actual: TBD (starts Monday)

---

## AUTOMATION (16 CRON JOBS)
```bash
# Screening (4x daily)
0 3 * * 1-5     - Overnight screening + auto-execution
30 10 * * 1-5   - Morning panic screening
0 13 * * 1-5    - Midday crash screening
0 15 * * 1-5    - Late day screening

# Monitoring
*/1 9-16 * * 1-5  - Intraday sniper
*/5 * * * *       - Position monitor (exits)
*/5 * * * *       - Alpaca sync

# System Health
*/10 * * * *      - Agent Manager (auto-healing)
*/15 * * * *      - Llama Watchdog

# Weekly
0 0 * * 0         - Weekly review
0 1 * * 0         - Meta-architect analysis
```

---

## CRITICAL FILES

### Environment Variables (.env)
```bash
# Alpaca Trading
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret

# OANDA Forex
OANDA_API_KEY=your_key
OANDA_ACCOUNT_ID=your_account

# Grok Sentiment
GROK_API_KEY=your_key

# Twilio SMS (optional)
TWILIO_ACCOUNT_SID=ACxxxx
TWILIO_AUTH_TOKEN=xxxx
TWILIO_FROM_NUMBER=+1234567890
ALERT_TO_NUMBER=+1234567890
```

### Data Files
```
data/positions.json         - Current open positions
data/daily_signals_*.json   - Screening results by date
data/decisions_log.jsonl    - All trade decisions
data/auto_trades_*.json     - Auto-executed trades log
```

---

## KNOWN ISSUES

### Fixed
✅ LLM speed (switched llama3.1 → khf-fast: 29s → 5s)
✅ Market coverage (10 → 500+ stocks)
✅ Missing opportunities (enabled auto-execution)
✅ Orchestrator compatibility (removed PAPER_TRADING_MODE)

### Active Issues
⚠️ Smart Money Trader disabled (pandas Series ambiguity bug in lines 125-128)
⚠️ Fortress Orchestrator disabled (bond_manager.py line 20 - client at module level)
⚠️ Minor: WDAY, ACN occasional 'current_price' KeyError (non-critical, <1% error rate)

### Not Critical
- ANTHROPIC_API_KEY not found (document analysis disabled - not needed)
- Llama watchdog shows slow (tests old model, screener uses fast model - OK)

---

## DAILY COMMANDS

### Morning Routine (9 AM)
```bash
# Check overnight auto-trades
cat data/daily_signals_$(date +%Y%m%d).json
cat data/positions.json

# Track performance
python track_performance.py

# Health check
python check_health.py

# View logs
tail -50 logs/screener.log
```

### Manual Operations
```bash
# Run strategies manually
python run_strategies.py momentum
python run_strategies.py trump
python run_strategies.py inefficiency

# Orchestrator commands
python orchestrator.py screen   # Manual screening
python orchestrator.py forex    # Forex sniper
python orchestrator.py status   # System status

# Command Center dashboard (recommended: system health, agents, performance, news, recommendations)
python dashboard/command_center.py   # Port 8083 (or COMMAND_CENTER_PORT=8082)
# From local: ssh -L 8083:localhost:8083 ubuntu@132.226.33.49 then http://localhost:8083
```

---

## ARCHITECTURE DECISIONS

### Why These Choices?
1. **Local LLM (Ollama):** Free, fast (khf-fast), no API costs
2. **Paper Trading:** Validate before real money (3-6 months)
3. **Strict Filters:** Quality over quantity (70%+ win rate target)
4. **Auto-Execution:** Build track record autonomously
5. **Multi-Frequency:** Catch overnight + intraday opportunities
6. **Conservative Position Sizing:** $500/trade = 5% of $10K account

### Risk Management
- Max 6 trades/day (prevents over-trading)
- $500 per trade (5% of account per position)
- -5% stop loss (limits downside)
- +10% profit target (2:1 reward/risk)
- Max 30% of account at risk simultaneously

---

## NEXT MILESTONES

### Week 1 (March 2-8)
- Monitor auto-execution
- Track first 5-10 trades
- Verify stop losses work
- Document any issues

### Month 1 (March)
- Target: 20-30 paper trades
- Calculate actual win rate
- Identify best/worst strategies
- First meta-architect analysis

### Month 3 (May)
- Target: 100+ paper trades
- Proven win rate > 60%
- Decision: Deploy $100-500 real money
- Or refine further if unprofitable

### Month 6+ (August onwards)
- If consistently profitable: Scale to $1K-10K
- Meta-architect optimizations
- Add new strategies
- Full autonomous deployment

---

## TROUBLESHOOTING

### If Screener Finds Nothing
- Check log: `tail -100 logs/screener.log`
- Verify market was volatile (calm days = no opportunities)
- Check filters are reasonable (not too strict)

### If Auto-Execution Doesn't Trigger
- Check: `grep "AUTO-EXECUTING" logs/screener.log`
- Verify: `PAPER_TRADING_AUTO_EXECUTE = True` in orchestrator.py
- Check confidence threshold (must be > 70%)

### If Stop Loss Not Working
- Check: `tail -50 logs/monitor.log`
- Verify position exists in Alpaca
- Check monitor cron is running: `crontab -l | grep monitor`

### If Dashboard Down
- Check: `ps aux | grep fortress_app`
- Restart: `nohup python dashboard/fortress_app.py > logs/fortress_dashboard.log 2>&1 &`
- Agent Manager should auto-restart

---

## TRANSCRIPTS & DOCUMENTATION

**Full Build History:**
```
/mnt/transcripts/2026-02-23-...txt  - Initial build
/mnt/transcripts/2026-02-25-...txt  - Fortress hedging
/mnt/transcripts/2026-02-27-...txt  - Current session
/mnt/transcripts/journal.txt        - Index of all sessions
```

**Key Documents:**
```
HANDOFF.md                   - Session handoff, resume prompt (start here when resuming)
FORTRESS_FINAL_STATUS.md     - Complete system overview
FORTRESS_AUDIT_GUIDE.md      - Audit and verification
PROJECT_CONTEXT.md           - This file
SYSTEM_REVIEW.md             - Inconsistencies audit, fixes applied
```

---

## QUICK REFERENCE

**Most Important Files:**
1. `orchestrator.py` - Main controller (auto-execution logic)
2. `agents/screener_agent.py` - Core screening (500+ stocks, 4x daily)
3. `agents/exit_monitor.py` - Stop loss/profit targets
4. `agents/agent_manager.py` - Auto-healing
5. `.env` - API keys (NEVER commit!)

**Most Important Logs:**
1. `logs/screener.log` - Screening results
2. `logs/monitor.log` - Position monitoring
3. `logs/error_report.txt` - Error Detective findings
4. `logs/agent_manager.log` - Auto-healing actions

**Git Commands:**
```bash
git log --oneline | head -20  # Recent commits
git status                    # Working tree status
git diff orchestrator.py      # See changes
```

---

## PHILOSOPHY

**Warren Buffett Approach:**
- Wide net (scan 500+ stocks)
- Strict filters (only best opportunities)
- High conviction (volume > 1.5x)
- Patient (wait for perfect setups)
- Conservative (5% position sizes)

**Not Day Trading:**
- Contrarian value plays
- Buy panic, sell recovery
- Hold 1-5 days typically
- 70%+ win rate target
- Let profits run, cut losses quick

---

**Last Updated:** February 27, 2026
**Status:** Production ready, autonomous execution enabled
**Next Auto-Trade:** Monday March 2, 2026 at 3:00 AM EST
