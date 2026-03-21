"""
US equity session helpers (NYSE-style full-day closures + weekday RTH).
Not a full exchange rule engine — good enough for operator UX and gates.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

# NYSE full-day closures (add annually). Partial days not modeled.
_NYSE_FULL_CLOSURES: frozenset[date] = frozenset(
    {
        date(2024, 1, 1),
        date(2024, 1, 15),
        date(2024, 2, 19),
        date(2024, 3, 29),
        date(2024, 5, 27),
        date(2024, 6, 19),
        date(2024, 7, 4),
        date(2024, 9, 2),
        date(2024, 11, 28),
        date(2024, 12, 25),
        date(2025, 1, 1),
        date(2025, 1, 20),
        date(2025, 2, 17),
        date(2025, 4, 18),
        date(2025, 5, 26),
        date(2025, 6, 19),
        date(2025, 7, 4),
        date(2025, 9, 1),
        date(2025, 11, 27),
        date(2025, 12, 25),
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),  # observed
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    }
)


def nyse_closed_full_day(d: date | None = None) -> bool:
    d = d or datetime.now(_ET).date()
    return d in _NYSE_FULL_CLOSURES


def is_us_equity_rth_open(now: datetime | None = None) -> bool:
    """Weekday regular session 09:30–16:00 ET, excluding full NYSE closure days."""
    now = now or datetime.now(_ET)
    if now.weekday() >= 5:
        return False
    if nyse_closed_full_day(now.date()):
        return False
    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 30) <= minutes < (16 * 60)


def session_label(now: datetime | None = None) -> str:
    now = now or datetime.now(_ET)
    if nyse_closed_full_day(now.date()):
        return "closed_holiday"
    if now.weekday() >= 5:
        return "closed_weekend"
    if is_us_equity_rth_open(now):
        return "rth_open"
    return "closed_after_hours"
