"""The production `Clock`: real time in America/Sao_Paulo (OQ-14).

Tests use `tests.fakes.clock.FixedClock` instead.
"""

from __future__ import annotations

from datetime import date, datetime

from di1.shared.clock import SAO_PAULO


class SystemClock:
    """Reads the system clock; satisfies `di1.shared.clock.Clock`."""

    def today(self) -> date:
        return self.now().date()

    def now(self) -> datetime:
        return datetime.now(SAO_PAULO)
