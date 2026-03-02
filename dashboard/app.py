from flask import Flask, render_template, jsonify
import json
import plotly
import plotly.graph_objs as go
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import pytz
import yfinance as yf
import shutil
import logging
from pathlib import Path

app = Flask(__name__)

# Add custom Jinja2 filters
@app.template_filter('format_currency')
def format_currency(value):
    """Format number as currency"""
    try:
        return f"${value:,.2f}"
    except (ValueError, TypeError):
        return "$0.00"

# Project root (dashboard/ is one level below)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
log_dir = _PROJECT_ROOT / 'logs'
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    filename=log_dir / 'dashboard.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Data directory
DATA_DIR = _PROJECT_ROOT / 'data'

def load_positions():
    """Load current positions from positions.json"""
    try:
        positions_file = DATA_DIR / 'positions.json'
        if positions_file.exists():
            with open(positions_file, 'r') as f:
                positions = json.load(f)
                logging.debug(f"Loaded positions: {positions}")
                return positions
        else:
            logging.warning("Positions file not found, returning empty list.")
            return []
    except FileNotFoundError:
        logging.error("Positions file not found.")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON from positions file: {e}")
        return []
    except Exception as e:
        logging.error(f"Unexpected error loading positions: {e}")
        return []

def load_decisions_log():
    """Load decisions log from decisions_log.jsonl"""
    try:
        log_file = DATA_DIR / 'decisions_log.jsonl'
        decisions = []
        if log_file.exists():
            with open(log_file, 'r') as f:
                for line in f:
                    if line.strip():
                        decisions.append(json.loads(line))
        return decisions
    except Exception as e:
        logging.error(f"Error loading decisions log: {e}")
        return []

def get_portfolio_value():
    """Calculate total portfolio value from positions + cash"""
    try:
        positions = load_positions()
        total_value = 0
        
        for pos in positions:
            ticker = pos.get('ticker')
            qty = pos.get('qty', 0)
            
            try:
                stock = yf.Ticker(ticker)
                current_price = stock.history(period='1d')['Close'].iloc[-1]
                total_value += current_price * qty
            except Exception as e:
                logging.warning(f"Could not fetch price for {ticker}: {e}")
                # Use entry price as fallback
                total_value += pos.get('entry_price', 0) * qty
        
        # Fetch cash from Alpaca API if available
        try:
            # Placeholder for Alpaca API call to get cash balance
            cash_balance = 10000  # Replace with actual API call
            total_value += cash_balance
        except Exception as e:
            logging.warning(f"Could not fetch cash balance from Alpaca API: {e}")
        
        return total_value
    except Exception as e:
        logging.error(f"Error calculating portfolio value: {e}")
        return 0

def get_market_status():
    """Check if market is open (9:30-16:00 ET, Mon-Fri)"""
    try:
        et_tz = pytz.timezone('America/New_York')
        now_et = datetime.now(et_tz)
        
        # Log current day and hour
        logging.debug(f"Current day: {now_et.weekday()}, Current hour: {now_et.hour}")
        
        # Check if weekend
        if now_et.weekday() >= 5:
            logging.debug("Market is closed: Weekend")
            return False
        
        # Check market hours
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        
        is_open = market_open <= now_et <= market_close
        logging.debug(f"Market open calculation: {is_open}")
        
        return is_open
    except Exception as e:
        logging.error(f"Error checking market status: {e}")
        return False

def calculate_win_rate(days=30):
    """Calculate win rate from decisions log"""
    try:
        decisions = load_decisions_log()
        cutoff_date = datetime.now() - timedelta(days=days)
        
        wins = 0
        losses = 0
        
        for decision in decisions:
            try:
                decision_date = datetime.fromisoformat(decision.get('timestamp', ''))
                if decision_date < cutoff_date:
                    continue
                
                if decision.get('action') == 'SELL':
                    pnl_pct = decision.get('pnl_pct', 0)
                    if pnl_pct > 0:
                        wins += 1
                    elif pnl_pct < 0:
                        losses += 1
            except Exception:
                continue
        
        total = wins + losses
        return (wins / total * 100) if total > 0 else 0
    except Exception as e:
        logging.error(f"Error calculating win rate: {e}")
        return 0

@app.route('/')
def home():
    """Main dashboard page"""
    try:
        portfolio_value = get_portfolio_value()
        positions = load_positions()
        open_positions = len(positions)
        win_rate = calculate_win_rate(30)
        market_status = "OPEN" if get_market_status() else "CLOSED"
        
        # Calculate today's P&L (simplified)
        today_pnl = 0
        for pos in positions:
            try:
                ticker = pos.get('ticker')
                stock = yf.Ticker(ticker)
                current_price = stock.history(period='1d')['Close'].iloc[-1]
                entry_price = pos.get('entry_price', current_price)
                qty = pos.get('qty', 0)
                today_pnl += (current_price - entry_price) * qty
            except Exception:
                continue
        
        system_status = "ACTIVE"
        
        return render_template('home.html',
                             portfolio_value=portfolio_value,
                             today_pnl=today_pnl,
                             open_positions=open_positions,
                             win_rate=win_rate,
                             market_status=market_status,
                             system_status=system_status)
    except Exception as e:
        logging.error(f"Error in home route: {e}")
        return render_template('home.html',
                             portfolio_value=0,
                             today_pnl=0,
                             open_positions=0,
                             win_rate=0,
                             market_status="UNKNOWN",
                             system_status="ERROR")

