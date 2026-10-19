"""Errors of the portfolio domain and the calendar checks every daily chain shares."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

ONE_DAY = timedelta(days=1)


class AccountingError(ValueError):
    """Input the portfolio engines cannot process: a skipped day, a misdated event, or a value
    outside the bounds the engines rely on. It flags a caller's mistake, never user input."""


def require_next_day(previous_as_of: date, current: date) -> None:
    """Every calendar day is processed (spec §7.1): a day starts from the day before."""
    if previous_as_of != current - ONE_DAY:
        raise AccountingError(
            f"the previous state must be of {current - ONE_DAY}, not {previous_as_of}"
        )


def require_range(previous_as_of: date, end_date: date, event_dates: Iterable[date]) -> date:
    """The first day of a range after ``previous_as_of``; every event must fall inside it."""
    start_date = previous_as_of + ONE_DAY
    if end_date < previous_as_of:
        raise AccountingError(f"the range ends on {end_date}, before {previous_as_of}")
    outside = [d for d in event_dates if not start_date <= d <= end_date]
    if outside:
        raise AccountingError(f"events dated {min(outside)} are outside {start_date}..{end_date}")
    return start_date


def days_between(start_date: date, end_date: date) -> list[date]:
    """Every calendar day from ``start_date`` to ``end_date``, inclusive."""
    return [start_date + timedelta(days=n) for n in range((end_date - start_date).days + 1)]
