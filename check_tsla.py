from alpaca.trading.client import TradingClient
import os

with open('.env') as f:
    for line in f:
        if 'ALPACA' in line and not line.startswith('#'):
            key, val = line.strip().split('=', 1)
            os.environ[key] = val

client = TradingClient(
    os.getenv('ALPACA_API_KEY'),
    os.getenv('ALPACA_SECRET_KEY'),
    paper=True
)

positions = client.get_all_positions()

for pos in positions:
    if pos.symbol == 'TSLA':
        entry = float(pos.avg_entry_price)
        current = float(pos.current_price)
        pnl_pct = ((current - entry) / entry) * 100
        
        print("=" * 60)
        print("TSLA MONITOR CHECK")
        print("=" * 60)
        print(f"Entry: ${entry:.2f}")
        print(f"Current: ${current:.2f}")
        print(f"P&L: {pnl_pct:.2f}%")
        print(f"Stop loss: ${entry * 0.98:.2f}")
        print("=" * 60)
