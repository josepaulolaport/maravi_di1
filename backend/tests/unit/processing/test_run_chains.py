"""One date of each chain (spec §7, §8.1, §8.3; OQ-1, OQ-4, OQ-10, OQ-24, OQ-31, OQ-38).
Expected values follow the formulas of CLAUDE.md §2, worked by hand."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.pnl.public import CalculationCompleteness
from di1.modules.portfolio.public import (
    CashBalance,
    OpenPosition,
    PositionState,
    PreviousPositionsDay,
    ValuationStatus,
)
from di1.modules.processing.application.services.run_chains import (
    cash_totals,
    process_cash_day,
    process_positions_day,
    trade_of,
)
from di1.modules.processing.domain.errors import ProcessingError
from di1.modules.processing.domain.issues import IssueRecord, IssueType
from tests.unit.processing.run_fakes import RecordingWriter, World, cash_movement, trade

D0 = date(2026, 10, 5)
D1 = date(2026, 10, 6)
D2 = date(2026, 10, 7)
F29 = UUID(int=29)
MATURITY = date(2029, 1, 2)


def world() -> World:
    w = World()
    w.instruments.maturities[F29] = MATURITY
    return w


async def positions(
    w: World, day: date, *, zero_state: bool
) -> tuple[list[IssueRecord], RecordingWriter]:
    writer = RecordingWriter()
    issues = await process_positions_day(
        day,
        zero_state=zero_state,
        ports=w.ports(writer),
    )
    return issues, writer


def held(quantity: int, pu: str, cumulative: str | None, as_of: date = D0) -> PreviousPositionsDay:
    return PreviousPositionsDay(
        state=PositionState(
            as_of=as_of,
            positions=(OpenPosition(F29, quantity, Decimal(pu), Decimal("0.1")),),
        ),
        cumulative_pnl=None if cumulative is None else Decimal(cumulative),
    )


# --- cash -----------------------------------------------------------------------------------


async def test_cash_from_the_zero_state_adds_trades_deposits_and_withdrawals() -> None:
    w = world()
    w.ledger.trades.append(trade(F29, D1, 10, "95000.0000000000"))
    w.ledger.movements += [cash_movement(D1, "1000000.00"), cash_movement(D1, "-200.00", seq=2)]
    writer = RecordingWriter()

    await process_cash_day(
        D1,
        zero_state=True,
        ports=w.ports(writer),
    )

    [written] = writer.cash
    assert written.day.previous_cash_balance == 0
    assert written.day.trades_cash_flow == Decimal("-950000")
    assert written.day.deposits == Decimal("1000000.00")
    assert written.day.withdrawals == Decimal("200.00")
    assert written.day.cash_balance == Decimal("49800")


async def test_cash_continues_from_the_published_balance_of_the_day_before() -> None:
    w = world()
    w.portfolio.cash[D0] = CashBalance(as_of=D0, balance=Decimal("500.00"))
    w.ledger.movements.append(cash_movement(D1, "-100.00"))
    writer = RecordingWriter()

    await process_cash_day(
        D1,
        zero_state=False,
        ports=w.ports(writer),
    )

    assert writer.cash[0].day.cash_balance == Decimal("400.00")


async def test_cash_with_a_processed_day_before_but_no_published_balance_is_a_data_error() -> None:
    with pytest.raises(ProcessingError):
        await process_cash_day(
            D1,
            zero_state=False,
            ports=world().ports(RecordingWriter()),
        )


# --- positions ------------------------------------------------------------------------------


async def test_first_trade_from_the_zero_state_has_only_trades_pnl() -> None:
    w = world()
    w.ledger.trades.append(trade(F29, D1, 10, "95000.0000000000"))
    w.prices.set(F29, D1, "95100.0000000000")

    issues, writer = await positions(w, D1, zero_state=True)

    assert issues == []
    [written] = writer.positions
    assert [p.quantity for p in written.day.positions] == [10]
    assert written.valuation.positions_market_value == Decimal("951000")
    assert written.asset_pnl[F29].position_pnl == 0  # Q[D−1] = 0 (OQ-4)
    assert written.asset_pnl[F29].trades_pnl == Decimal("1000")
    assert written.pnl.daily_pnl == Decimal("1000")
    assert written.pnl.cumulative_pnl == Decimal("1000")  # 0 before the first entry


async def test_a_held_position_earns_position_pnl_from_d_minus_1_to_d() -> None:
    w = world()
    w.portfolio.positions[D1] = held(10, "95000.0000000000", "1000", as_of=D1)
    w.prices.set(F29, D1, "95100.0000000000")
    w.prices.set(F29, D2, "95200.0000000000")

    issues, writer = await positions(w, D2, zero_state=False)

    assert issues == []
    written = writer.positions[0]
    assert written.asset_pnl[F29].position_pnl == Decimal("1000")
    assert written.pnl.cumulative_pnl == Decimal("2000")


async def test_a_missing_price_on_d_is_an_issue_and_leaves_the_figures_null() -> None:
    w = world()
    w.portfolio.positions[D1] = held(10, "95000.0000000000", "0", as_of=D1)
    w.prices.set(F29, D1, "95100.0000000000")

    issues, writer = await positions(w, D2, zero_state=False)

    assert issues == [IssueRecord(IssueType.MISSING_REFERENCE_PRICE, F29, D2, D2)]
    written = writer.positions[0]
    assert written.day.positions[0].quantity == 10  # the quantity is still computed
    assert written.valuation.status is ValuationStatus.MISSING
    assert written.valuation.positions_market_value is None
    assert written.pnl.daily_pnl is None
    assert written.pnl.cumulative_pnl is None
    assert written.pnl.status is CalculationCompleteness.MISSING


async def test_a_missing_price_on_d_minus_1_is_an_issue_for_that_date() -> None:
    w = world()
    w.portfolio.positions[D1] = held(10, "95000.0000000000", "0", as_of=D1)
    w.prices.set(F29, D2, "95200.0000000000")

    issues, writer = await positions(w, D2, zero_state=False)

    assert issues == [IssueRecord(IssueType.MISSING_REFERENCE_PRICE, F29, D2, D1)]
    assert writer.positions[0].valuation.positions_market_value == Decimal("952000")
    assert writer.positions[0].asset_pnl[F29].position_pnl is None


async def test_a_day_with_no_expected_asset_is_still_written_with_zero_pnl() -> None:
    w = world()
    w.portfolio.positions[D1] = PreviousPositionsDay(
        state=PositionState(as_of=D1), cumulative_pnl=Decimal("750")
    )

    issues, writer = await positions(w, D2, zero_state=False)

    assert issues == []
    written = writer.positions[0]
    assert written.day.positions == ()
    assert written.valuation.positions_market_value == 0
    assert written.pnl.daily_pnl == 0
    assert written.pnl.cumulative_pnl == Decimal("750")  # carried forward (OQ-22)


async def test_an_open_position_after_maturity_is_worth_zero_and_raises_an_issue() -> None:
    w = world()
    maturity = D1
    w.instruments.maturities[F29] = maturity
    w.portfolio.positions[D1] = held(10, "99000.0000000000", "0", as_of=D1)
    w.prices.set(F29, maturity, "99900.0000000000")  # the maturity-day price, typed by the user

    issues, writer = await positions(w, D2, zero_state=False)

    assert issues == [IssueRecord(IssueType.EXPIRED_OPEN_POSITION, F29, D2, None)]
    written = writer.positions[0]
    assert written.valuation.positions_market_value == 0
    # position_pnl = Q × (0 − PU_maturity) (spec §7.4)
    assert written.asset_pnl[F29].position_pnl == Decimal("-999000")


async def test_positions_with_a_processed_day_before_but_nothing_published_is_a_data_error() -> (
    None
):
    with pytest.raises(ProcessingError):
        await positions(world(), D2, zero_state=False)


async def test_a_traded_asset_without_an_instrument_is_a_data_error() -> None:
    w = World()
    w.ledger.trades.append(trade(F29, D1, 1, "95000.0000000000"))
    with pytest.raises(ProcessingError):
        await positions(w, D1, zero_state=True)


# --- malformed ledger rows (explicit raises, not asserts: they hold under python -O) --------


@pytest.mark.parametrize(
    "missing", ["asset_id", "signed_quantity", "execution_pu", "execution_rate"]
)
def test_a_trade_missing_a_trade_field_is_a_data_error(missing: str) -> None:
    broken = replace(trade(F29, D1, 1, "95000.0000000000"), **{missing: None})  # type: ignore[arg-type]

    with pytest.raises(ProcessingError):
        trade_of(broken)


def test_a_cash_movement_without_an_amount_is_a_data_error() -> None:
    broken = replace(cash_movement(D1, "100.00"), cash_amount=None)

    with pytest.raises(ProcessingError):
        cash_totals([broken])
