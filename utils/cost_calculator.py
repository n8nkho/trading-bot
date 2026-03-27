#!/usr/bin/env python3
"""
Comprehensive cost tracking and analysis system.
Tracks API costs, OCI infrastructure, and provides detailed reporting.
"""
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

# API Pricing (per 1M tokens)
PRICING = {
    'anthropic': {
        'claude-haiku': {'input': 0.25, 'output': 1.25},
        'claude-sonnet': {'input': 3.0, 'output': 15.0},
    },
    'grok': {
        'grok-mini': {'input': 0.15, 'output': 0.60},
    },
    'deepseek': {
        # Pricing from user-provided DeepSeek sheet (USD per 1M tokens).
        # Input cache-hit is modeled via cached_tokens + CACHE_DISCOUNT=90%.
        'deepseek-chat': {'input': 0.28, 'output': 0.42},
        'deepseek-reasoner': {'input': 0.28, 'output': 0.42},
    },
    'ollama': {
        'llama3.1:8b': {'input': 0.0, 'output': 0.0},  # FREE
        'llama3.2:3b': {'input': 0.0, 'output': 0.0},  # FREE
        'deepseek-r1:14b': {'input': 0.0, 'output': 0.0},  # FREE local
    }
}

# Cache discount (90% off cached tokens)
CACHE_DISCOUNT = 0.90

# OCI Free Tier Limits (A1.Flex ARM)
OCI_FREE_TIER = {
    'compute_ocpu': 4,
    'compute_ram_gb': 24,
    'storage_gb': 200,
    'network_tb': 10,
}

DATA_DIR = Path('data')
API_COSTS_FILE = DATA_DIR / 'api_costs.jsonl'
OCI_COSTS_FILE = DATA_DIR / 'oci_costs.jsonl'


def ensure_data_dir():
    """Ensure data directory exists."""
    DATA_DIR.mkdir(exist_ok=True)


def track_api_cost(service, model, input_tokens, output_tokens, cached_tokens=0):
    """
    Track API cost for a single call.
    
    Args:
        service: 'anthropic', 'grok', or 'ollama'
        model: Model name (e.g., 'claude-haiku', 'grok-mini', 'llama3.1:8b')
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        cached_tokens: Number of cached input tokens (default 0)
    
    Returns:
        dict: Cost breakdown with savings
    """
    ensure_data_dir()
    
    # Get pricing for this service/model
    if service not in PRICING or model not in PRICING[service]:
        raise ValueError(f"Unknown service/model: {service}/{model}")
    
    pricing = PRICING[service][model]
    
    # Calculate cost without cache
    input_cost_full = (input_tokens / 1_000_000) * pricing['input']
    output_cost = (output_tokens / 1_000_000) * pricing['output']
    cost_without_cache = input_cost_full + output_cost
    
    # Calculate cost with cache (90% discount on cached tokens)
    uncached_tokens = input_tokens - cached_tokens
    input_cost_uncached = (uncached_tokens / 1_000_000) * pricing['input']
    input_cost_cached = (cached_tokens / 1_000_000) * pricing['input'] * (1 - CACHE_DISCOUNT)
    cost_with_cache = input_cost_uncached + input_cost_cached + output_cost
    
    savings = cost_without_cache - cost_with_cache
    
    # Create record
    record = {
        'timestamp': datetime.now().isoformat(),
        'service': service,
        'model': model,
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'cached_tokens': cached_tokens,
        'cost_without_cache': round(cost_without_cache, 6),
        'cost_with_cache': round(cost_with_cache, 6),
        'savings': round(savings, 6),
    }
    
    # Append to log
    with open(API_COSTS_FILE, 'a') as f:
        f.write(json.dumps(record) + '\n')
    
    return record


