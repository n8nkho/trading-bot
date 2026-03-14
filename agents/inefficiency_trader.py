"""
Inefficiency Trader Agent (TEMPLATE ONLY).

EOD imbalance, options pinning, index rebalancing, after-hours overreaction,
and earnings whisper gaps require external data sources. Until configured,
returns empty list so run_strategies and main_loop do not break.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    filename="logs/inefficiency.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def inefficiency_strategy(portfolio_value: float = 10_000.0) -> List[Dict[str, Any]]:
    """
    Scan for market inefficiencies. TEMPLATE ONLY: no data source configured.
    Returns [] so callers get a consistent candidate list. Implement
    detect_eod_imbalance, scan_index_rebalancing, etc. with your data to enable.
    """
    logger.info(
        "Inefficiency strategy: template only (no EOD/rebalancing/options data source). "
        "Returning 0 candidates. See docstring to implement."
    )
    return []
