"""
Calendar Bias Overlay
Adjusts signal confidence based on known calendar anomalies.
Multiplier > 1.0 = bullish tailwind. < 1.0 = headwind. 1.0 = neutral.
"""
import logging
import calendar as cal
from datetime import date, datetime
import pytz

logger = logging.getLogger(__name__)
ET = pytz.timezone("US/Eastern")


def get_calendar_bias(signal_date=None):
    """
    Returns confidence multiplier and active effects for the given date.
    """
    if signal_date is None:
        signal_date = datetime.now(ET).date()

    day_of_week = signal_date.weekday()  # 0=Mon, 4=Fri
    month = signal_date.month
    dom = signal_date.day
    last_day = cal.monthrange(signal_date.year, month)[1]

    effects = []
    multiplier = 1.0

    if day_of_week == 1:  # Turnaround Tuesday
        multiplier *= 1.08
        effects.append("Turnaround Tuesday (+8%)")

    if dom >= last_day - 2:  # Month-end markup
        multiplier *= 1.06
        effects.append("Month-end markup (+6%)")

    if dom <= 2:  # Month-start fresh capital
        multiplier *= 1.05
        effects.append("Month-start flow (+5%)")

    if month == 1 and dom <= 15:  # January effect
        multiplier *= 1.07
        effects.append("January effect (+7%)")

    if month == 1 and dom <= 10:  # Tax loss reversal
        multiplier *= 1.05
        effects.append("Tax reversal (+5%)")

    if day_of_week == 4:  # Friday risk
        multiplier *= 0.92
        effects.append("Friday risk (-8%)")

    if month == 10:  # October weakness
        multiplier *= 0.94
        effects.append("October seasonality (-6%)")

    if not effects:
        effects.append("No calendar effect")

    return {
        "multiplier": round(multiplier, 3),
        "effects": effects,
        "date": signal_date.isoformat(),
    }


def apply_calendar_bias(confidence, signal_date=None):
    """
    Adjust a signal confidence score by calendar bias multiplier.
    Result capped at 0.95 to avoid overconfidence.
    """
    bias = get_calendar_bias(signal_date)
    adjusted = min(confidence * bias["multiplier"], 0.95)
    if abs(bias["multiplier"] - 1.0) > 0.01:
        logger.info(f"Calendar bias {confidence:.2f} -> {adjusted:.2f} ({', '.join(bias['effects'])})")
    return adjusted
