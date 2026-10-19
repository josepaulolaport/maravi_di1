"""`PortfolioQueryService`: published data and each date's chain statuses, never recalculated on
read (spec §11.4; OQ-23, OQ-27, OQ-28, OQ-30, OQ-31)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.pnl.public import CalculationCompleteness
from di1.modules.portfolio.application.interfaces.repository import (
    PublishedCash,
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.portfolio.application.services.query_service import PortfolioQueries
from di1.modules.portfolio.domain.valuation import ReferenceSource, ValuationStatus
from di1.modules.prices.public import PriceSource
from di1.modules.processing.public import ChainStatus, DateStatus
from di1.shared.clock import FixedClock
from di1.shared.errors import DomainError, ErrorCode
from tests.unit.portfolio.factories import DAY, DI1F27, DI1F28, DI1F29
from tests.unit.portfolio.fakes import (
    FakeAssetReader,
    FakeDateStatusReader,
    FakePriceReader,
    FakeUnitOfWork,
    InMemoryPortfolioRepository,
)

TODAY = DAY + timedelta(days=10)
COMPLETE = CalculationCompleteness.COMPLETE
MISSING = CalculationCompleteness.MISSING
CASH_AT = datetime(2027, 1, 4, 21, 0, tzinfo=UTC)
POSITIONS_AT = datetime(2027, 1, 4, 21, 5, tzinfo=UTC)


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
        aum=Decimal("1000000"),
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
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def queries(
    repository: InMemoryPortfolioRepository,
    statuses: FakeDateStatusReader,
    prices: FakePriceReader,
    uow: FakeUnitOfWork,
) -> PortfolioQueries:
    assets = FakeAssetReader(
        (DI1F27, "DI1F27", DAY - timedelta(days=1)),  # matured yesterday
        (DI1F28, "DI1F28", date(2028, 1, 3)),
        (DI1F29, "DI1F29", date(2029, 1, 2)),
    )
    return PortfolioQueries(
        repository,
        uow=uow,
        assets=assets,
        prices=prices,
        date_statuses=statuses,
        clock=FixedClock(TODAY),
    )


class TestSummary:
    async def test_a_processed_date_shows_both_chains_and_the_stored_aum(
        self,
        queries: PortfolioQueries,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
        uow: FakeUnitOfWork,
    ) -> None:
        repository.cash[DAY] = PublishedCash(
            DAY, Decimal("50000"), Decimal("-950000"), Decimal("1000000"), Decimal("0")
        )
        repository.days[DAY] = _day(DAY, "10", "15")
        statuses.statuses[DAY] = _status(
            DAY, ChainStatus.PROCESSED_WITH_ISSUES, ChainStatus.PROCESSED
        )

        summary = await queries.get_summary(DAY)

        assert summary.date == DAY
        assert summary.cash.status is ChainStatus.PROCESSED
        assert summary.cash.balance == Decimal("50000")
        assert summary.cash.trades_cash_flow == Decimal("-950000")
        assert summary.cash.deposits == Decimal("1000000")
        assert summary.cash.withdrawals == Decimal("0")
        assert summary.cash.published_at == CASH_AT
        assert summary.positions.status is ChainStatus.PROCESSED_WITH_ISSUES
        assert summary.positions.published_at == POSITIONS_AT
        assert summary.positions.market_value == Decimal("950000")
        assert summary.positions.valuation_status is COMPLETE
        assert summary.positions.daily_pnl == Decimal("10")
        assert summary.positions.cumulative_pnl == Decimal("15")
        assert summary.positions.pnl_status is COMPLETE
        assert summary.aum == Decimal("1000000")
        assert statuses.seen_uows == [uow]  # read in the published rows' transaction
        assert repository.snapshots == 1  # started once, before any read

    async def test_a_date_never_processed_is_all_null_never_zero(
        self, queries: PortfolioQueries
    ) -> None:
        summary = await queries.get_summary(DAY)

        assert summary.cash.status is None
        assert summary.cash.balance is None
        assert summary.cash.published_at is None
        assert summary.positions.status is None
        assert summary.positions.market_value is None
        assert summary.positions.valuation_status is None
        assert summary.positions.pnl_status is None
        assert summary.aum is None

    async def test_cash_alone_has_no_aum(
        self,
        queries: PortfolioQueries,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        repository.cash[DAY] = PublishedCash(
            DAY, Decimal("7"), Decimal("0"), Decimal("7"), Decimal("0")
        )
        statuses.statuses[DAY] = _status(DAY, None, ChainStatus.PROCESSED)

        summary = await queries.get_summary(DAY)

        assert summary.cash.balance == Decimal("7")
        assert summary.positions.status is None
        assert summary.aum is None


class TestPositionTable:
    async def test_rows_carry_the_current_preferred_price_and_its_source(
        self,
        queries: PortfolioQueries,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
        prices: FakePriceReader,
    ) -> None:
        repository.positions[DAY] = (
            _position(DI1F29, -2, None),
            _position(DI1F28, 10, "951000"),
        )
        prices.add(DI1F28, DAY, PriceSource.B3, "95100", "0.0990")
        prices.add(DI1F28, DAY - timedelta(days=1), PriceSource.MANUAL, "1", "0.5")  # other date
        statuses.statuses[DAY] = _status(DAY, ChainStatus.PROCESSED, None)

        table = await queries.get_position_table(DAY)

        assert table.status is ChainStatus.PROCESSED
        assert table.published_at == POSITIONS_AT
        assert [r.asset_code for r in table.items] == ["DI1F28", "DI1F29"]
        priced, unpriced = table.items
        assert priced.maturity_date == date(2028, 1, 3)
        assert priced.quantity == 10
        assert priced.reference_source is ReferenceSource.B3
        assert priced.reference_pu == Decimal("95100")
        assert priced.reference_rate == Decimal("0.0990")
        assert priced.financial_total == Decimal("951000")
        assert unpriced.reference_source is None  # exact date only, no carry-forward
        assert unpriced.reference_pu is None
        assert unpriced.reference_rate is None
        assert unpriced.financial_total is None
        assert unpriced.valuation_status is ValuationStatus.MISSING

    async def test_a_corrected_price_shows_next_to_the_figures_of_the_last_processing(
        self,
        queries: PortfolioQueries,
        repository: InMemoryPortfolioRepository,
        prices: FakePriceReader,
    ) -> None:
        # OQ-30: the row shows the current preferred price; the stored financial_total stays that
        # of the last processing (10 × 95100) until the date is processed again.
        repository.positions[DAY] = (_position(DI1F28, 10, "951000"),)
        prices.add(DI1F28, DAY, PriceSource.MANUAL, "95300", "0.0970")

        (row,) = (await queries.get_position_table(DAY)).items

        assert row.reference_source is ReferenceSource.MANUAL
        assert row.reference_pu == Decimal("95300")
        assert row.financial_total == Decimal("951000")

    async def test_after_maturity_the_reference_pu_is_zero_with_no_source(
        self, queries: PortfolioQueries, repository: InMemoryPortfolioRepository
    ) -> None:
        # OQ-1, OQ-30: the PU is 0 by definition after maturity.
        repository.positions[DAY] = (_position(DI1F27, 3, "0"),)

        (row,) = (await queries.get_position_table(DAY)).items

        assert row.reference_pu == Decimal("0")
        assert row.reference_source is None
        assert row.reference_rate is None

    async def test_a_date_never_processed_has_no_rows(self, queries: PortfolioQueries) -> None:
        table = await queries.get_position_table(DAY)

        assert table.status is None
        assert table.published_at is None
        assert table.items == ()


class TestPnLSeries:
    async def test_points_sum_daily_pnl_from_the_start_and_break_at_a_gap(
        self,
        queries: PortfolioQueries,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        # OQ-31 item 8: Σ daily_pnl from start; null from the first day with null daily_pnl or no
        # published day. D: 10; D+1: 5 → 15; D+2 not processed; D+3: 7 → null (after the gap).
        days = [DAY + timedelta(days=n) for n in range(5)]
        for on, daily in ((days[0], "10"), (days[1], "5"), (days[3], "7")):
            repository.days[on] = _day(on, daily, "100")
            statuses.statuses[on] = _status(on, ChainStatus.PROCESSED, None)

        points = await queries.get_pnl_series(days[0], days[4])

        assert [p.date for p in points] == [days[0], days[1], days[3]]
        assert [p.range_cumulative_pnl for p in points] == [Decimal("10"), Decimal("15"), None]
        assert [p.cumulative_pnl for p in points] == [Decimal("100")] * 3  # stored, since inception
        assert all(p.status is ChainStatus.PROCESSED for p in points)
        assert all(p.published_at == POSITIONS_AT for p in points)

    async def test_a_null_daily_pnl_breaks_the_range_sum_from_that_day(
        self,
        queries: PortfolioQueries,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        days = [DAY + timedelta(days=n) for n in range(3)]
        for on, daily in zip(days, ("10", None, "5"), strict=True):
            repository.days[on] = _day(on, daily)
            statuses.statuses[on] = _status(on, ChainStatus.PROCESSED_WITH_ISSUES, None)

        points = await queries.get_pnl_series(days[0], days[2])

        assert [p.range_cumulative_pnl for p in points] == [Decimal("10"), None, None]
        assert points[1].pnl_status is MISSING

    async def test_a_row_without_a_positions_status_is_not_listed(
        self,
        queries: PortfolioQueries,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        # Only published days are listed, so a point always has a status (OQ-31 item 8).
        repository.days[DAY] = _day(DAY, "10")
        statuses.statuses[DAY] = _status(DAY, None, ChainStatus.PROCESSED)

        assert await queries.get_pnl_series(DAY, DAY) == ()

    async def test_a_start_after_the_end_is_an_invalid_range(
        self, queries: PortfolioQueries
    ) -> None:
        with pytest.raises(DomainError) as raised:
            await queries.get_pnl_series(DAY, DAY - timedelta(days=1))

        (detail,) = raised.value.errors
        assert detail.code is ErrorCode.INVALID_RANGE
        assert detail.field == "start_date"


class TestFutureDates:
    """OQ-35: a read dated after today (São Paulo, injected clock) is 422 FUTURE_DATE; today and
    earlier read as published."""

    FUTURE_MESSAGE = "A data não pode ser posterior a hoje."

    async def test_a_summary_or_table_after_today_is_rejected_on_date(
        self, queries: PortfolioQueries
    ) -> None:
        for read in (queries.get_summary, queries.get_position_table):
            with pytest.raises(DomainError) as raised:
                await read(TODAY + timedelta(days=1))
            (detail,) = raised.value.errors
            assert (detail.code, detail.message, detail.field) == (
                ErrorCode.FUTURE_DATE,
                self.FUTURE_MESSAGE,
                "date",
            )

    async def test_today_is_read(self, queries: PortfolioQueries) -> None:
        assert (await queries.get_summary(TODAY)).date == TODAY
        assert (await queries.get_position_table(TODAY)).items == ()
        assert await queries.get_pnl_series(DAY, TODAY) == ()

    async def test_a_pnl_series_ending_after_today_is_rejected_on_end_date(
        self, queries: PortfolioQueries
    ) -> None:
        with pytest.raises(DomainError) as raised:
            await queries.get_pnl_series(DAY, TODAY + timedelta(days=1))

        (detail,) = raised.value.errors
        assert (detail.code, detail.field) == (ErrorCode.FUTURE_DATE, "end_date")

    async def test_a_reversed_range_ending_after_today_reports_both(
        self, queries: PortfolioQueries
    ) -> None:
        with pytest.raises(DomainError) as raised:
            await queries.get_pnl_series(TODAY + timedelta(days=3), TODAY + timedelta(days=2))

        assert [(e.code, e.field) for e in raised.value.errors] == [
            (ErrorCode.INVALID_RANGE, "start_date"),
            (ErrorCode.FUTURE_DATE, "end_date"),
        ]
