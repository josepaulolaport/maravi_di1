"""Errors of the portfolio domain and the calendar checks every daily chain shares."""

from __future__ import annotations

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
