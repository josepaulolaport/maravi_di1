"""The injected clock: "today" is the real date in America/Sao_Paulo (OQ-14).

Application code reads time only through a `Clock`; domain code never reads it and receives
"today" as an argument. `FixedClock` pins the time for tests (spec §15 D4: the challenge's 2027
examples run under a clock fixed at 01/01/2027). The system implementation reads the real time,
so it lives in ``di1.platform`` (lane H), not here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
"""The business time zone: dates such as "today" and trade times are São Paulo local time."""


class Clock(Protocol):
    """The current business date and instant."""

    def today(self) -> date:
        """Today in São Paulo."""
        ...

    def now(self) -> datetime:
        """The current instant, as an aware datetime in São Paulo."""
        ...


class FixedClock:
    """A clock that always returns the same date and instant (tests and demos).

    ``now`` defaults to noon in São Paulo on ``today``. A given ``now`` must be aware; it is
    converted to São Paulo and must fall on ``today`` there.
    """

    __slots__ = ("_now", "_today")

    def __init__(self, today: date, now: datetime | None = None) -> None:
        if type(today) is not date:
            raise TypeError(f"`today` must be a date, not {type(today).__name__}")
        if now is None:
            local = datetime.combine(today, time(12, 0), tzinfo=SAO_PAULO)
        elif now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("FixedClock needs a time zone on `now`")
        else:
            # Through UTC, so a local time that never existed (historical DST) is normalised.
            local = now.astimezone(UTC).astimezone(SAO_PAULO)
        if local.date() != today:
            raise ValueError(
                f"`now` is {local.isoformat()} in São Paulo, not on {today.isoformat()}"
            )
        self._today = today
        self._now = local

    def today(self) -> date:
        return self._today

    def now(self) -> datetime:
        return self._now
