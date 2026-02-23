from agents.vix_insurance import get_current_vix, should_buy_insurance, calculate_insurance_position
from agents.bond_manager import get_market_regime, calculate_bond_target
from agents.commodity_trader import get_usd_strength, commodity_hedge_strategy
from agents.theta_spreads import theta_strategy
from agents.dividend_capture import dividend_capture_strategy
from agents.pairs_trader import pairs_trading_strategy, analyze_all_pairs
from alpaca.trading.client import TradingClient
import os
import json
import logging
from datetime import datetime

# Constants
BUDGET_MODE = True  # Set False when can afford VIX
RISK_ON_ALLOCATION = {
    'stocks': 0.30,
    'options': 0.10,
    'bonds': 0.15,
    'forex': 0.15,
    'commodities': 0.05,
    'vix_insurance': 0.01,
    'theta_spreads': 0.05,
    'dividend': 0.10,
    'pairs': 0.09
}

RISK_OFF_ALLOCATION = {
    'stocks': 0.15,
    'options': 0.05,
    'bonds': 0.35,
    'forex': 0.15,
    'commodities': 0.15,
    'vix_insurance': 0.03,
    'theta_spreads': 0.02,
    'dividend': 0.05,
    'pairs': 0.05
}

NEUTRAL_ALLOCATION = {
    'stocks': 0.25,
    'options': 0.08,
    'bonds': 0.25,
    'forex': 0.15,
    'commodities': 0.08,
    'vix_insurance': 0.02,
    'theta_spreads': 0.04,
    'dividend': 0.08,
    'pairs': 0.05
}

BUDGET_RISK_OFF_ALLOCATION = {
    'stocks': 0.15,
    'options': 0.05,
    'bonds': 0.40,  # Increased from 35%
    'forex': 0.15,
    'commodities': 0.17,  # Increased from 15%
    'theta_spreads': 0.02,
    'dividend': 0.05,
    'pairs': 0.08  # Increased from 5%
    # No VIX insurance!
}
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_portfolio_status():
    """Connect to Alpaca and get portfolio status."""
    client = TradingClient(os.getenv('APCA_API_KEY_ID'), os.getenv('APCA_API_SECRET_KEY'))
    account = client.get_account()
    positions = client.get_all_positions()
    total_value = float(account.equity)
    return {
        'balance': float(account.cash),
        'positions': positions,
        'total_value': total_value
    }

def assess_market_conditions():
    """Assess current market conditions."""
    vix = get_current_vix()
    regime = get_market_regime()
    usd_strength = get_usd_strength()
    assessment = "Neutral"  # Placeholder for more complex logic
    return {
        'vix': vix,
        'regime': regime,
        'usd_strength': usd_strength,
        'assessment': assessment
    }

def get_target_allocation(market_regime):
    """Get target allocation based on market regime."""
    if market_regime == 'RISK_ON':
        return RISK_ON_ALLOCATION
    elif market_regime == 'RISK_OFF':
        return RISK_OFF_ALLOCATION
    else:
        return NEUTRAL_ALLOCATION

def run_all_hedge_strategies(portfolio_value):
    """Run all hedge strategies and collect recommendations."""
    recommendations = {}
    try:
        if BUDGET_MODE:
            # Skip VIX insurance
            recommendations['vix_insurance'] = {'action': 'SKIP', 'reason': 'Budget mode - using other hedges'}
            
            # Increase other hedges to compensate:
            # - Increase bond allocation by 5%
            # - Increase pairs trading by 3%
            # - Increase commodity hedge by 2%
            recommendations['bonds'] = {'target': calculate_bond_target(portfolio_value, get_market_regime()) * 1.05}
            recommendations['pairs_trading'] = {'action': 'INCREASE', 'reason': 'Budget mode - increased allocation'}
            recommendations['commodities'] = {'action': 'INCREASE', 'reason': 'Budget mode - increased allocation'}
        else:
            # VIX Insurance
            should_buy, reason = should_buy_insurance(portfolio_value, get_current_vix())
            if should_buy:
                insurance = calculate_insurance_position(portfolio_value)
                recommendations['vix_insurance'] = insurance
            else:
                recommendations['vix_insurance'] = {'action': 'HOLD', 'reason': reason}

        # Bonds
        recommendations['bonds'] = {'target': calculate_bond_target(portfolio_value, get_market_regime())}

        # Commodities
        result = commodity_hedge_strategy(portfolio_value)
        if isinstance(result, tuple):
            action, reason = result
            recommendations['commodities'] = {'action': action, 'reason': reason}
        else:
            recommendations['commodities'] = result

        # Theta Spreads
        result = theta_strategy(portfolio_value)
        recommendations['theta_spreads'] = result or {'action': 'NONE'}

        # Dividend Capture
        result = dividend_capture_strategy(portfolio_value)
        recommendations['dividend_capture'] = result or {'action': 'NONE'}

        # Pairs Trading
        result = pairs_trading_strategy(portfolio_value)
        recommendations['pairs_trading'] = result or {'action': 'NONE'}

    except Exception as e:
        logging.error(f"Error running hedge strategies: {e}")
    return recommendations

def generate_fortress_report(portfolio_value):
    """Generate a comprehensive fortress report."""
    market_conditions = assess_market_conditions()
    target_allocations = get_target_allocation(market_conditions['regime'])
    strategies = run_all_hedge_strategies(portfolio_value)
    report = {
        'market_conditions': market_conditions,
        'target_allocations': target_allocations,
        'strategies': strategies
    }
    report_note = "Budget mode: Using stop losses + diversification instead of VIX insurance"
    report['note'] = report_note
    return json.dumps(report, indent=4)

def fortress_daily_check():
    """Perform daily check and generate report."""
    portfolio_status = get_portfolio_status()
    recommendations = run_all_hedge_strategies(portfolio_status['total_value'])
    report = generate_fortress_report(portfolio_status['total_value'])
    report_filename = f"data/fortress_report_{datetime.now().strftime('%Y%m%d')}.json"
    with open(report_filename, 'w') as report_file:
        report_file.write(report)
    logging.info(f"Daily fortress report saved to {report_filename}")
    print(report)
    return recommendations

def fortress_weekly_rebalance():
    """Perform weekly portfolio rebalance."""
    portfolio_status = get_portfolio_status()
    current_allocations = {}  # Placeholder for actual calculation
    target_allocations = get_target_allocation(assess_market_conditions()['regime'])
    rebalance_plan = {}  # Placeholder for actual rebalance logic
    logging.info("Weekly rebalance plan generated.")
    return rebalance_plan