def track_oci_cost(compute_hours=24, storage_gb=50, network_gb=1):
    """
    Track OCI infrastructure costs (always $0 for free tier).
    
    Args:
        compute_hours: Hours of compute used (default 24)
        storage_gb: GB of storage used (default 50)
        network_gb: GB of network transfer (default 1)
    
    Returns:
        dict: Cost breakdown (all $0 for free tier)
    """
    ensure_data_dir()
    
    # Check if within free tier limits
    within_limits = (
        storage_gb <= OCI_FREE_TIER['storage_gb'] and
        network_gb <= (OCI_FREE_TIER['network_tb'] * 1024)
    )
    
    # OCI A1.Flex ARM is FREE tier
    record = {
        'timestamp': datetime.now().isoformat(),
        'compute_hours': compute_hours,
        'storage_gb': storage_gb,
        'network_gb': network_gb,
        'compute_cost': 0.0,
        'storage_cost': 0.0,
        'network_cost': 0.0,
        'total_cost': 0.0,
        'within_free_tier': within_limits,
    }
    
    # Append to log
    with open(OCI_COSTS_FILE, 'a') as f:
        f.write(json.dumps(record) + '\n')
    
    return record


def get_daily_costs(date=None):
    """
    Get costs for a specific day.
    
    Args:
        date: datetime.date object (default: today)
    
    Returns:
        dict: Daily cost breakdown
    """
    if date is None:
        date = datetime.now().date()
    
    api_calls = 0
    total_api_cost = 0.0
    api_savings = 0.0
    service_breakdown = {}
    
    # Load API costs
    if API_COSTS_FILE.exists():
        with open(API_COSTS_FILE) as f:
            for line in f:
                record = json.loads(line)
                record_date = datetime.fromisoformat(record['timestamp']).date()
                
                if record_date == date:
                    api_calls += 1
                    total_api_cost += record['cost_with_cache']
                    api_savings += record['savings']
                    
                    service = record['service']
                    if service not in service_breakdown:
                        service_breakdown[service] = {
                            'calls': 0,
                            'cost': 0.0,
                            'savings': 0.0,
                        }
                    service_breakdown[service]['calls'] += 1
                    service_breakdown[service]['cost'] += record['cost_with_cache']
                    service_breakdown[service]['savings'] += record['savings']
    
    # OCI is always free
    oci_cost = 0.0
    
    return {
        'date': date.isoformat(),
        'api_calls': api_calls,
        'api_cost': round(total_api_cost, 4),
        'api_savings': round(api_savings, 4),
        'oci_cost': oci_cost,
        'total_cost': round(total_api_cost + oci_cost, 4),
        'service_breakdown': service_breakdown,
    }


def get_monthly_projection():
    """
    Project monthly costs based on recent activity.
    
    Returns:
        dict: Monthly projection with breakdown
    """
    # Get last 7 days of data
    today = datetime.now().date()
    daily_costs = []
    
    for i in range(7):
        date = today - timedelta(days=i)
        costs = get_daily_costs(date)
        if costs['api_calls'] > 0:
            daily_costs.append(costs['total_cost'])
    
    if not daily_costs:
        return {
            'daily_average': 0.0,
            'monthly_projection': 0.0,
            'api_projection': 0.0,
            'oci_projection': 0.0,
            'days_sampled': 0,
        }
    
    # Calculate average
    daily_avg = sum(daily_costs) / len(daily_costs)
    monthly_projection = daily_avg * 30
    
    return {
        'daily_average': round(daily_avg, 4),
        'monthly_projection': round(monthly_projection, 2),
        'api_projection': round(monthly_projection, 2),  # All API for now
        'oci_projection': 0.0,  # Always free
        'days_sampled': len(daily_costs),
    }


