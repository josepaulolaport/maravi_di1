"""`PortfolioService`: published data and each date's chain statuses, never recalculated on
read except AUM (spec §11.4; OQ-21, OQ-23, OQ-27, OQ-28, OQ-30, OQ-31, OQ-35, OQ-38, OQ-41, OQ-50).

The read snapshot (REPEATABLE READ, started once before any read) is checked against PostgreSQL in
tests/integration/portfolio/test_published_rows.py."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from di1.modules.pnl.public import CalculationCompleteness
from di1.modules.portfolio.application.ports import (
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.portfolio.application.services.query_service import DefaultPortfolioService
from di1.modules.portfolio.domain.valuation import ValuationStatus
from di1.modules.portfolio.public import PortfolioService
from di1.modules.prices.public import PriceSource
from di1.modules.processing.public import ChainStatus, DateStatus
from di1.shared.errors import DomainError, ErrorCode
from tests.support.builders import DAY, DI1F27, DI1F28, DI1F29, di1_contract
from tests.support.fakes import FakeAssetReader, FakeClock, FakeDateStatusReader, FakePriceReader
from tests.unit.portfolio.fakes import InMemoryPortfolioRepository, stored_cash

TODAY = DAY + timedelta(days=10)
YESTERDAY = DAY - timedelta(days=1)
COMPLETE = CalculationCompleteness.COMPLETE
MISSING = CalculationCompleteness.MISSING
PROCESSED = ChainStatus.PROCESSED
WITH_ISSUES = ChainStatus.PROCESSED_WITH_ISSUES
FAILED = ChainStatus.FAILED
RUNNING = ChainStatus.RUNNING
ZERO = Decimal("0")
CASH_AT = datetime(2027, 1, 4, 21, 0, tzinfo=UTC)
POSITIONS_AT = datetime(2027, 1, 4, 21, 5, tzinfo=UTC)
FUTURE_MESSAGE = "A data não pode ser posterior a hoje."


def _status(on: date, portfolio: ChainStatus | None, cash: ChainStatus | None) -> DateStatus:
    return DateStatus(
        date=on,
        portfolio=portfolio,
        cash=cash,
        portfolio_processed_at=None if portfolio is None else POSITIONS_AT,
        cash_processed_at=None if cash is None else CASH_AT,
    )


def _day(on: date, daily: str | None, cumulative: str | None = None) -> PublishedPortfolioDay:
    value = None if daily is None else Decimal(daily)
    return PublishedPortfolioDay(
        date=on,
        positions_market_value=Decimal("950000"),
        position_pnl=value,
        trades_pnl=None if value is None else Decimal("0"),
        daily_pnl=value,
        cumulative_pnl=None if cumulative is None else Decimal(cumulative),
        valuation_status=COMPLETE,
        pnl_status=COMPLETE if value is not None else MISSING,
    )


def _position(asset_id: UUID, quantity: int, financial_total: str | None) -> PublishedPosition:
    return PublishedPosition(
        asset_id=asset_id,
        quantity=quantity,
        average_entry_pu=Decimal("95000"),
        average_entry_rate=Decimal("0.105"),
        financial_total=None if financial_total is None else Decimal(financial_total),
        position_pnl=Decimal("10"),
        trades_pnl=Decimal("0"),
        daily_pnl=Decimal("10"),
        valuation_status=ValuationStatus.COMPLETE if financial_total else ValuationStatus.MISSING,
        pnl_status=COMPLETE,
    )


@pytest.fixture
def repository() -> InMemoryPortfolioRepository:
    return InMemoryPortfolioRepository()


@pytest.fixture
def statuses() -> FakeDateStatusReader:
    return FakeDateStatusReader()


@pytest.fixture
def prices() -> FakePriceReader:
    return FakePriceReader()


@pytest.fixture
def queries(
    repository: InMemoryPortfolioRepository,
    statuses: FakeDateStatusReader,
    prices: FakePriceReader,
) -> PortfolioService:
    assets = FakeAssetReader(
        di1_contract("DI1F27", DI1F27.id, YESTERDAY),  # matured yesterday
        DI1F28,
        DI1F29,
    )
    return DefaultPortfolioService(
        repository,
        assets=assets,
        prices=prices,
        date_statuses=statuses,
        clock=FakeClock(TODAY),
    )


# --- summary -------------------------------------------------------------------------------------


async def test_a_processed_date_shows_both_chains_and_aum_computed_on_read(
    queries: PortfolioService,
    repository: InMemoryPortfolioRepository,
    statuses: FakeDateStatusReader,
) -> None:
    repository.cash[DAY] = stored_cash(
        DAY, Decimal("50000"), Decimal("-950000"), Decimal("1000000"), Decimal("0")
    )
    repository.days[DAY] = _day(DAY, "10", "15")
    statuses.statuses[DAY] = _status(DAY, WITH_ISSUES, PROCESSED)

    summary = await queries.get_summary(DAY)

    assert summary.date == DAY
    assert summary.cash.status is PROCESSED
    assert summary.cash.balance == Decimal("50000")
    assert summary.cash.trades_cash_flow == Decimal("-950000")
    assert summary.cash.deposits == Decimal("1000000")
    assert summary.cash.withdrawals == Decimal("0")
    assert summary.cash.published_at == CASH_AT
    assert summary.positions.status is WITH_ISSUES
    assert summary.positions.published_at == POSITIONS_AT
    assert summary.positions.market_value == Decimal("950000")
    assert summary.positions.valuation_status is COMPLETE
    assert summary.positions.daily_pnl == Decimal("10")
    assert summary.positions.cumulative_pnl == Decimal("15")
    assert summary.positions.pnl_status is COMPLETE
    assert summary.aum == Decimal("1000000")  # 50000 cash + 950000 market value, on read


async def test_a_date_never_processed_is_all_null_never_zero(queries: PortfolioService) -> None:
    summary = await queries.get_summary(DAY)

    assert summary.cash.status is None
    assert summary.cash.balance is None
    assert summary.cash.published_at is None
    assert summary.positions.status is None
    assert summary.positions.market_value is None
    assert summary.positions.valuation_status is None
    assert summary.positions.pnl_status is None
    assert summary.aum is None


@pytest.mark.parametrize(
    ("positions", "cash", "market_value", "balance", "aum"),
    [
        # OQ-38, OQ-40: hidden unless both chains are PROCESSED or PROCESSED_WITH_ISSUES, so a
        # later FAILED or RUNNING chain hides it (reviewer M1).
        pytest.param(PROCESSED, FAILED, "50", "100", None, id="cash-failed"),
        pytest.param(FAILED, PROCESSED, "50", "100", None, id="positions-failed"),
        pytest.param(PROCESSED, RUNNING, "50", "100", None, id="cash-running"),
        pytest.param(RUNNING, WITH_ISSUES, "50", "100", None, id="positions-running"),
        pytest.param(PROCESSED, None, "50", "100", None, id="positions-alone"),
        pytest.param(None, PROCESSED, "50", "100", None, id="cash-alone"),
        # 100 cash + 50 market value.
        pytest.param(PROCESSED, PROCESSED, "50", "100", "150", id="both-processed"),
        pytest.param(WITH_ISSUES, PROCESSED, "50", "100", "150", id="positions-with-issues"),
        # An expected asset without a reference price: the market value is unknown (OQ-10).
        pytest.param(WITH_ISSUES, PROCESSED, None, "100", None, id="market-value-missing"),
        # OQ-22 item 5, OQ-38: no expected asset → market value 0 → AUM = cash.
        pytest.param(PROCESSED, PROCESSED, "0", "100", "100", id="no-expected-asset"),
        # A later CASH run republished D with another balance: AUM follows on read (OQ-21).
        pytest.param(PROCESSED, PROCESSED, "50", "400", "450", id="cash-rewritten"),
    ],
)
async def test_aum_is_cash_plus_market_value_only_while_both_chains_are_processed(
    queries: PortfolioService,
    repository: InMemoryPortfolioRepository,
    statuses: FakeDateStatusReader,
    positions: ChainStatus | None,
    cash: ChainStatus | None,
    market_value: str | None,
    balance: str,
    aum: str | None,
) -> None:
    repository.cash[DAY] = stored_cash(DAY, Decimal(balance), ZERO, Decimal(balance), ZERO)
    repository.days[DAY] = replace(
        _day(DAY, "0"),
        positions_market_value=None if market_value is None else Decimal(market_value),
        valuation_status=COMPLETE if market_value is not None else MISSING,
    )
    statuses.statuses[DAY] = _status(DAY, positions, cash)

    summary = await queries.get_summary(DAY)

    assert summary.aum == (None if aum is None else Decimal(aum))
    assert summary.cash.balance == Decimal(balance)  # each chain's own figures still show
    assert summary.positions.market_value == (
        None if market_value is None else Decimal(market_value)
    )


# --- position table ------------------------------------------------------------------------------


async def test_rows_carry_the_current_preferred_price_and_its_source(
    queries: PortfolioService,
    repository: InMemoryPortfolioRepository,
    statuses: FakeDateStatusReader,
    prices: FakePriceReader,
) -> None:
    repository.positions[DAY] = (
        _position(DI1F29.id, -2, None),
        _position(DI1F28.id, 10, "951000"),
    )
    prices.set(DI1F28.id, DAY, "95100", PriceSource.B3, "0.0990")
    prices.set(DI1F28.id, YESTERDAY, "1", PriceSource.MANUAL, "0.5")  # another date
    statuses.statuses[DAY] = _status(DAY, PROCESSED, None)

    table = await queries.get_position_table(DAY)

    assert table.status is PROCESSED
    assert table.published_at == POSITIONS_AT
    assert [r.asset_code for r in table.items] == ["DI1F28", "DI1F29"]
    priced, unpriced = table.items
    assert priced.maturity_date == date(2028, 1, 3)
    assert priced.quantity == 10
    assert priced.reference_source is PriceSource.B3
    assert priced.reference_pu == Decimal("95100")
    assert priced.reference_rate == Decimal("0.0990")
    assert priced.financial_total == Decimal("951000")
    assert unpriced.reference_source is None  # exact date only, no carry-forward
    assert unpriced.reference_pu is None
    assert unpriced.reference_rate is None
    assert unpriced.financial_total is None
    assert unpriced.valuation_status is ValuationStatus.MISSING


async def test_a_corrected_price_shows_next_to_the_figures_of_the_last_processing(
    queries: PortfolioService,
    repository: InMemoryPortfolioRepository,
    prices: FakePriceReader,
) -> None:
    # OQ-30: the row shows the current preferred price; the stored financial_total stays that
    # of the last processing (10 × 95100) until the date is processed again.
    repository.positions[DAY] = (_position(DI1F28.id, 10, "951000"),)
    prices.set(DI1F28.id, DAY, "95300", PriceSource.MANUAL, "0.0970")

    (row,) = (await queries.get_position_table(DAY)).items

    assert row.reference_source is PriceSource.MANUAL
    assert row.reference_pu == Decimal("95300")
    assert row.financial_total == Decimal("951000")


async def test_after_maturity_the_reference_pu_is_zero_with_no_source(
    queries: PortfolioService, repository: InMemoryPortfolioRepository
) -> None:
    # OQ-1, OQ-30: the PU is 0 by definition after maturity.
    repository.positions[DAY] = (_position(DI1F27.id, 3, "0"),)

    (row,) = (await queries.get_position_table(DAY)).items

    assert row.reference_pu == Decimal("0")
    assert row.reference_source is None
    assert row.reference_rate is None


async def test_a_date_never_processed_has_no_rows(queries: PortfolioService) -> None:
    table = await queries.get_position_table(DAY)

    assert table.status is None
    assert table.published_at is None
    assert table.items == ()


AFTER = timedelta(seconds=1)
LATER = timedelta(minutes=1)
NEXT_DAY = timedelta(days=1)
D_PRICE_AT_RUN = (0, timedelta(0))
D_MINUS_1_LATER = (-1, LATER)


@pytest.mark.parametrize(
    ("asset", "registered", "held_before", "processed", "changed"),
    [
        pytest.param(DI1F28.id, [(0, AFTER)], None, True, True, id="d-price-set-after-the-run"),
        pytest.param(DI1F28.id, [D_PRICE_AT_RUN], None, True, False, id="d-price-set-at-the-run"),
        pytest.param(
            DI1F28.id, [(0, timedelta(minutes=-5))], None, True, False, id="d-price-set-before"
        ),
        # OQ-50 item 3: position P&L uses the D−1 price too while Q[D−1] ≠ 0 (OQ-4).
        pytest.param(
            DI1F28.id, [D_PRICE_AT_RUN, D_MINUS_1_LATER], 10, True, True, id="d-1-price-set-after"
        ),
        # OQ-4: with Q[D−1] = 0 position P&L is exactly 0 and the D−1 price is never used.
        pytest.param(
            DI1F28.id, [D_PRICE_AT_RUN, D_MINUS_1_LATER], None, True, False, id="d-1-first-buy-on-d"
        ),
        pytest.param(
            DI1F28.id, [D_PRICE_AT_RUN, D_MINUS_1_LATER], 0, True, False, id="d-1-closed-on-d-1"
        ),
        pytest.param(
            DI1F28.id,
            [(1, NEXT_DAY), (-2, NEXT_DAY)],
            None,
            True,
            False,
            id="other-dates-set-later",
        ),
        pytest.param(DI1F28.id, [], None, True, False, id="no-price"),
        pytest.param(DI1F28.id, [(0, NEXT_DAY)], None, False, False, id="no-processing-time"),
        # OQ-1: the PU is 0 by definition after maturity, whatever the price table holds.
        pytest.param(DI1F27.id, [(0, NEXT_DAY)], None, True, False, id="after-maturity"),
    ],
)
async def test_a_row_is_marked_when_a_price_it_used_was_set_after_the_processing(
    queries: PortfolioService,
    repository: InMemoryPortfolioRepository,
    statuses: FakeDateStatusReader,
    prices: FakePriceReader,
    asset: UUID,
    registered: list[tuple[int, timedelta]],
    held_before: int | None,
    processed: bool,
    changed: bool,
) -> None:
    # OQ-50 item 3: the stored figures come from the D and D−1 prices the run read; prices are
    # re-registered as a new row, so ``created_at`` is the time of the last set (OQ-25).
    repository.positions[DAY] = (_position(asset, 10, "951000"),)
    if held_before is not None:
        repository.positions[YESTERDAY] = (_position(asset, held_before, "0"),)
    if processed:
        statuses.statuses[DAY] = _status(DAY, PROCESSED, None)
    for offset, set_at in registered:
        pu = "95300" if offset == 0 else "95000"
        on = DAY + timedelta(days=offset)
        prices.set(asset, on, pu, PriceSource.MANUAL, "0.0970", created_at=POSITIONS_AT + set_at)

    (row,) = (await queries.get_position_table(DAY)).items

    assert row.reference_price_changed is changed
    if asset == DI1F28.id and any(offset == 0 for offset, _ in registered):
        assert row.reference_pu == Decimal("95300")  # the row shows D's price, never D−1's


# --- P&L series ----------------------------------------------------------------------------------

Day = tuple[ChainStatus | None, ChainStatus | None, str | None] | None  # positions, cash, daily


@pytest.mark.parametrize(
    ("days", "range_sums"),
    [
        # D: 10; D+1: 5 → 15; D+2 not processed → 15; D+3: 7 → 22; D+4 not processed → 22.
        pytest.param(
            [(PROCESSED, None, "10"), (PROCESSED, None, "5"), None, (PROCESSED, None, "7"), None],
            ["10", "15", "15", "22", "22"],
            id="every-date-is-a-point-and-a-gap-adds-zero",
        ),
        # D+1 processed with a missing price (daily null) adds 0 and keeps its status.
        pytest.param(
            [(WITH_ISSUES, None, "10"), (WITH_ISSUES, None, None), (WITH_ISSUES, None, "5")],
            ["10", "10", "15"],
            id="missing-price-day",
        ),
        # OQ-41 item 4 (user, M2): a FAILED or RUNNING day shows its status and no daily P&L,
        # even over an older row (daily 999).
        pytest.param(
            [(PROCESSED, None, "100"), (FAILED, None, "999"), (PROCESSED, None, "-40")],
            ["100", "100", "60"],
            id="failed-day-over-an-older-row",
        ),
        pytest.param(
            [(PROCESSED, None, "100"), (RUNNING, None, "999"), (PROCESSED, None, "-40")],
            ["100", "100", "60"],
            id="running-day-over-an-older-row",
        ),
        pytest.param([None, (PROCESSED, None, "-3")], ["0", "-3"], id="range-starting-on-a-gap"),
        # Freshness comes only from date_status (OQ-23): a row with no positions status is ignored.
        pytest.param([(None, PROCESSED, "10")], ["0"], id="row-without-a-positions-status"),
    ],
)
async def test_the_range_sum_adds_only_processed_daily_pnl(
    queries: PortfolioService,
    repository: InMemoryPortfolioRepository,
    statuses: FakeDateStatusReader,
    days: list[Day],
    range_sums: list[str],
) -> None:
    # OQ-41: one point per calendar date of the range; the range sum never goes null.
    dates = [DAY + timedelta(days=n) for n in range(len(days))]
    for on, day in zip(dates, days, strict=True):
        if day is not None:
            positions, cash, daily = day
            repository.days[on] = _day(on, daily, "100")
            statuses.statuses[on] = _status(on, positions, cash)

    points = await queries.get_pnl_series(dates[0], dates[-1])

    assert [p.date for p in points] == dates
    assert [p.range_cumulative_pnl for p in points] == [Decimal(s) for s in range_sums]
    for point, day in zip(points, days, strict=True):
        positions, _, daily = day if day is not None else (None, None, None)
        processed = positions in (PROCESSED, WITH_ISSUES)
        assert point.status is positions
        assert point.daily_pnl == (Decimal(daily) if processed and daily is not None else None)


async def test_a_start_after_the_end_is_an_invalid_range(queries: PortfolioService) -> None:
    with pytest.raises(DomainError) as raised:
        await queries.get_pnl_series(DAY, DAY - timedelta(days=1))

    (detail,) = raised.value.errors
    assert detail.code is ErrorCode.INVALID_RANGE
    assert detail.field == "start_date"


async def test_a_range_of_at_most_3660_dates_is_read(queries: PortfolioService) -> None:
    # TODAY − 3659 days .. TODAY is 3,660 dates, ends included; one more is refused.
    points = await queries.get_pnl_series(TODAY - timedelta(days=3659), TODAY)
    assert len(points) == 3660

    with pytest.raises(DomainError) as raised:
        await queries.get_pnl_series(TODAY - timedelta(days=3660), TODAY)

    (detail,) = raised.value.errors
    assert (detail.code, detail.message, detail.field) == (
        ErrorCode.INVALID_RANGE,
        "O período deve ter no máximo 3.660 dias.",
        "end_date",
    )


# --- dates after today (OQ-35: São Paulo, injected clock) ---------------------------------------


def _summary(service: PortfolioService) -> Awaitable[Any]:
    return service.get_summary(TODAY + timedelta(days=1))


def _table(service: PortfolioService) -> Awaitable[Any]:
    return service.get_position_table(TODAY + timedelta(days=1))


def _series(service: PortfolioService) -> Awaitable[Any]:
    return service.get_pnl_series(DAY, TODAY + timedelta(days=1))


@pytest.mark.parametrize(
    ("read", "field"),
    [
        pytest.param(_summary, "date", id="summary"),
        pytest.param(_table, "date", id="position-table"),
        pytest.param(_series, "end_date", id="pnl-series"),
    ],
)
async def test_a_read_after_today_is_a_future_date(
    queries: PortfolioService,
    read: Callable[[PortfolioService], Awaitable[Any]],
    field: str,
) -> None:
    with pytest.raises(DomainError) as raised:
        await read(queries)

    (detail,) = raised.value.errors
    assert (detail.code, detail.message, detail.field) == (
        ErrorCode.FUTURE_DATE,
        FUTURE_MESSAGE,
        field,
    )


async def test_today_is_read(queries: PortfolioService) -> None:
    assert (await queries.get_summary(TODAY)).date == TODAY
    assert (await queries.get_position_table(TODAY)).items == ()
    assert (await queries.get_pnl_series(DAY, TODAY))[-1].date == TODAY  # every date (OQ-41)


async def test_a_reversed_range_ending_after_today_reports_both(
    queries: PortfolioService,
) -> None:
    with pytest.raises(DomainError) as raised:
        await queries.get_pnl_series(TODAY + timedelta(days=3), TODAY + timedelta(days=2))

    assert [(e.code, e.field) for e in raised.value.errors] == [
        (ErrorCode.INVALID_RANGE, "start_date"),
        (ErrorCode.FUTURE_DATE, "end_date"),
    ]
