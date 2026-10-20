"""`PortfolioService`: published data and each date's chain statuses, never recalculated on
read (spec §11.4; OQ-23, OQ-27, OQ-28, OQ-30, OQ-31)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
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
from tests.support.fakes import FakeClock
from tests.unit.portfolio.factories import DAY, DI1F27, DI1F28, DI1F29
from tests.unit.portfolio.fakes import (
    FakeAssetReader,
    FakeDateStatusReader,
    FakePriceReader,
    InMemoryPortfolioRepository,
    stored_cash,
)

TODAY = DAY + timedelta(days=10)
COMPLETE = CalculationCompleteness.COMPLETE
ZERO = Decimal("0")
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
        (DI1F27, "DI1F27", DAY - timedelta(days=1)),  # matured yesterday
        (DI1F28, "DI1F28", date(2028, 1, 3)),
        (DI1F29, "DI1F29", date(2029, 1, 2)),
    )
    return DefaultPortfolioService(
        repository,
        assets=assets,
        prices=prices,
        date_statuses=statuses,
        clock=FakeClock(TODAY),
    )


class TestSummary:
    async def test_a_processed_date_shows_both_chains_and_aum_computed_on_read(
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        repository.cash[DAY] = stored_cash(
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
        assert summary.aum == Decimal("1000000")  # 50000 cash + 950000 market value, on read
        assert statuses.reads == 1  # on the published rows' session (the composition's wiring)
        assert repository.snapshots == 1  # started once, before any read

    async def test_a_date_never_processed_is_all_null_never_zero(
        self, queries: PortfolioService
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
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        repository.cash[DAY] = stored_cash(
            DAY, Decimal("7"), Decimal("0"), Decimal("7"), Decimal("0")
        )
        statuses.statuses[DAY] = _status(DAY, None, ChainStatus.PROCESSED)

        summary = await queries.get_summary(DAY)

        assert summary.cash.balance == Decimal("7")
        assert summary.positions.status is None
        assert summary.aum is None


class TestAumNeedsBothChainsProcessed:
    """OQ-21, OQ-38, OQ-40: AUM is computed on read from the date's published cash and market
    value, whichever runs wrote them, and only while both chains are PROCESSED or
    PROCESSED_WITH_ISSUES, so a later FAILED or RUNNING chain hides it (reviewer M1)."""

    @pytest.fixture(autouse=True)
    def published(self, repository: InMemoryPortfolioRepository) -> None:
        # D processed: cash 100 + market value 50 → AUM 150.
        repository.cash[DAY] = stored_cash(DAY, Decimal("100"), ZERO, Decimal("100"), ZERO)
        repository.days[DAY] = replace(_day(DAY, "0"), positions_market_value=Decimal("50"))

    @pytest.mark.parametrize(
        ("positions", "cash"),
        [
            (ChainStatus.PROCESSED, ChainStatus.FAILED),
            (ChainStatus.FAILED, ChainStatus.PROCESSED),
            (ChainStatus.PROCESSED, ChainStatus.RUNNING),
            (ChainStatus.RUNNING, ChainStatus.PROCESSED_WITH_ISSUES),
            (ChainStatus.PROCESSED, None),
            (None, ChainStatus.PROCESSED),
        ],
    )
    async def test_aum_is_hidden_unless_both_chains_are_processed(
        self,
        queries: PortfolioService,
        statuses: FakeDateStatusReader,
        positions: ChainStatus | None,
        cash: ChainStatus | None,
    ) -> None:
        statuses.statuses[DAY] = _status(DAY, positions, cash)

        summary = await queries.get_summary(DAY)

        assert summary.aum is None
        assert summary.cash.balance == Decimal("100")  # each chain's own figures still show
        assert summary.positions.market_value == Decimal("50")

    @pytest.mark.parametrize("status", [ChainStatus.PROCESSED, ChainStatus.PROCESSED_WITH_ISSUES])
    async def test_aum_shows_when_both_chains_are_processed(
        self, queries: PortfolioService, statuses: FakeDateStatusReader, status: ChainStatus
    ) -> None:
        statuses.statuses[DAY] = _status(DAY, status, ChainStatus.PROCESSED)

        assert (await queries.get_summary(DAY)).aum == Decimal("150")

    async def test_a_missing_market_value_gives_no_aum(
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        # An expected asset without a reference price: the market value is unknown (OQ-10).
        repository.days[DAY] = replace(
            _day(DAY, None), positions_market_value=None, valuation_status=MISSING
        )
        statuses.statuses[DAY] = _status(
            DAY, ChainStatus.PROCESSED_WITH_ISSUES, ChainStatus.PROCESSED
        )

        summary = await queries.get_summary(DAY)

        assert summary.aum is None
        assert summary.cash.balance == Decimal("100")

    async def test_a_day_with_no_expected_asset_has_aum_equal_to_cash(
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        # OQ-22 item 5, OQ-38: no expected asset → market value 0 → AUM = cash.
        repository.days[DAY] = replace(_day(DAY, "0"), positions_market_value=ZERO)
        statuses.statuses[DAY] = _status(DAY, ChainStatus.PROCESSED, ChainStatus.PROCESSED)

        assert (await queries.get_summary(DAY)).aum == Decimal("100")

    async def test_the_aum_follows_a_cash_row_rewritten_after_the_positions(
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        # A later CASH run republishes D with another balance: AUM follows on read (OQ-21).
        repository.cash[DAY] = stored_cash(DAY, Decimal("400"), ZERO, Decimal("400"), ZERO)
        statuses.statuses[DAY] = _status(DAY, ChainStatus.PROCESSED, ChainStatus.PROCESSED)

        assert (await queries.get_summary(DAY)).aum == Decimal("450")


class TestPositionTable:
    async def test_rows_carry_the_current_preferred_price_and_its_source(
        self,
        queries: PortfolioService,
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
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        prices: FakePriceReader,
    ) -> None:
        # OQ-30: the row shows the current preferred price; the stored financial_total stays that
        # of the last processing (10 × 95100) until the date is processed again.
        repository.positions[DAY] = (_position(DI1F28, 10, "951000"),)
        prices.add(DI1F28, DAY, PriceSource.MANUAL, "95300", "0.0970")

        (row,) = (await queries.get_position_table(DAY)).items

        assert row.reference_source is PriceSource.MANUAL
        assert row.reference_pu == Decimal("95300")
        assert row.financial_total == Decimal("951000")

    async def test_after_maturity_the_reference_pu_is_zero_with_no_source(
        self, queries: PortfolioService, repository: InMemoryPortfolioRepository
    ) -> None:
        # OQ-1, OQ-30: the PU is 0 by definition after maturity.
        repository.positions[DAY] = (_position(DI1F27, 3, "0"),)

        (row,) = (await queries.get_position_table(DAY)).items

        assert row.reference_pu == Decimal("0")
        assert row.reference_source is None
        assert row.reference_rate is None

    async def test_a_date_never_processed_has_no_rows(self, queries: PortfolioService) -> None:
        table = await queries.get_position_table(DAY)

        assert table.status is None
        assert table.published_at is None
        assert table.items == ()


class TestReferencePriceChanged:
    """OQ-50 item 3: a row is marked when the current preferred price of D, or of D−1 while
    Q[D−1] ≠ 0, was registered after the date's positions chain was processed, since its figures
    come from the prices the run read (OQ-30, OQ-31). Prices are re-registered with a new row, so
    ``created_at`` is the time of the last set (OQ-25)."""

    @pytest.fixture(autouse=True)
    def published(
        self, repository: InMemoryPortfolioRepository, statuses: FakeDateStatusReader
    ) -> None:
        repository.positions[DAY] = (_position(DI1F28, 10, "951000"),)
        statuses.statuses[DAY] = _status(DAY, ChainStatus.PROCESSED, None)

    async def test_a_price_set_after_the_processing_marks_the_row(
        self, queries: PortfolioService, prices: FakePriceReader
    ) -> None:
        prices.add(
            DI1F28,
            DAY,
            PriceSource.MANUAL,
            "95300",
            "0.0970",
            created_at=POSITIONS_AT + timedelta(seconds=1),
        )

        (row,) = (await queries.get_position_table(DAY)).items

        assert row.reference_price_changed is True

    @pytest.mark.parametrize("before", [timedelta(0), timedelta(minutes=-5)])
    async def test_a_price_set_before_or_at_the_processing_does_not(
        self, queries: PortfolioService, prices: FakePriceReader, before: timedelta
    ) -> None:
        prices.add(DI1F28, DAY, PriceSource.B3, "95100", "0.0990", created_at=POSITIONS_AT + before)

        (row,) = (await queries.get_position_table(DAY)).items

        assert row.reference_price_changed is False

    async def test_a_d_minus_1_price_set_after_the_processing_marks_the_row(
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        prices: FakePriceReader,
    ) -> None:
        # OQ-50 item 3: position P&L uses the D−1 price too while Q[D−1] ≠ 0 (OQ-4).
        repository.positions[DAY - timedelta(days=1)] = (_position(DI1F28, 10, "950000"),)
        prices.add(DI1F28, DAY, PriceSource.B3, "95100", "0.0990", created_at=POSITIONS_AT)
        prices.add(
            DI1F28,
            DAY - timedelta(days=1),
            PriceSource.MANUAL,
            "95000",
            "0.1000",
            created_at=POSITIONS_AT + timedelta(minutes=1),
        )

        (row,) = (await queries.get_position_table(DAY)).items

        assert row.reference_price_changed is True
        assert row.reference_pu == Decimal("95100")  # the row still shows D's price

    @pytest.mark.parametrize("previous", [None, 0], ids=["first-buy-on-d", "closed-on-d-1"])
    async def test_a_d_minus_1_price_is_ignored_while_q_d_minus_1_is_zero(
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        prices: FakePriceReader,
        previous: int | None,
    ) -> None:
        # OQ-4: with Q[D−1] = 0 position P&L is exactly 0 and the D−1 price is never used.
        if previous is not None:
            repository.positions[DAY - timedelta(days=1)] = (_position(DI1F28, previous, "0"),)
        prices.add(DI1F28, DAY, PriceSource.B3, "95100", "0.0990", created_at=POSITIONS_AT)
        prices.add(
            DI1F28,
            DAY - timedelta(days=1),
            PriceSource.MANUAL,
            "95000",
            "0.1000",
            created_at=POSITIONS_AT + timedelta(minutes=1),
        )

        (row,) = (await queries.get_position_table(DAY)).items

        assert row.reference_price_changed is False

    async def test_a_price_of_another_date_set_later_does_not_mark_the_row(
        self, queries: PortfolioService, prices: FakePriceReader
    ) -> None:
        later = POSITIONS_AT + timedelta(days=1)
        prices.add(DI1F28, DAY + timedelta(days=1), PriceSource.B3, "1", None, created_at=later)
        prices.add(DI1F28, DAY - timedelta(days=2), PriceSource.B3, "1", None, created_at=later)

        (row,) = (await queries.get_position_table(DAY)).items

        assert row.reference_price_changed is False

    async def test_no_price_does_not_mark_the_row(self, queries: PortfolioService) -> None:
        (row,) = (await queries.get_position_table(DAY)).items

        assert row.reference_price_changed is False

    async def test_a_date_without_a_processing_time_does_not_mark_the_row(
        self,
        queries: PortfolioService,
        prices: FakePriceReader,
        statuses: FakeDateStatusReader,
    ) -> None:
        statuses.statuses.pop(DAY)
        prices.add(
            DI1F28,
            DAY,
            PriceSource.MANUAL,
            "95300",
            "0.0970",
            created_at=POSITIONS_AT + timedelta(days=1),
        )

        (row,) = (await queries.get_position_table(DAY)).items

        assert row.reference_price_changed is False

    async def test_after_maturity_no_price_is_read_so_no_mark(
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        prices: FakePriceReader,
    ) -> None:
        # OQ-1: the PU is 0 by definition after maturity, whatever the price table holds.
        repository.positions[DAY] = (_position(DI1F27, 3, "0"),)
        prices.add(
            DI1F27, DAY, PriceSource.MANUAL, "1", None, created_at=POSITIONS_AT + timedelta(days=1)
        )

        (row,) = (await queries.get_position_table(DAY)).items

        assert row.reference_price_changed is False


class TestPnLSeries:
    """OQ-41: one point per calendar date of the range; the range sum never goes null, a date not
    processed or with a null daily P&L adding 0."""

    async def test_every_date_is_a_point_and_a_gap_adds_zero(
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        # D: 10; D+1: 5 → 15; D+2 not processed → 15; D+3: 7 → 22; D+4 not processed → 22.
        days = [DAY + timedelta(days=n) for n in range(5)]
        for on, daily in ((days[0], "10"), (days[1], "5"), (days[3], "7")):
            repository.days[on] = _day(on, daily, "100")
            statuses.statuses[on] = _status(on, ChainStatus.PROCESSED, None)

        points = await queries.get_pnl_series(days[0], days[4])

        assert [p.date for p in points] == days
        assert [p.range_cumulative_pnl for p in points] == [
            Decimal("10"),
            Decimal("15"),
            Decimal("15"),
            Decimal("22"),
            Decimal("22"),
        ]
        processed = [points[0], points[1], points[3]]
        assert all(p.status is ChainStatus.PROCESSED for p in processed)
        for gap in (points[2], points[4]):
            assert gap.status is None
            assert gap.daily_pnl is None

    async def test_a_missing_price_day_adds_zero_and_keeps_its_status(
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        # D: 10; D+1 processed with a missing price (daily null) → 10; D+2: 5 → 15.
        days = [DAY + timedelta(days=n) for n in range(3)]
        for on, daily in zip(days, ("10", None, "5"), strict=True):
            repository.days[on] = _day(on, daily)
            statuses.statuses[on] = _status(on, ChainStatus.PROCESSED_WITH_ISSUES, None)

        points = await queries.get_pnl_series(days[0], days[2])

        assert [p.range_cumulative_pnl for p in points] == [
            Decimal("10"),
            Decimal("10"),
            Decimal("15"),
        ]
        assert points[1].daily_pnl is None
        assert points[1].status is ChainStatus.PROCESSED_WITH_ISSUES

    @pytest.mark.parametrize("chain", [ChainStatus.FAILED, ChainStatus.RUNNING])
    async def test_a_failed_or_running_day_shows_its_status_and_adds_zero(
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
        chain: ChainStatus,
    ) -> None:
        # OQ-41 item 4 (user, M2): only PROCESSED/PROCESSED_WITH_ISSUES days add their daily P&L;
        # a FAILED or RUNNING day shows its status, no daily P&L, even over an older row.
        days = [DAY + timedelta(days=n) for n in range(3)]
        for on, daily in zip(days, ("100", "999", "-40"), strict=True):
            repository.days[on] = _day(on, daily, "1")
            statuses.statuses[on] = _status(on, ChainStatus.PROCESSED, None)
        statuses.statuses[days[1]] = _status(days[1], chain, None)

        points = await queries.get_pnl_series(days[0], days[2])

        assert [p.range_cumulative_pnl for p in points] == [
            Decimal("100"),
            Decimal("100"),
            Decimal("60"),
        ]
        stopped = points[1]
        assert stopped.status is chain
        assert stopped.daily_pnl is None

    async def test_case_27_an_unprocessed_day_adds_zero(
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        # Spec §13 case 27 (OQ-41): D1 100, D2 not processed, D3 −40 → 100, 100, 60.
        days = [DAY + timedelta(days=n) for n in range(3)]
        for on, daily in ((days[0], "100"), (days[2], "-40")):
            repository.days[on] = _day(on, daily)
            statuses.statuses[on] = _status(on, ChainStatus.PROCESSED, None)

        points = await queries.get_pnl_series(days[0], days[2])

        assert [p.range_cumulative_pnl for p in points] == [
            Decimal("100"),
            Decimal("100"),
            Decimal("60"),
        ]
        assert points[1].status is None

    async def test_a_range_starting_on_a_gap_sums_from_zero(
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        repository.days[DAY + timedelta(days=1)] = _day(DAY + timedelta(days=1), "-3")
        statuses.statuses[DAY + timedelta(days=1)] = _status(
            DAY + timedelta(days=1), ChainStatus.PROCESSED, None
        )

        points = await queries.get_pnl_series(DAY, DAY + timedelta(days=1))

        assert [p.range_cumulative_pnl for p in points] == [Decimal("0"), Decimal("-3")]

    async def test_a_row_without_a_positions_status_reads_not_processed(
        self,
        queries: PortfolioService,
        repository: InMemoryPortfolioRepository,
        statuses: FakeDateStatusReader,
    ) -> None:
        # Freshness comes only from date_status (OQ-23): a row with no positions status is ignored.
        repository.days[DAY] = _day(DAY, "10")
        statuses.statuses[DAY] = _status(DAY, None, ChainStatus.PROCESSED)

        (point,) = await queries.get_pnl_series(DAY, DAY)

        assert point.status is None
        assert point.daily_pnl is None
        assert point.range_cumulative_pnl == Decimal("0")

    async def test_a_start_after_the_end_is_an_invalid_range(
        self, queries: PortfolioService
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
        self, queries: PortfolioService
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

    async def test_today_is_read(self, queries: PortfolioService) -> None:
        assert (await queries.get_summary(TODAY)).date == TODAY
        assert (await queries.get_position_table(TODAY)).items == ()
        assert (await queries.get_pnl_series(DAY, TODAY))[-1].date == TODAY  # every date (OQ-41)

    async def test_a_pnl_series_ending_after_today_is_rejected_on_end_date(
        self, queries: PortfolioService
    ) -> None:
        with pytest.raises(DomainError) as raised:
            await queries.get_pnl_series(DAY, TODAY + timedelta(days=1))

        (detail,) = raised.value.errors
        assert (detail.code, detail.field) == (ErrorCode.FUTURE_DATE, "end_date")

    async def test_a_reversed_range_ending_after_today_reports_both(
        self, queries: PortfolioService
    ) -> None:
        with pytest.raises(DomainError) as raised:
            await queries.get_pnl_series(TODAY + timedelta(days=3), TODAY + timedelta(days=2))

        assert [(e.code, e.field) for e in raised.value.errors] == [
            (ErrorCode.INVALID_RANGE, "start_date"),
            (ErrorCode.FUTURE_DATE, "end_date"),
        ]
