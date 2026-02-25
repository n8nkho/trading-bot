import yfinance as yf

def detect_trend(ticker):
    """
    Detects the trend direction based on moving averages.

    Args:
        ticker (str): The stock ticker symbol.

    Returns:
        str: 'uptrend' if 50MA is above 200MA, 'downtrend' if 50MA is below 200MA.
    """
    data = yf.download(ticker, period='1y')
    data['50MA'] = data['Close'].rolling(window=50).mean()
    data['200MA'] = data['Close'].rolling(window=200).mean()

    if data['50MA'].iloc[-1] > data['200MA'].iloc[-1]:
        return 'uptrend'
    elif data['50MA'].iloc[-1] < data['200MA'].iloc[-1]:
        return 'downtrend'
    else:
        return 'no trend'

def trend_entry(ticker, portfolio_value):
    """
    Executes a buy when the 50MA crosses above the 200MA or on pullbacks to 50MA in an uptrend.

    Args:
        ticker (str): The stock ticker symbol.
        portfolio_value (float): The total value of the portfolio.

    Returns:
        dict: Details of the entry trade.
    """
    data = yf.download(ticker, period='1y')
    data['50MA'] = data['Close'].rolling(window=50).mean()
    data['200MA'] = data['Close'].rolling(window=200).mean()

    position_size = 0.1 * portfolio_value
    stop_loss = data['50MA'].iloc[-1]

    if data['50MA'].iloc[-1] > data['200MA'].iloc[-1] and data['Close'].iloc[-1] > data['50MA'].iloc[-1]:
        return {'action': 'buy', 'position_size': position_size, 'stop_loss': stop_loss}
    elif data['Close'].iloc[-1] < data['50MA'].iloc[-1] and data['50MA'].iloc[-1] > data['200MA'].iloc[-1]:
        return {'action': 'buy on pullback', 'position_size': position_size, 'stop_loss': stop_loss}
    else:
        return {'action': 'hold'}

def trend_exit(ticker):
    """
    Determines when to exit the position based on moving averages.

    Args:
        ticker (str): The stock ticker symbol.

    Returns:
        dict: Details of the exit trade.
    """
    data = yf.download(ticker, period='1y')
    data['50MA'] = data['Close'].rolling(window=50).mean()
    data['200MA'] = data['Close'].rolling(window=200).mean()

    if data['50MA'].iloc[-1] < data['200MA'].iloc[-1] or data['Close'].iloc[-1] < data['50MA'].iloc[-1]:
        return {'action': 'sell', 'stop_loss': data['50MA'].iloc[-1]}
    else:
        return {'action': 'hold'}
