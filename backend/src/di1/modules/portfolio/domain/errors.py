"""The portfolio module's one internal error and the calendar check every daily chain shares."""

from __future__ import annotations

from datetime import date

from di1.shared.calendar import ONE_DAY


class PortfolioError(ValueError):
    """Input the portfolio chains cannot process: a skipped day, a misdated event, a value outside
    the bounds they rely on, or published rows that disagree. It flags a caller's mistake or a
    technical fault, never user input (user errors are `DomainError`s)."""


def require_next_day(previous_as_of: date, current: date) -> None:
    """Every calendar day is processed (spec §7.1): a day starts from the day before."""
    if previous_as_of != current - ONE_DAY:
        raise PortfolioError(
            f"the previous state must be of {current - ONE_DAY}, not {previous_as_of}"
        )
