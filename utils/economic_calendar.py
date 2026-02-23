import datetime
import pytz

def get_upcoming_news(hours_ahead=2):
    """Return a list of major economic events in the next N hours."""
    est = pytz.timezone('US/Eastern')
    current_time = datetime.datetime.now(est)
    events = []

    # Simple hardcoded events
    if current_time.weekday() == 4 and 8 <= current_time.hour < 10:
        events.append("NFP")
    if current_time.hour == 14:
        events.append("FOMC")

    return events

def is_safe_to_trade():
    """Check if it's safe to trade based on upcoming news."""
    events = get_upcoming_news()
    high_impact_events = {"NFP", "FOMC", "ECB", "GDP"}
    for event in events:
        if event in high_impact_events:
            return False
    return True
