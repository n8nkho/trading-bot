import logging

import yfinance as yf

from agents.commodity_trader import get_usd_strength
from agents.vix_insurance import get_current_vix
from utils.market_assets import require_market_assets

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Keep forex hedges small and conservative.
FOREX_ALLOCATION_PCT = 0.03


def forex_hedge_strategy(portfolio_value):
    """
    Produce a conservative FX hedging recommendation (recommendations-only).

    This module is intentionally safe: it never raises if market data is missing.
    It returns a structured dict for fortress dashboard/reporting.
    """
    try:
        usd_strength = get_usd_strength()
        vix_level = get_current_vix()

        if usd_strength is None or vix_level is None:
            return {'action': 'HOLD', 'reason': 'USD strength or VIX unavailable'}

        assets = require_market_assets()
        fx_proxy_ticker = (assets.get("forex_hedger") or {}).get("fx_proxy_ticker")
        pair_label = (assets.get("forex_hedger") or {}).get("pair_label")
        if not fx_proxy_ticker or not pair_label:
            return {'action': 'HOLD', 'reason': 'FX hedge disabled (missing forex_hedger config)'}

        # Use configured FX proxy ticker as a simple risk proxy for USD strength.
        fx_proxy = yf.Ticker(fx_proxy_ticker).history(period="1d")["Close"].iloc[-1]
        fx_proxy = float(fx_proxy)

        notional = portfolio_value * FOREX_ALLOCATION_PCT

        # Conservative directional rule-set.
        # - Strong USD: hedge by shorting the configured FX pair.
        # - Weak USD: hedge by longing the configured FX pair.
        if usd_strength >= 100 and vix_level >= 20:
            direction = "SHORT"
            reason = f"USD strong (DXY={usd_strength:.2f}) and VIX elevated ({vix_level:.2f})"
        elif usd_strength <= 92 and vix_level >= 20:
            direction = "LONG"
            reason = f"USD weak (DXY={usd_strength:.2f}) and VIX elevated ({vix_level:.2f})"
        else:
            return {
                'action': 'HOLD',
                'reason': f"No strong FX hedge signal (DXY={usd_strength:.2f}, VIX={vix_level:.2f})"
            }

        # Place symmetric stop/target levels (~0.5% / ~1.0%) to reduce downside.
        # These are guidance fields for later execution logic.
        stop_long = float((assets.get("forex_hedger") or {}).get("stop_long_multiplier", 0.995))
        stop_short = float((assets.get("forex_hedger") or {}).get("stop_short_multiplier", 1.005))
        target_long = float((assets.get("forex_hedger") or {}).get("target_long_multiplier", 1.01))
        target_short = float((assets.get("forex_hedger") or {}).get("target_short_multiplier", 0.99))

        stop = fx_proxy * (stop_long if direction == "LONG" else stop_short)
        target = fx_proxy * (target_long if direction == "LONG" else target_short)

        return {
            'action': 'INCREASE',
            'reason': reason,
            'allocation_pct': FOREX_ALLOCATION_PCT,
            'positions': [
                {
                    'pair': pair_label,
                    'direction': direction,
                    'notional': notional,
                    'entry_rate': fx_proxy,
                    'stop_rate': stop,
                    'target_rate': target,
                }
            ],
        }
    except Exception as e:
        logger.error(f"Error in forex_hedge_strategy: {type(e).__name__}: {str(e)}")
        return {'action': 'HOLD', 'reason': f'Error generating FX hedge: {type(e).__name__}'}

