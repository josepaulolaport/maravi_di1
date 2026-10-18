"""Every calendar day, the starting state, the expected-asset set and input validation.

Spec §7.1, §8.3 (OQ-10), §13 items 2 and 7; OQ-7 (weekends and holidays are ordinary days).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from di1.modules.portfolio.domain.accounting import (
    ZERO,
    AccountingError,
    AccountingState,
    OpenPosition,
    PortfolioAccounting,
)
from tests.unit.portfolio.factories import (
    DAY,
    DI1F27,
    DI1F28,
    DI1F29,
    position,
    trade,
)

ACCOUNTING = PortfolioAccounting()
YESTERDAY = DAY - timedelta(days=1)

FRIDAY = date(2027, 1, 1)
SATURDAY = date(2027, 1, 2)
SUNDAY = date(2027, 1, 3)
MONDAY = date(2027, 1, 4)


def test_the_starting_state_has_zero_cash_and_no_positions() -> None:
    state = AccountingState.zero(YESTERDAY)

    assert state.as_of == YESTERDAY
    assert state.cash_balance == Decimal("0")
    assert state.positions == ()


def test_a_day_without_events_yields_the_same_state_one_day_later() -> None:
    state = AccountingState(
        as_of=YESTERDAY, cash_balance=Decimal("10"), positions=(position(2, "95000", "0.1"),)
    )

    closing = ACCOUNTING.calculate_day(state, [], ZERO, ZERO, DAY).closing_state()

    assert closing == AccountingState(
        as_of=DAY, cash_balance=Decimal("10"), positions=(position(2, "95000", "0.1"),)
    )


def test_weekends_are_ordinary_days_processed_one_by_one() -> None:
    # Deposit on Saturday, trade on Sunday: both land on their own day, with no carry-over gap.
    days = ACCOUNTING.calculate_range(
        AccountingState.zero(FRIDAY - timedelta(days=1)),
        [trade(2, "95000", on=SUNDAY)],
        {SATURDAY: Decimal("300000")},
        {},
        MONDAY,
    )

    assert [d.date for d in days] == [FRIDAY, SATURDAY, SUNDAY, MONDAY]
    assert [d.cash_balance for d in days] == [
        Decimal("0"),
        Decimal("300000"),
        Decimal("110000"),
        Decimal("110000"),
    ]
    assert [[p.quantity for p in d.positions] for d in days] == [[], [], [2], [2]]
    assert days[3].positions[0].previous_quantity == 2


def test_a_range_chains_each_closing_state_into_the_next_day() -> None:
    trades = [
        trade(10, "95000", "0.105", on=FRIDAY),
        trade(30, "96000", "0.095", on=SATURDAY),
        trade(-15, "97000", "0.08", on=SUNDAY),
        trade(-50, "98000", "0.07", on=MONDAY),
    ]

    days = ACCOUNTING.calculate_range(
        AccountingState.zero(FRIDAY - timedelta(days=1)), trades, {}, {}, MONDAY
    )

    closing = days[-1].closing_state()
    assert closing.positions == (
        OpenPosition(
            asset_id=DI1F27,
            quantity=-25,
            average_entry_pu=Decimal("98000"),
            average_entry_rate=Decimal("0.07"),
        ),
    )
    # −950000 − 2880000 + 1455000 + 4900000
    assert closing.cash_balance == Decimal("2525000")
    assert closing.as_of == MONDAY


def test_a_range_matches_day_by_day_calculation() -> None:
    trades = [trade(5, "95000", on=SATURDAY), trade(-5, "95500", on=MONDAY)]
    deposits = {FRIDAY: Decimal("1000")}
    withdrawals = {SUNDAY: Decimal("400")}
    start = AccountingState.zero(FRIDAY - timedelta(days=1))

    by_range = ACCOUNTING.calculate_range(start, trades, deposits, withdrawals, MONDAY)

    state, by_day = start, []
    for current in (FRIDAY, SATURDAY, SUNDAY, MONDAY):
        day = ACCOUNTING.calculate_day(
            state,
            [t for t in trades if t.trade_date == current],
            deposits.get(current, ZERO),
            withdrawals.get(current, ZERO),
            current,
        )
        by_day.append(day)
        state = day.closing_state()
    assert by_range == tuple(by_day)


def test_an_empty_range_yields_no_days() -> None:
    assert ACCOUNTING.calculate_range(AccountingState.zero(DAY), [], {}, {}, DAY) == ()


def test_expected_assets_are_those_held_yesterday_or_traded_today() -> None:
    # DI1F27 held, not traded; DI1F28 opened today; DI1F29 closed before yesterday (absent).
    state = AccountingState(
        as_of=YESTERDAY, cash_balance=Decimal("0"), positions=(position(3, "95000", "0.1"),)
    )

    day = ACCOUNTING.calculate_day(state, [trade(1, "91000", asset_id=DI1F28)], ZERO, ZERO, DAY)

    assert [p.asset_id for p in day.positions] == [DI1F27, DI1F28]
    assert DI1F29 not in {p.asset_id for p in day.positions}


def test_a_position_closed_today_keeps_its_row_today_and_leaves_tomorrow() -> None:
    state = AccountingState(
        as_of=YESTERDAY, cash_balance=Decimal("0"), positions=(position(3, "95000", "0.1"),)
    )

    today = ACCOUNTING.calculate_day(state, [trade(-3, "96000")], ZERO, ZERO, DAY)
    tomorrow = ACCOUNTING.calculate_day(
        today.closing_state(), [], ZERO, ZERO, DAY + timedelta(days=1)
    )

    assert [(p.asset_id, p.quantity) for p in today.positions] == [(DI1F27, 0)]
    assert today.closing_state().positions == ()
    assert tomorrow.positions == ()


def test_positions_are_listed_in_asset_id_order() -> None:
    day = ACCOUNTING.calculate_day(
        AccountingState.zero(YESTERDAY),
        [
            trade(1, "90000", asset_id=DI1F29, seq=1),
            trade(1, "91000", asset_id=DI1F27, seq=2),
            trade(1, "92000", asset_id=DI1F28, seq=3),
        ],
        ZERO,
        ZERO,
        DAY,
    )

    assert [p.asset_id for p in day.positions] == [DI1F27, DI1F28, DI1F29]


def test_trades_of_different_assets_do_not_mix_averages() -> None:
    day = ACCOUNTING.calculate_day(
        AccountingState.zero(YESTERDAY),
        [trade(1, "90000", asset_id=DI1F28, seq=1), trade(1, "95000", asset_id=DI1F27, seq=2)],
        ZERO,
        ZERO,
        DAY,
    )

    assert [p.average_entry_pu for p in day.positions] == [Decimal("95000"), Decimal("90000")]


def test_the_previous_state_must_be_the_day_before() -> None:
    # Every calendar day is processed: skipping one would drop its events.
    with pytest.raises(AccountingError):
        ACCOUNTING.calculate_day(AccountingState.zero(DAY - timedelta(days=2)), [], ZERO, ZERO, DAY)


def test_a_trade_dated_another_day_is_rejected() -> None:
    with pytest.raises(AccountingError):
        ACCOUNTING.calculate_day(
            AccountingState.zero(YESTERDAY), [trade(1, "95000", on=YESTERDAY)], ZERO, ZERO, DAY
        )


def test_a_range_rejects_events_outside_it() -> None:
    with pytest.raises(AccountingError):
        ACCOUNTING.calculate_range(
            AccountingState.zero(FRIDAY - timedelta(days=1)),
            [trade(1, "95000", on=MONDAY + timedelta(days=1))],
            {},
            {},
            MONDAY,
        )


@pytest.mark.parametrize("side", ["deposits", "withdrawals"])
def test_a_range_rejects_cash_totals_outside_it(side: str) -> None:
    totals = {FRIDAY - timedelta(days=1): Decimal("10")}
    with pytest.raises(AccountingError):
        ACCOUNTING.calculate_range(
            AccountingState.zero(FRIDAY - timedelta(days=1)),
            [],
            totals if side == "deposits" else {},
            totals if side == "withdrawals" else {},
            MONDAY,
        )


def test_a_range_cannot_end_before_its_previous_state() -> None:
    with pytest.raises(AccountingError):
        ACCOUNTING.calculate_range(AccountingState.zero(DAY), [], {}, {}, YESTERDAY)


def test_a_flat_position_is_never_carried() -> None:
    # The next day's state holds open positions only; flat assets are not expected (OQ-10).
    with pytest.raises(AccountingError):
        position(0, "95000", "0.1")


def test_a_state_holding_the_same_asset_twice_is_rejected() -> None:
    with pytest.raises(AccountingError):
        AccountingState(
            as_of=YESTERDAY,
            cash_balance=Decimal("0"),
            positions=(position(1, "95000", "0.1"), position(2, "95000", "0.1")),
        )


def test_a_zero_quantity_trade_is_rejected() -> None:
    # Schema CHECK trades_qty_nonzero (OQ-14).
    with pytest.raises(AccountingError):
        trade(0, "95000")


def test_a_backdated_trade_is_applied_on_its_own_date_whatever_the_input_order() -> None:
    # A Saturday trade entered after Monday's (a later seq, listed last) still lands on Saturday:
    # Sat buy 10 @ 95000; Mon sell 4 @ 96000 → partial close keeps 6 @ 95000.
    monday_sell = trade(-4, "96000", "0.095", on=MONDAY, seq=1)
    backdated_saturday_buy = trade(10, "95000", "0.105", on=SATURDAY, seq=2)

    days = ACCOUNTING.calculate_range(
        AccountingState.zero(FRIDAY - timedelta(days=1)),
        [monday_sell, backdated_saturday_buy],
        {},
        {},
        MONDAY,
    )

    assert [[p.quantity for p in d.positions] for d in days] == [[], [10], [10], [6]]
    assert days[3].positions[0].average_entry_pu == Decimal("95000")
    assert days[3].positions[0].average_entry_rate == Decimal("0.105")
    # −950000 + 384000
    assert days[3].cash_balance == Decimal("-566000")


def test_a_range_equals_jobs_split_by_day_reading_the_stored_previous_state() -> None:
    # Fri: 1 @ 90909.0909090909 + 2 @ 91000 → 90969.69696969696666… → stored 90969.6969696970.
    # Sat: + 1 @ 91000 → (3 × 90969.6969696970 + 91000) / 4 = 90977.27272727275 → 90977.2727272728.
    friday = [
        trade(1, "90909.0909090909", on=FRIDAY, at="09:00", seq=1),
        trade(2, "91000", on=FRIDAY, at="10:00", seq=2),
    ]
    saturday = [trade(1, "91000", on=SATURDAY, seq=3)]
    start = AccountingState.zero(FRIDAY - timedelta(days=1))

    one_job = ACCOUNTING.calculate_range(start, friday + saturday, {}, {}, SATURDAY)
    first_job = ACCOUNTING.calculate_range(start, friday, {}, {}, FRIDAY)
    stored = first_job[-1].positions[0]
    read_back = AccountingState(
        as_of=FRIDAY,
        cash_balance=first_job[-1].cash_balance,
        positions=(
            position(stored.quantity, str(stored.average_entry_pu), str(stored.average_entry_rate)),
        ),
    )
    second_job = ACCOUNTING.calculate_range(read_back, saturday, {}, {}, SATURDAY)

    assert stored.average_entry_pu == Decimal("90969.6969696970")
    assert one_job[-1].positions[0].average_entry_pu == Decimal("90977.2727272728")
    assert second_job[-1] == one_job[-1]
