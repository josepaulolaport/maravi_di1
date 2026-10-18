"""The injected clock: "today" is the real date in America/Sao_Paulo (OQ-14).

Application code reads time only through a `Clock`; domain code receives "today" as an argument.
`FixedClock` pins the time for tests (spec §15 D4: the challenge's 2027 examples run with a clock
fixed at 01/01/2027). The system clock reads real time, so it lives in ``di1.platform``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
"""The business time zone."""


class Clock(Protocol):
    def today(self) -> date:
        """Today in São Paulo."""
        ...

    def now(self) -> datetime:
        """The current instant, aware, in São Paulo."""
        ...


@dataclass(frozen=True, slots=True)
class FixedClock:
    """Always the same date; ``now`` defaults to noon in São Paulo on that date."""

    fixed_today: date
    fixed_now: datetime | None = None

    def today(self) -> date:
        return self.fixed_today

    def now(self) -> datetime:
        if self.fixed_now is not None:
            return self.fixed_now
        return datetime.combine(self.fixed_today, time(12, 0), tzinfo=SAO_PAULO)
