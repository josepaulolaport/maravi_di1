"""Spec §13 cases 2 and 3: buy, increase, partial sale, close and long/short reversal with
intraday order; average PU and average rate by their own weighting (spec §7.2, OQ-13, OQ-24).

Monday 04/01/2027, DI1F28, starting flat. Trades in (date, time, seq) order:

    t1 10:00  buy  1 @ 90000  rate 0.12
    t2 11:00  buy  3 @ 91000  rate 0.10   Q 4,  avg PU (90000 + 3×91000)/4 = 90750,
                                                avg rate (0.12 + 3×0.10)/4 = 0.105
    t3 12:00  sell 2 @ 92000  rate 0.09   Q 2,  partial reduction keeps 90750 / 0.105
    t4 13:00  sell 5 @ 93000  rate 0.08   Q −3, crosses zero: opens at 93000 / 0.08
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from di1.modules.portfolio.public import Trade
from tests.acceptance.harness import DI1F28, DI1F29, Facts, run, trade

MONDAY = date(2027, 1, 4)
TUESDAY = date(2027, 1, 5)
WEDNESDAY = date(2027, 1, 6)

T1 = trade(DI1F28, MONDAY, 1, "90000", "0.12", at="10:00", seq=1)
T2 = trade(DI1F28, MONDAY, 3, "91000", "0.10", at="11:00", seq=2)
T3 = trade(DI1F28, MONDAY, -2, "92000", "0.09", at="12:00", seq=3)
T4 = trade(DI1F28, MONDAY, -5, "93000", "0.08", at="13:00", seq=4)


@pytest.mark.parametrize(
    "given_order",
    [[T1, T2, T3, T4], [T4, T3, T2, T1], [T3, T1, T4, T2]],
    ids=["chronological", "reversed", "shuffled"],
)
def test_trades_apply_in_time_order_whatever_the_input_order(given_order: list[Trade]) -> None:
    facts = Facts(trades=given_order)

    position = run(facts, MONDAY, MONDAY)[MONDAY].position(DI1F28)

    assert position.previous_quantity == 0
    assert position.quantity == -3
    assert position.average_entry_pu == Decimal("93000.0000000000")
    assert position.average_entry_rate == Decimal("0.080000000000")
    # The reversing trade stays one row: four trades in, four applied, none split (spec §7.2).
    assert position.trades == (T1, T2, T3, T4)


def test_each_step_of_the_day() -> None:
    def after(*trades: Trade) -> tuple[int, Decimal | None, Decimal | None]:
        p = run(Facts(trades=trades), MONDAY, MONDAY)[MONDAY].position(DI1F28)
        return p.quantity, p.average_entry_pu, p.average_entry_rate

    assert after(T1) == (1, Decimal("90000"), Decimal("0.12"))
    # Increase: PU and rate each weighted by quantity, the rate never derived from the PU.
    assert after(T1, T2) == (4, Decimal("90750"), Decimal("0.105"))
    # Partial reduction keeps the average of the remaining contracts.
    assert after(T1, T2, T3) == (2, Decimal("90750"), Decimal("0.105"))
    # Crossing zero closes the long and opens the rest short at the trade's own PU and rate.
    assert after(T1, T2, T3, T4) == (-3, Decimal("93000"), Decimal("0.08"))


def test_same_time_trades_follow_seq() -> None:
    # Same date and time, seq decides:
    #   seq 1 buy 2 @ 90000 → long 2 @ 90000
    #   seq 2 sell 3 @ 92000 → crosses zero, short 1 @ 92000
    #   seq 3 buy 2 @ 94000 → crosses zero, long 1 @ 94000
    # In reverse order it would end long 1 @ 90000.
    first = trade(DI1F28, MONDAY, 2, "90000", "0.11", at="10:00", seq=1)
    second = trade(DI1F28, MONDAY, -3, "92000", "0.10", at="10:00", seq=2)
    third = trade(DI1F28, MONDAY, 2, "94000", "0.09", at="10:00", seq=3)

    position = run(Facts(trades=[third, second, first]), MONDAY, MONDAY)[MONDAY].position(DI1F28)

    assert position.quantity == 1
    assert position.average_entry_pu == Decimal("94000")
    assert position.average_entry_rate == Decimal("0.09")
    assert position.trades == (first, second, third)


def test_time_comes_before_seq() -> None:
    # Entered later (higher seq) but executed earlier: (date, time, seq) puts time first.
    #   09:00 seq 3 buy 2 @ 94000 → long 2 @ 94000
    #   10:00 seq 2 sell 3 @ 92000 → short 1 @ 92000
    #   11:00 seq 1 buy 2 @ 90000 → long 1 @ 90000
    # Ordered by seq alone it would end long 1 @ 94000.
    late_seq = trade(DI1F28, MONDAY, 2, "94000", "0.09", at="09:00", seq=3)
    middle = trade(DI1F28, MONDAY, -3, "92000", "0.10", at="10:00", seq=2)
    early_seq = trade(DI1F28, MONDAY, 2, "90000", "0.11", at="11:00", seq=1)

    position = run(Facts(trades=[early_seq, middle, late_seq]), MONDAY, MONDAY)[MONDAY].position(
        DI1F28
    )

    assert position.quantity == 1
    assert position.average_entry_pu == Decimal("90000")
    assert position.average_entry_rate == Decimal("0.11")
    assert position.trades == (late_seq, middle, early_seq)


def test_full_close_then_no_row_the_next_day() -> None:
    # Monday buy 4, Tuesday sell 1 (partial) and sell 3 (full close), Wednesday nothing (OQ-10).
    facts = Facts(
        trades=[
            trade(DI1F28, MONDAY, 4, "90000", "0.11"),
            trade(DI1F28, TUESDAY, -1, "90500", "0.10", at="10:00", seq=2),
            trade(DI1F28, TUESDAY, -3, "90600", "0.10", at="15:00", seq=3),
        ],
        prices={(DI1F28, MONDAY): Decimal("90100"), (DI1F28, TUESDAY): Decimal("90550")},
    )

    days = run(facts, MONDAY, WEDNESDAY)

    tuesday = days[TUESDAY].position(DI1F28)
    assert (tuesday.previous_quantity, tuesday.quantity) == (4, 0)
    assert tuesday.average_entry_pu is None
    assert tuesday.average_entry_rate is None
    # A flat position is worth 0 even before looking at a price (spec §8.3).
    assert days[TUESDAY].valued(DI1F28).financial_total == 0
    assert days[WEDNESDAY].expected_assets == set()


def test_assets_are_independent() -> None:
    facts = Facts(
        trades=[
            trade(DI1F28, MONDAY, 2, "90000", "0.11", seq=1),
            trade(DI1F29, MONDAY, -1, "82000", "0.10", seq=2),
            trade(DI1F28, MONDAY, -1, "90200", "0.11", at="11:00", seq=3),
        ]
    )

    day = run(facts, MONDAY, MONDAY)[MONDAY]

    assert (day.position(DI1F28).quantity, day.position(DI1F28).average_entry_pu) == (
        1,
        Decimal("90000"),
    )
    assert (day.position(DI1F29).quantity, day.position(DI1F29).average_entry_pu) == (
        -1,
        Decimal("82000"),
    )