@app.route('/performance')
def performance():
    """Performance analytics page"""
    try:
        decisions = load_decisions_log()
        cutoff_date = datetime.now() - timedelta(days=30)
        
        # Filter last 30 days
        recent_decisions = [d for d in decisions 
                          if datetime.fromisoformat(d.get('timestamp', '')) > cutoff_date]
        
        # Create daily P&L data
        daily_pnl = {}
        for decision in recent_decisions:
            if decision.get('action') == 'SELL':
                date = datetime.fromisoformat(decision['timestamp']).date()
                pnl = decision.get('pnl_pct', 0)
                daily_pnl[date] = daily_pnl.get(date, 0) + pnl
        
        dates = sorted(daily_pnl.keys())
        pnl_values = [daily_pnl[d] for d in dates]
        
        # Daily P&L chart
        pnl_chart = go.Figure(data=[
            go.Scatter(x=dates, y=pnl_values, mode='lines+markers', name='Daily P&L')
        ])
        pnl_chart.update_layout(title='Daily P&L (%)', xaxis_title='Date', yaxis_title='P&L %')
        pnl_chart_json = json.dumps(pnl_chart, cls=plotly.utils.PlotlyJSONEncoder)
        
        # Win/Loss chart
        wins = sum(1 for d in recent_decisions if d.get('action') == 'SELL' and d.get('pnl_pct', 0) > 0)
        losses = sum(1 for d in recent_decisions if d.get('action') == 'SELL' and d.get('pnl_pct', 0) < 0)
        
        winloss_chart = go.Figure(data=[
            go.Bar(x=['Wins', 'Losses'], y=[wins, losses], marker_color=['green', 'red'])
        ])
        winloss_chart.update_layout(title='Win/Loss Distribution')
        winloss_chart_json = json.dumps(winloss_chart, cls=plotly.utils.PlotlyJSONEncoder)
        
        # Cumulative returns
        cumulative = []
        total = 0
        for pnl in pnl_values:
            total += pnl
            cumulative.append(total)
        
        cumulative_chart = go.Figure(data=[
            go.Scatter(x=dates, y=cumulative, mode='lines', fill='tozeroy', name='Cumulative')
        ])
        cumulative_chart.update_layout(title='Cumulative Returns (%)', xaxis_title='Date', yaxis_title='Return %')
        cumulative_chart_json = json.dumps(cumulative_chart, cls=plotly.utils.PlotlyJSONEncoder)
        
        # Calculate stats
        sharpe = (sum(pnl_values) / len(pnl_values) / (pd.Series(pnl_values).std() + 0.001)) if pnl_values else 0
        max_drawdown = min(cumulative) if cumulative else 0
        
        # Average hold time
        hold_times = []
        for decision in recent_decisions:
            if decision.get('action') == 'SELL' and 'entry_time' in decision:
                try:
                    entry = datetime.fromisoformat(decision['entry_time'])
                    exit = datetime.fromisoformat(decision['timestamp'])
                    hold_times.append((exit - entry).total_seconds() / 3600)
                except Exception:
                    continue
        avg_hold_time = sum(hold_times) / len(hold_times) if hold_times else 0
        
        return render_template('performance.html',
                             pnl_chart=pnl_chart_json,
                             winloss_chart=winloss_chart_json,
                             cumulative_chart=cumulative_chart_json,
                             sharpe=sharpe,
                             max_drawdown=max_drawdown,
                             avg_hold_time=avg_hold_time)
    except Exception as e:
        logging.error(f"Error in performance route: {e}")
        return render_template('performance.html',
                             pnl_chart='{}',
                             winloss_chart='{}',
                             cumulative_chart='{}',
                             sharpe=0,
                             max_drawdown=0,
                             avg_hold_time=0)

@app.route('/positions')
def positions():
    """Current positions page"""
    try:
        positions_data = load_positions()
        
        # Fetch current prices and calculate P&L
        enriched_positions = []
        for pos in positions_data:
            ticker = pos.get('ticker')
            qty = pos.get('qty', 0)
            entry_price = pos.get('entry_price', 0)
            
            try:
                stock = yf.Ticker(ticker)
                current_price = stock.history(period='1d')['Close'].iloc[-1]
                pnl = (current_price - entry_price) * qty
                pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                
                enriched_positions.append({
                    'ticker': ticker,
                    'qty': qty,
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'entry_time': pos.get('entry_time', 'N/A')
                })
            except Exception as e:
                logging.warning(f"Could not fetch data for {ticker}: {e}")
                enriched_positions.append({
                    'ticker': ticker,
                    'qty': qty,
                    'entry_price': entry_price,
                    'current_price': entry_price,
                    'pnl': 0,
                    'pnl_pct': 0,
                    'entry_time': pos.get('entry_time', 'N/A')
                })
        
        return render_template('positions.html', positions=enriched_positions)
    except Exception as e:
        logging.error(f"Error in positions route: {e}")
        return render_template('positions.html', positions=[])

