"""Calendar-day conventions (spec §4.1, §7.1; OQ-7).

Every calendar date counts, weekends and holidays included; there is no holiday calendar.
Standard library only: domain code imports this module.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

DAYS_PER_YEAR = Decimal(365)
"""Days in the DC/365 year (spec §4.1)."""


def calendar_days(start: date, end: date) -> int:
    """Calendar days from ``start`` to ``end``; negative when ``end`` is earlier."""
    return (end - start).days
