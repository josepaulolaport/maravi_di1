"""Calendar days count every day, weekends and holidays included; the DC/365 year has 365 days
(spec §4.1, §7.1; OQ-7)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from di1.shared.calendar import DAYS_PER_YEAR, calendar_days


def test_the_dc365_year_has_365_days() -> None:
    assert Decimal(365) == DAYS_PER_YEAR
    assert isinstance(DAYS_PER_YEAR, Decimal)


@pytest.mark.parametrize(
    ("start", "end", "days"),
    [
        (date(2027, 1, 1), date(2028, 1, 1), 365),
        (date(2028, 1, 1), date(2029, 1, 1), 366),  # 2028 is a leap year
        (date(2028, 2, 28), date(2028, 3, 1), 2),  # through 29/02
        (date(2027, 2, 28), date(2027, 3, 1), 1),
        (date(2026, 10, 16), date(2026, 10, 19), 3),  # Friday → Monday: weekend counts
        (date(2026, 12, 24), date(2026, 12, 26), 2),  # Christmas counts: no holiday calendar
        (date(2027, 1, 1), date(2027, 1, 1), 0),
        (date(2027, 1, 2), date(2027, 1, 1), -1),  # end before start: negative
    ],
)
def test_calendar_days(start: date, end: date, days: int) -> None:
    assert calendar_days(start, end) == days
