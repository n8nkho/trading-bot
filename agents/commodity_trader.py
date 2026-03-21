import os
import logging
import yfinance as yf
from agents.vix_insurance import get_current_vix

# Instrument/ticker config (no hard-coded ticker literals).
from utils.market_assets import require_market_assets

# Constants (non-ticker numeric defaults; actual instruments come from config)
COMMODITY_ALLOCATION_PCT = 0.08  # 8% of portfolio
USD_STRENGTH_THRESHOLD = 95  # DXY level

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    # Optional dependency: forex/commodity hedging should not crash the bot
    # if OANDA libs aren't installed.
    from oandapyV20 import API  # type: ignore
    from oandapyV20.endpoints.pricing import PricingInfo  # type: ignore
    _OANDA_AVAILABLE = True
except ModuleNotFoundError:
    API = None  # type: ignore
    PricingInfo = None  # type: ignore
    _OANDA_AVAILABLE = False


def _get_oanda_api():
    """Create an OANDA API client (returns None if unavailable/misconfigured)."""
    if not _OANDA_AVAILABLE:
        return None
    token = os.getenv("OANDA_API_KEY")
    if not token:
        return None
    return API(access_token=token)

def get_usd_strength():
    try:
        assets = require_market_assets()
        usd_strength_ticker = (assets.get("commodity_trader") or {}).get("usd_strength_ticker")
        if not usd_strength_ticker:
            return None
        dxy = yf.Ticker(usd_strength_ticker)
        dxy_price = dxy.history(period="1d")['Close'].iloc[-1]
        return float(dxy_price)
    except Exception as e:
        logger.error(f"Failed to get USD strength: {e}")
        return None

def get_gold_price():
    try:
        if not _OANDA_AVAILABLE:
            return None

        oanda_api = _get_oanda_api()
        if oanda_api is None:
            return None

        account_id = os.getenv("OANDA_ACCOUNT_ID")
        if not account_id:
            return None

        assets = require_market_assets()
        gold_pair_instrument = (assets.get("commodity_trader") or {}).get("gold_pair_instrument")
        if not gold_pair_instrument:
            return None

        params = {"instruments": gold_pair_instrument}
        r = PricingInfo(accountID=account_id, params=params)
        response = oanda_api.request(r)
        gold_price = float(response['prices'][0]['bids'][0]['price'])
        return gold_price
    except Exception as e:
        logger.error(f"Failed to get gold price: {e}")
        return None

def get_silver_price():
    try:
        if not _OANDA_AVAILABLE:
            return None

        oanda_api = _get_oanda_api()
        if oanda_api is None:
            return None

        account_id = os.getenv("OANDA_ACCOUNT_ID")
        if not account_id:
            return None

        assets = require_market_assets()
        silver_pair_instrument = (assets.get("commodity_trader") or {}).get("silver_pair_instrument")
        if not silver_pair_instrument:
            return None

        params = {"instruments": silver_pair_instrument}
        r = PricingInfo(accountID=account_id, params=params)
        response = oanda_api.request(r)
        silver_price = float(response['prices'][0]['bids'][0]['price'])
        return silver_price
    except Exception as e:
        logger.error(f"Failed to get silver price: {e}")
        return None

def should_buy_commodities(usd_strength, vix_level):
    assets = require_market_assets()
    commodity_cfg = assets.get("commodity_trader") or {}
    gold_label = commodity_cfg.get("gold_label")
    silver_label = commodity_cfg.get("silver_label")
    if not gold_label or not silver_label:
        return "HOLD", "Commodity strategy disabled (missing gold/silver labels in config/market_assets.json)"

    if usd_strength is None:
        return "HOLD", "USD strength data unavailable"
    
    usd_strength_threshold = commodity_cfg.get("usd_strength_threshold", USD_STRENGTH_THRESHOLD)

    if usd_strength < 90:
        return "BUY_BOTH", "USD very weak (DXY < 90)"
    elif usd_strength < usd_strength_threshold and vix_level > 25:
        return f"BUY_{gold_label}", "USD weak and VIX > 25"
    elif usd_strength < usd_strength_threshold and vix_level > 20:
        return f"BUY_{gold_label}", "USD weak and VIX > 20"
    elif usd_strength < usd_strength_threshold and vix_level < 25:
        return f"BUY_{silver_label}", "USD weak and VIX < 25 (industrial demand)"
    else:
        return "HOLD", "No favorable conditions"

def calculate_commodity_position(portfolio_value, commodity_type):
    allocation = portfolio_value * COMMODITY_ALLOCATION_PCT
    assets = require_market_assets()
    commodity_cfg = assets.get("commodity_trader") or {}
    gold_label = commodity_cfg.get("gold_label")
    silver_label = commodity_cfg.get("silver_label")
    gold_pair_instrument = commodity_cfg.get("gold_pair_instrument")
    silver_pair_instrument = commodity_cfg.get("silver_pair_instrument")
    if not gold_label or not silver_label:
        return None

    if commodity_type == gold_label:
        gold_price = get_gold_price()
        if gold_price is None:
            return None
        lot_size = allocation / gold_price
        stop_price = gold_price * 0.99
        target_price = gold_price * 1.02
        return {
            'pair': gold_pair_instrument,
            'direction': 'BUY',
            'lot_size': lot_size,
            'stop_price': stop_price,
            'target_price': target_price
        }
    elif commodity_type == silver_label:
        silver_price = get_silver_price()
        if silver_price is None:
            return None
        lot_size = allocation / silver_price
        stop_price = silver_price * 0.98
        target_price = silver_price * 1.04
        return {
            'pair': silver_pair_instrument,
            'direction': 'BUY',
            'lot_size': lot_size,
            'stop_price': stop_price,
            'target_price': target_price
        }
    return None

def commodity_hedge_strategy(portfolio_value):
    assets = require_market_assets()
    commodity_cfg = assets.get("commodity_trader") or {}
    gold_label = commodity_cfg.get("gold_label")
    silver_label = commodity_cfg.get("silver_label")
    if not gold_label or not silver_label:
        return {"action": "HOLD", "reason": "Commodity strategy disabled (missing gold/silver labels in config/market_assets.json)"}

    usd_strength = get_usd_strength()
    vix_level = get_current_vix()
    action, reasoning = should_buy_commodities(usd_strength, vix_level)
    logger.info(f"Decision: {action}, Reason: {reasoning}")

    if action == f"BUY_{gold_label}":
        position = calculate_commodity_position(portfolio_value, gold_label)
        if position is None:
            return {'action': 'HOLD', 'reason': 'Gold price unavailable'}
        logger.info(f"Gold position: {position}")
        return {'action': 'INCREASE', 'reason': reasoning, 'positions': [position]}

    if action == f"BUY_{silver_label}":
        position = calculate_commodity_position(portfolio_value, silver_label)
        if position is None:
            return {'action': 'HOLD', 'reason': 'Silver price unavailable'}
        logger.info(f"Silver position: {position}")
        return {'action': 'INCREASE', 'reason': reasoning, 'positions': [position]}

    if action == "BUY_BOTH":
        gold_position = calculate_commodity_position(portfolio_value / 2, gold_label)
        silver_position = calculate_commodity_position(portfolio_value / 2, silver_label)
        positions = []
        if gold_position:
            positions.append(gold_position)
        if silver_position:
            positions.append(silver_position)
        if not positions:
            return {'action': 'HOLD', 'reason': 'Commodity pricing unavailable'}
        logger.info(f"Commodities positions: {positions}")
        return {'action': 'INCREASE', 'reason': reasoning, 'positions': positions}

    return {'action': 'HOLD', 'reason': reasoning}
