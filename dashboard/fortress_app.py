import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, render_template
from flask_cors import CORS
import json
import os
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from agents.fortress_orchestrator import assess_market_conditions, get_portfolio_status
import glob

app = Flask(__name__)
CORS(app)

def get_all_trades():
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(project_root, 'data', 'decisions_log.jsonl'), 'r') as file:
            trades = [json.loads(line) for line in file]
        return trades
    except FileNotFoundError:
        return []

def get_strategy_performance():
    trades = get_all_trades()
    performance = {}
    for trade in trades:
        strategy = trade.get('strategy', 'Unknown')
        if strategy not in performance:
            performance[strategy] = {'pnl': 0, 'trades': 0, 'wins': 0}
        performance[strategy]['pnl'] += trade.get('pnl', 0)
        performance[strategy]['trades'] += 1
        if trade.get('pnl', 0) > 0:
            performance[strategy]['wins'] += 1
    for strategy, data in performance.items():
        data['win_rate'] = (data['wins'] / data['trades']) * 100 if data['trades'] > 0 else 0
    return performance

def get_platform_breakdown():
    # Placeholder for platform breakdown logic
    return {}

def get_portfolio_summary():
    # Placeholder for portfolio summary logic
    return {}

def get_equity_curve():
    # Placeholder for equity curve logic
    return []

def get_recent_activity():
    trades = get_all_trades()
    return trades[-20:]

@app.route('/')
def index():
    return render_template('fortress_dashboard.html')

@app.route('/api/summary')
def api_summary():
    return jsonify({
        'portfolio': get_portfolio_summary(),
        'strategies': get_strategy_performance(),
        'platforms': get_platform_breakdown(),
        'market': assess_market_conditions()
    })

@app.route('/api/equity')
def api_equity():
    return jsonify(get_equity_curve())

@app.route('/api/trades')
def api_trades():
    return jsonify(get_all_trades())

@app.route('/api/activity')
def api_activity():
    return jsonify(get_recent_activity())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
