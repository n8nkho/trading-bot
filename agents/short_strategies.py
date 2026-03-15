import os

def _trading_client():
    """Return Alpaca TradingClient if keys are set; else None (uses alpaca-py, same as orchestrator)."""
    try:
        from alpaca.trading.client import TradingClient
        key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
        secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
        if key and secret:
            return TradingClient(key, secret, paper=True)
    except Exception:
        pass
    return None


def find_overvalued_stocks():
    """
    Identify overvalued stocks for shorting.
    
    Criteria:
    - P/E ratio > 40
    - RSI > 70
    - Recent parabolic move (>50% in 3 months)
    
    Returns:
        list: Short candidates
    """
    # Placeholder for actual implementation
    short_candidates = []
    # Logic to find overvalued stocks goes here
    return short_candidates

def execute_short_trade(ticker, portfolio_value):
    """
    Execute a short trade via Alpaca (alpaca-py).

    Args:
        ticker (str): Stock ticker
        portfolio_value (float): Total portfolio value
    """
    client = _trading_client()
    if not client:
        return
    position_size = 0.05 * portfolio_value
    # Placeholder for getting current price
    current_price = 100  # Example price
    qty = max(1, int(position_size / current_price))
    try:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        req = MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
        )
        client.submit_order(req)
    except Exception:
        pass
    # Placeholder: set stop loss and target

def macro_short_strategy(macro_regime, portfolio_value):
    """
    Execute macro short strategy based on market regime.
    
    Args:
        macro_regime (str): Current macro regime ('BEAR' or 'BULL')
        portfolio_value (float): Total portfolio value
    
    Returns:
        list: Short recommendations
    """
    recommendations = []
    if macro_regime == 'BEAR':
        short_candidates = find_overvalued_stocks()
        for ticker in short_candidates:
            execute_short_trade(ticker, portfolio_value)
            recommendations.append(f"Short {ticker}")
        # Buy inverse ETFs like SQQQ
        recommendations.append("Buy SQQQ")
    elif macro_regime == 'BULL':
        recommendations.append("Skip shorting")
    
    return recommendations
