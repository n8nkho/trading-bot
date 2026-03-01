# Setting Up Fortress Trading Bot in Cursor

## STEP 1: CLONE/OPEN PROJECT

### Option A: If continuing on same server
```bash
# Cursor can connect via SSH
# In Cursor: Cmd/Ctrl+Shift+P → "Remote-SSH: Connect to Host"
# Add: ubuntu@132.226.33.49
# Open folder: /home/ubuntu/trading-bot
```

### Option B: If working locally
```bash
# Clone from server to your Mac
rsync -avz ubuntu@132.226.33.49:~/trading-bot ~/trading-bot-local
cd ~/trading-bot-local
cursor .
```

---

## STEP 2: CONFIGURE CURSOR FOR THIS PROJECT

### Add to .cursorrules (project-specific instructions)
```bash
cat > .cursorrules << 'RULES'
# Fortress Trading Bot - Cursor Rules

## Project Context
This is an autonomous trading bot with 29 AI agents. Always reference PROJECT_CONTEXT.md for system overview before making changes.

## Key Constraints
- NEVER edit .env file (contains API keys)
- NEVER commit sensitive data
- All trading is PAPER ONLY (Alpaca paper account)
- Max 6 auto-trades per day
- Strict filters: 5-15% drop, RSI <40, volume >1.5x

## Code Style
- Conservative and defensive
- Comprehensive logging
- Error handling on all API calls
- Type hints when reasonable
- Comments for complex logic

## Testing
- Always test on paper account first
- Verify cron jobs after changes: `crontab -l`
- Check logs after changes: `tail -f logs/*.log`
- Run health check: `python check_health.py`

## Architecture Patterns
- Agents are independent modules
- orchestrator.py coordinates everything
- All API calls go through clients (Alpaca, OANDA, Grok)
- Logging to logs/ directory
- Data persistence in data/ directory

## Common Tasks
- Add strategy: Create in agents/, add to run_strategies.py
- Fix cron: `crontab -e`
- Check health: `python check_health.py`
- View results: `cat data/daily_signals_$(date +%Y%m%d).json`

Always read PROJECT_CONTEXT.md before major changes.
RULES
```

---

## STEP 3: FIRST SESSION PROMPT

When opening Cursor, paste this as your first message:
```markdown
I'm continuing development on the Fortress Trading Bot. Please read PROJECT_CONTEXT.md for complete system overview.

Current Status:
- 29 AI agents operational
- Auto-execution enabled (starts Monday March 2)
- 4x daily screening (3 AM, 10:30 AM, 1 PM, 3 PM)
- Paper trading on Alpaca
- Server: ubuntu@132.226.33.49:~/trading-bot

Known Issues to Fix:
1. Smart Money Trader disabled (pandas Series bug lines 125-128)
2. Fortress Orchestrator disabled (bond_manager.py line 20 client issue)
3. Minor: ACN/WDAY occasional KeyError 'current_price'

I want to: [STATE YOUR GOAL]

Please review PROJECT_CONTEXT.md first, then suggest approach.
```

---

## STEP 4: USEFUL CURSOR FEATURES

### Use Composer (Cmd+I)
- Multi-file editing
- "Fix smart_money_trader.py pandas issue across all affected lines"
- Shows changes before applying

### Use Chat (Cmd+L)
- Quick questions
- "Explain the auto-execution logic in orchestrator.py"
- "How does the screener filter work?"

### Use Codebase-Wide Search
- Cmd+Shift+F
- Search for "PAPER_TRADING_AUTO_EXECUTE" to see usage
- Find all "TODO" or "FIXME" comments

### Terminal Integration
- Built-in terminal at bottom
- Can run: `python check_health.py`
- Test changes immediately

---

## STEP 5: SUGGESTED WORKFLOW

### Daily Development
1. `git pull` - Get latest changes
2. Check health: `python check_health.py`
3. Make changes in Cursor
4. Test: `python orchestrator.py screen` (dry run)
5. `git add -A && git commit -m "description"`
6. `git push`

### Testing Changes
```bash
# Before deploying
python -m pytest tests/  # If you add tests
python orchestrator.py status  # Verify works
tail -f logs/screener.log  # Monitor in real-time
```

### Monitoring Production
```bash
# SSH to server
ssh ubuntu@132.226.33.49

# Check what's running
python check_health.py

# View recent activity
tail -100 logs/screener.log | grep "QUALIFIED\|AUTO-EXECUTING"

# Track performance
python track_performance.py
```

---

## STEP 6: COMMON DEVELOPMENT TASKS

### Add New Strategy
```bash
# 1. Create agent
cursor agents/new_strategy.py

# 2. Add to runner
# Edit run_strategies.py, add elif block

# 3. Test manually
python run_strategies.py new_strategy

# 4. Add to cron if needed
crontab -e
```

### Fix Bug
```bash
# 1. Find error in Error Detective
cat logs/error_report.txt

# 2. Use Cursor to fix
# Cmd+I: "Fix the KeyError in screener_agent.py line 211"

# 3. Test
python orchestrator.py screen

# 4. Commit
git add -A && git commit -m "fix: KeyError in screener"
```

### Optimize Performance
```bash
# 1. Check current performance
python track_performance.py

# 2. Analyze logs
grep "execution time\|timeout" logs/*.log

# 3. Use Cursor to optimize
# Chat: "The screener is slow. How can we speed it up?"

# 4. Benchmark
time python orchestrator.py screen
```

---

## STEP 7: DEBUGGING IN CURSOR

### Use Built-in Debugger
- Set breakpoints: Click left margin
- F5: Start debugging
- Step through auto-execution logic

### Use Terminal for Quick Tests
```bash
# Test specific function
python -c "from agents.screener_agent import run_screener; run_screener()"

# Check imports
python -c "import orchestrator; print('OK')"
```

### Check Logs in Real-Time
- Open logs/ in Cursor sidebar
- Tail in terminal: `tail -f logs/screener.log`
- Cursor auto-refreshes open files

---

## TIPS FOR CURSOR + CLAUDE

### Effective Prompts
- "Review PROJECT_CONTEXT.md then explain the screening logic"
- "Fix all pandas Series comparison errors in smart_money_trader.py"
- "Add logging to track auto-execution decisions"

### Multi-File Edits
- Use Composer (Cmd+I) for changes across files
- Example: "Update all agents to use khf-fast model"

### Code Reviews
- "@orchestrator.py review the auto-execution logic for bugs"
- "Check all API error handling across agents/"

### Documentation
- "Generate docstrings for all functions in screener_agent.py"
- "Create README for new developers"

---

