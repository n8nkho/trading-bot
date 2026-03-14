"""
Lightweight S&P 500 / liquid universe ticker list.

Use this module instead of importing from agents.screener_agent to avoid
pulling in heavy dependencies (vision_analyst, scipy). Used by earnings_drift,
vwap_reversion, insider_tracker, defensive_universe_scanner, and screener_agent.
"""

from __future__ import annotations


def get_sp500_tickers() -> list[str]:
    """
    Return a list of liquid S&P 500–style tickers (top names + ETFs).
    Single source of truth for agents that need a universe without loading the screener.
    """
    return [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "BRK.B",
        "UNH", "XOM", "JNJ", "JPM", "V", "PG", "MA", "HD", "CVX", "MRK",
        "ABBV", "KO", "AVGO", "PEP", "COST", "TMO", "MCD", "CSCO", "ACN",
        "LLY", "DHR", "ABT", "NKE", "DIS", "TXN", "VZ", "ADBE", "WMT",
        "CRM", "NFLX", "ORCL", "AMD", "INTC", "CMCSA", "PFE", "PM", "BA",
        "QCOM", "T", "UNP", "HON", "IBM", "GE", "INTU", "SBUX", "CAT",
        "PLTR", "COIN", "HOOD", "SOFI", "RIVN", "LCID", "NIO",
        "SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "HYG", "LQD",
        "MS", "GS", "BAC", "WFC", "C", "BLK", "SCHW", "AXP",
        "AMGN", "GILD", "BIIB", "REGN", "VRTX", "ISRG", "MDT", "BMY",
        "F", "GM", "UBER", "LYFT", "ABNB", "DASH", "SNAP", "PINS",
        "ZM", "DDOG", "NET", "SNOW", "MDB", "BILL", "CRWD", "PANW",
    ]
