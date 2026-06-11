"""
Document Analyst Agent — quick fundamental gate for orchestrator entry path.
"""

import logging

logger = logging.getLogger(__name__)


def quick_fundamental_check(ticker, confidence):
    """
    Quick fundamental analysis check for high-confidence candidates.

    Simplified placeholder until full SEC filing analysis is wired.
    """
    logger.info(f"{ticker}: Running quick fundamental check (confidence: {confidence:.2f})")

    try:
        logger.info(f"{ticker}: Fundamental analysis not fully implemented - using placeholder")

        return {
            "fundamental_approved": True,
            "adjusted_confidence": confidence,
            "risk_score": None,
            "analysis": None,
            "cost": 0,
            "reason": "Fundamental analysis placeholder - full SEC filing analysis not yet implemented",
        }

    except Exception as e:
        logger.error(f"{ticker}: Error in fundamental check: {type(e).__name__}: {str(e)}")
        return {
            "fundamental_approved": False,
            "adjusted_confidence": confidence * 0.9,
            "risk_score": None,
            "analysis": None,
            "cost": 0,
            "reason": f"Fundamental check error: {str(e)}",
        }
