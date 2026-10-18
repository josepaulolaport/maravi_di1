"""The injected clock (OQ-14: "today" is the real date in America/Sao_Paulo, read through a clock).

Application code reads time only through `Clock`; domain code receives "today" as an argument.
`FixedClock` pins both values for tests (spec §15 D4: the challenge's 2027 examples run under a
clock fixed at 01/01/2027).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from di1.contracts.clock import SAO_PAULO, Clock, FixedClock


def test_sao_paulo_is_the_business_time_zone() -> None:
    assert ZoneInfo("America/Sao_Paulo") == SAO_PAULO


def test_fixed_clock_is_a_clock() -> None:
    clock: Clock = FixedClock(date(2027, 1, 1))
    assert clock.today() == date(2027, 1, 1)


def test_fixed_clock_defaults_now_to_noon_in_sao_paulo() -> None:
    now = FixedClock(date(2027, 1, 1)).now()
    assert now == datetime(2027, 1, 1, 12, 0, tzinfo=SAO_PAULO)
    assert now.utcoffset() == timedelta(hours=-3)


def test_fixed_clock_converts_an_aware_now_to_sao_paulo() -> None:
    # 01:30 UTC on 2 Jan is 22:30 on 1 Jan in São Paulo: the business date is 1 Jan.
    clock = FixedClock(date(2027, 1, 1), now=datetime(2027, 1, 2, 1, 30, tzinfo=UTC))
    assert clock.now() == datetime(2027, 1, 1, 22, 30, tzinfo=SAO_PAULO)
    assert clock.now().tzinfo == SAO_PAULO


def test_fixed_clock_rejects_a_naive_now() -> None:
    with pytest.raises(ValueError, match="time zone"):
        FixedClock(date(2027, 1, 1), now=datetime(2027, 1, 1, 12, 0))  # noqa: DTZ001


def test_fixed_clock_rejects_a_now_on_another_business_date() -> None:
    with pytest.raises(ValueError, match="2027-01-01"):
        FixedClock(date(2027, 1, 1), now=datetime(2027, 1, 2, 12, 0, tzinfo=SAO_PAULO))


def test_fixed_clock_rejects_a_utc_now_that_is_the_previous_day_in_sao_paulo() -> None:
    # 02:00 UTC on 1 Jan is 23:00 on 31 Dec in São Paulo.
    with pytest.raises(ValueError, match="2027-01-01"):
        FixedClock(date(2027, 1, 1), now=datetime(2027, 1, 1, 2, 0, tzinfo=UTC))


def test_fixed_clock_rejects_a_datetime_as_today() -> None:
    with pytest.raises(TypeError, match="date"):
        FixedClock(datetime(2027, 1, 1, 15, 0, tzinfo=SAO_PAULO))


def test_fixed_clock_normalises_a_local_time_skipped_by_historical_dst() -> None:
    # DST began at 00:00 on 4 Nov 2018: 00:30 local did not exist; it is 01:30 (-02:00).
    clock = FixedClock(date(2018, 11, 4), now=datetime(2018, 11, 4, 0, 30, tzinfo=SAO_PAULO))
    assert clock.now().utcoffset() == timedelta(hours=-2)
    assert (clock.now().hour, clock.now().minute) == (1, 30)
