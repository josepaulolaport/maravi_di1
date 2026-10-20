"""The injected clock (OQ-14; spec §15 D4)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from di1.shared.clock import SAO_PAULO, Clock
from tests.support.fakes import FakeClock


def test_fixed_clock_gives_the_pinned_date() -> None:
    clock: Clock = FakeClock(date(2027, 1, 1))
    assert clock.today() == date(2027, 1, 1)


def test_fixed_clock_now_defaults_to_noon_in_sao_paulo() -> None:
    now = FakeClock(date(2027, 1, 1)).now()
    assert now == datetime(2027, 1, 1, 12, 0, tzinfo=SAO_PAULO)
    assert now.utcoffset() == timedelta(hours=-3)


def test_fixed_clock_returns_a_given_now() -> None:
    given = datetime(2027, 1, 1, 15, 0, tzinfo=UTC)
    assert FakeClock(date(2027, 1, 1), given).now() == given