def get_lifetime_costs():
    """
    Get lifetime cost statistics.
    
    Returns:
        dict: Lifetime cost breakdown
    """
    total_spent = 0.0
    total_saved = 0.0
    total_calls = 0
    first_call = None
    last_call = None
    
    if API_COSTS_FILE.exists():
        with open(API_COSTS_FILE) as f:
            for line in f:
                record = json.loads(line)
                total_calls += 1
                total_spent += record['cost_with_cache']
                total_saved += record['savings']
                
                timestamp = datetime.fromisoformat(record['timestamp'])
                if first_call is None or timestamp < first_call:
                    first_call = timestamp
                if last_call is None or timestamp > last_call:
                    last_call = timestamp
    
    # Calculate ROI (savings / spent)
    roi = (total_saved / total_spent * 100) if total_spent > 0 else 0
    
    # Days active
    days_active = 0
    if first_call and last_call:
        days_active = (last_call - first_call).days + 1
    
    return {
        'total_spent': round(total_spent, 2),
        'total_saved': round(total_saved, 2),
        'total_calls': total_calls,
        'roi_percent': round(roi, 1),
        'days_active': days_active,
        'first_call': first_call.isoformat() if first_call else None,
        'last_call': last_call.isoformat() if last_call else None,
    }


def get_cost_per_trade():
    """
    Calculate average cost per trade.
    
    Returns:
        float: Average cost per trade
    """
    # Load decisions log to count trades
    decisions_file = DATA_DIR / 'decisions_log.jsonl'
    trade_count = 0
    
    if decisions_file.exists():
        with open(decisions_file) as f:
            for line in f:
                record = json.loads(line)
                if record.get('action') in ['BUY', 'SELL']:
                    trade_count += 1
    
    lifetime = get_lifetime_costs()
    
    if trade_count > 0:
        return round(lifetime['total_spent'] / trade_count, 4)
    return 0.0


def generate_cost_report():
    """
    Generate comprehensive cost report.
    
    Returns:
        str: Formatted cost report
    """
    today_costs = get_daily_costs()
    monthly = get_monthly_projection()
    lifetime = get_lifetime_costs()
    cost_per_trade = get_cost_per_trade()
    
    report = []
    report.append("━" * 60)
    report.append("💰 COMPREHENSIVE COST ANALYSIS")
    report.append("━" * 60)
    report.append("")
    
    # TODAY
    report.append("TODAY:")
    report.append(f"  API Calls: {today_costs['api_calls']}")
    
    for service, data in today_costs['service_breakdown'].items():
        service_name = service.capitalize()
        if service == 'ollama':
            report.append(f"  - {service_name}: $0.00 (FREE) ({data['calls']} calls)")
        else:
            report.append(f"  - {service_name}: ${data['cost']:.2f} ({data['calls']} calls)")
    
    if today_costs['api_savings'] > 0:
        cache_pct = (today_costs['api_savings'] / (today_costs['api_cost'] + today_costs['api_savings'])) * 100
        report.append(f"  Cache savings: ${today_costs['api_savings']:.2f} ({cache_pct:.0f}%)")
    
    report.append(f"  OCI: $0.00 (FREE tier)")
    report.append(f"  TOTAL: ${today_costs['total_cost']:.2f}")
    report.append("")
    
    # MONTH
    report.append("MONTH (projected):")
    report.append(f"  API: ${monthly['api_projection']:.2f}")
    report.append(f"  OCI: $0.00")
    report.append(f"  TOTAL: ${monthly['monthly_projection']:.2f}/month")
    report.append(f"  (based on {monthly['days_sampled']} day average)")
    report.append("")
    
    # LIFETIME
    report.append("LIFETIME:")
    report.append(f"  Total spent: ${lifetime['total_spent']:.2f}")
    report.append(f"  Total saved: ${lifetime['total_saved']:.2f} (via caching)")
    if cost_per_trade > 0:
        report.append(f"  Cost per trade: ${cost_per_trade:.2f}")
    report.append(f"  ROI: {lifetime['roi_percent']:.0f}%")
    report.append(f"  Days active: {lifetime['days_active']}")
    report.append("")
    
    report.append("━" * 60)
    
    return "\n".join(report)


if __name__ == '__main__':
    # Test the system
    print(generate_cost_report())
