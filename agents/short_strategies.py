import alpaca_trade_api as tradeapi

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
    Execute a short trade via Alpaca.
    
    Args:
        ticker (str): Stock ticker
        portfolio_value (float): Total portfolio value
    """
    api = tradeapi.REST('APCA-API-KEY-ID', 'APCA-API-SECRET-KEY', base_url='https://paper-api.alpaca.markets')
    position_size = 0.05 * portfolio_value
    # Placeholder for getting current price
    current_price = 100  # Example price
    stop_loss = current_price * 1.05
    target_price = current_price * 0.80
    
    # Execute short order
    api.submit_order(
        symbol=ticker,
        qty=position_size / current_price,
        side='sell',
        type='market',
        time_in_force='gtc'
    )
    # Set stop loss and target
    # Placeholder for setting stop loss and target

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