@app.route('/health')
def health():
    """System health page"""
    try:
        # Check circuit breaker
        circuit_breaker_status = "OK"
        try:
            risk_file = DATA_DIR / 'risk_status.json'
            if risk_file.exists():
                with open(risk_file, 'r') as f:
                    risk_data = json.load(f)
                    if risk_data.get('circuit_breaker_active'):
                        circuit_breaker_status = "TRIPPED"
        except Exception:
            circuit_breaker_status = "UNKNOWN"
        
        # Check API connectivity
        alpaca_status = "OK"
        try:
            # Simple check - in production, ping Alpaca API
            alpaca_status = "OK"
        except Exception:
            alpaca_status = "ERROR"
        
        ollama_status = "OK"
        try:
            # Simple check - in production, ping Ollama
            ollama_status = "OK"
        except Exception:
            ollama_status = "ERROR"
        
        # System metrics
        disk_usage = shutil.disk_usage('/')
        disk_free_gb = disk_usage.free / (1024**3)
        disk_total_gb = disk_usage.total / (1024**3)
        disk_pct = (disk_usage.used / disk_usage.total) * 100
        
        # Last run times
        screener_last_run = "N/A"
        sniper_last_run = "N/A"
        
        try:
            screener_log = Path('../logs/screener.log')
            if screener_log.exists():
                screener_last_run = datetime.fromtimestamp(screener_log.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
        
        try:
            sniper_log = Path('../logs/sniper.log')
            if sniper_log.exists():
                sniper_last_run = datetime.fromtimestamp(sniper_log.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
        
        return render_template('health.html',
                             circuit_breaker=circuit_breaker_status,
                             alpaca_status=alpaca_status,
                             ollama_status=ollama_status,
                             disk_free_gb=disk_free_gb,
                             disk_total_gb=disk_total_gb,
                             disk_pct=disk_pct,
                             screener_last_run=screener_last_run,
                             sniper_last_run=sniper_last_run)
    except Exception as e:
        logging.error(f"Error in health route: {e}")
        return render_template('health.html',
                             circuit_breaker="ERROR",
                             alpaca_status="ERROR",
                             ollama_status="ERROR",
                             disk_free_gb=0,
                             disk_total_gb=0,
                             disk_pct=0,
                             screener_last_run="N/A",
                             sniper_last_run="N/A")

@app.route('/logs')
def logs():
    """System logs page"""
    try:
        screener_logs = []
        sniper_logs = []
        
        # Read screener logs
        try:
            screener_log_file = Path('../logs/screener.log')
            if screener_log_file.exists():
                with open(screener_log_file, 'r') as f:
                    lines = f.readlines()
                    screener_logs = lines[-100:]  # Last 100 lines
        except Exception as e:
            logging.warning(f"Could not read screener logs: {e}")
        
        # Read sniper logs
        try:
            sniper_log_file = Path('../logs/sniper.log')
            if sniper_log_file.exists():
                with open(sniper_log_file, 'r') as f:
                    lines = f.readlines()
                    sniper_logs = lines[-100:]  # Last 100 lines
        except Exception as e:
            logging.warning(f"Could not read sniper logs: {e}")
        
        # Parse and color-code logs
        def parse_log_line(line):
            level = "INFO"
            if "WARNING" in line:
                level = "WARNING"
            elif "ERROR" in line:
                level = "ERROR"
            return {'text': line.strip(), 'level': level}
        
        screener_logs = [parse_log_line(line) for line in screener_logs]
        sniper_logs = [parse_log_line(line) for line in sniper_logs]
        
        return render_template('logs.html',
                             screener_logs=screener_logs,
                             sniper_logs=sniper_logs)
    except Exception as e:
        logging.error(f"Error in logs route: {e}")
        return render_template('logs.html',
                             screener_logs=[],
                             sniper_logs=[])

@app.route('/api/status')
def api_status():
    """API endpoint for external monitoring"""
    try:
        portfolio_value = get_portfolio_value()
        positions = load_positions()
        market_status = get_market_status()
        
        # Health checks
        circuit_breaker_active = False
        try:
            risk_file = DATA_DIR / 'risk_status.json'
            if risk_file.exists():
                with open(risk_file, 'r') as f:
                    risk_data = json.load(f)
                    circuit_breaker_active = risk_data.get('circuit_breaker_active', False)
        except Exception:
            pass
        
        return jsonify({
            'status': 'ok',
            'timestamp': datetime.now().isoformat(),
            'portfolio': {
                'value': portfolio_value,
                'positions': len(positions)
            },
            'market_status': 'open' if market_status else 'closed',
            'health': {
                'circuit_breaker_active': circuit_breaker_active
            }
        })
    except Exception as e:
        logging.error(f"Error in api_status route: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    # Create necessary directories
    DATA_DIR.mkdir(exist_ok=True)
    Path('../logs').mkdir(exist_ok=True)
    Path('templates').mkdir(exist_ok=True)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
