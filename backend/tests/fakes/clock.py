"""A clock pinned for tests (spec §15 D4: the challenge's 2027 examples run with a clock fixed at
01/01/2027). Production reads real time through ``di1.platform.clock.SystemClock``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from di1.shared.clock import SAO_PAULO


@dataclass(frozen=True, slots=True)
class FixedClock:
    """Always the same date; ``now`` defaults to noon in São Paulo on that date. Satisfies
    `di1.shared.clock.Clock`."""

    fixed_today: date
    fixed_now: datetime | None = None

    def today(self) -> date:
        return self.fixed_today

    def now(self) -> datetime:
        if self.fixed_now is not None:
            return self.fixed_now
        return datetime.combine(self.fixed_today, time(12, 0), tzinfo=SAO_PAULO)
