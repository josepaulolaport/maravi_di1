"""The system clock reads real time in America/Sao_Paulo (OQ-14; `di1.shared.clock` docstring).

Application code reads time only through a `Clock`; `SystemClock` is the production one.
"""

from __future__ import annotations

from datetime import datetime

from di1.platform.clock import SystemClock
from di1.shared.clock import SAO_PAULO


def test_now_is_aware_and_in_sao_paulo() -> None:
    now = SystemClock().now()

    assert now.tzinfo is SAO_PAULO


def test_now_is_the_current_instant() -> None:
    before = datetime.now(SAO_PAULO)
    now = SystemClock().now()
    after = datetime.now(SAO_PAULO)

    assert before <= now <= after


def test_today_is_the_sao_paulo_date() -> None:
    before = datetime.now(SAO_PAULO).date()
    today = SystemClock().today()
    after = datetime.now(SAO_PAULO).date()

    assert today in {before, after}
