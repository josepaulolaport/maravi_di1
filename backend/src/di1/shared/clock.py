"""The injected clock: "today" is the real date in America/Sao_Paulo (OQ-14).

Application code reads time only through a `Clock`; domain code receives "today" as an argument.
The system clock reads real time, so it lives in ``di1.platform``; tests pin it with
``tests.fakes.clock.FixedClock`` (spec §15 D4).
"""

from __future__ import annotations

from datetime import date, datetime
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
