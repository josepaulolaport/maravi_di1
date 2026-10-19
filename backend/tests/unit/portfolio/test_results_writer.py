"""`PortfolioResultsWriter`: one date of each chain, mapped onto the published rows (OQ-10, OQ-21,
OQ-23, OQ-28, OQ-30)."""

from __future__ import annotations

from dataclasses import replace
from datetime import time
from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.pnl.public import AssetPnLResult, CalculationCompleteness, PortfolioPnLResult
from di1.modules.portfolio.application.services.repository import (
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.portfolio.application.services.results_writer import PortfolioResultsWriter
from di1.modules.portfolio.domain.cash import CashDay
from di1.modules.portfolio.domain.positions import PositionDay, PositionsDay
from di1.modules.portfolio.domain.trade import Trade
from di1.modules.portfolio.domain.valuation import (
    AssetValuation,
    PortfolioValuation,
    ValuationStatus,
)
from tests.unit.portfolio.factories import DAY, DI1F27, DI1F28
from tests.unit.portfolio.fakes import FakeUnitOfWork, InMemoryPortfolioRepository

COMPLETE = CalculationCompleteness.COMPLETE
MISSING = CalculationCompleteness.MISSING


def _buy(asset_id: UUID = DI1F27) -> Trade:
    return Trade(asset_id, DAY, time(10), 1, 10, Decimal("95000"), Decimal("0.105"))


def _positions(*asset_ids: UUID) -> PositionsDay:
    return PositionsDay(
        date=DAY,
        positions=tuple(
            PositionDay(a, 0, 10, Decimal("95000"), Decimal("0.105"), (_buy(a),)) for a in asset_ids
        ),
    )


def _valuation(*asset_ids: UUID, market_value: str | None = "951000") -> PortfolioValuation:
    return PortfolioValuation(
        date=DAY,
        assets=tuple(
            AssetValuation(
                a,
                Decimal("95100"),
                Decimal("951000"),
                ValuationStatus.COMPLETE,
            )
            for a in asset_ids
        ),
        positions_market_value=None if market_value is None else Decimal(market_value),
        status=ValuationStatus.COMPLETE if market_value is not None else ValuationStatus.MISSING,
    )


def _asset_pnl(*asset_ids: UUID) -> dict[UUID, AssetPnLResult]:
    return {
        a: AssetPnLResult(Decimal("0"), Decimal("1000"), Decimal("1000"), COMPLETE, frozenset())
        for a in asset_ids
    }


PNL = PortfolioPnLResult(
    position_pnl=Decimal("0"),
    trades_pnl=Decimal("1000"),
    daily_pnl=Decimal("1000"),
    cumulative_pnl=Decimal("1500"),
    status=COMPLETE,
)


@pytest.fixture
def repository() -> InMemoryPortfolioRepository:
    return InMemoryPortfolioRepository()


@pytest.fixture
def writer(repository: InMemoryPortfolioRepository) -> PortfolioResultsWriter:
    return PortfolioResultsWriter(lambda uow: repository)


async def test_a_positions_day_maps_onto_the_published_rows(
    writer: PortfolioResultsWriter, repository: InMemoryPortfolioRepository
) -> None:
    await writer.write_positions_day(
        _positions(DI1F27),
        _valuation(DI1F27),
        _asset_pnl(DI1F27),
        PNL,
        uow=FakeUnitOfWork(),
        other_chain_processed=True,
    )

    assert repository.positions[DAY] == (
        PublishedPosition(
            asset_id=DI1F27,
            quantity=10,
            average_entry_pu=Decimal("95000"),
            average_entry_rate=Decimal("0.105"),
            financial_total=Decimal("951000"),
            position_pnl=Decimal("0"),
            trades_pnl=Decimal("1000"),
            daily_pnl=Decimal("1000"),
            valuation_status=ValuationStatus.COMPLETE,
            pnl_status=COMPLETE,
        ),
    )
    assert repository.days[DAY] == PublishedPortfolioDay(
        date=DAY,
        positions_market_value=Decimal("951000"),
        aum=None,  # no cash published yet
        position_pnl=Decimal("0"),
        trades_pnl=Decimal("1000"),
        daily_pnl=Decimal("1000"),
        cumulative_pnl=Decimal("1500"),
        valuation_status=COMPLETE,
        pnl_status=COMPLETE,
    )


async def test_the_valuation_aum_is_ignored_and_recomputed_from_the_published_cash(
    writer: PortfolioResultsWriter, repository: InMemoryPortfolioRepository
) -> None:
    # OQ-21, OQ-28: AUM = cash + market value of the date: 49000 + 951000.
    cash = CashDay(
        DAY, Decimal("0"), Decimal("-950000"), Decimal("999000"), Decimal("0"), Decimal("49000")
    )
    await writer.write_cash_day(cash, uow=FakeUnitOfWork(), other_chain_processed=True)
    await writer.write_positions_day(
        _positions(DI1F27),
        _valuation(DI1F27),
        _asset_pnl(DI1F27),
        PNL,
        uow=FakeUnitOfWork(),
        other_chain_processed=True,
    )

    assert repository.days[DAY].aum == Decimal("1000000")


async def test_a_missing_market_value_is_stored_missing(
    writer: PortfolioResultsWriter, repository: InMemoryPortfolioRepository
) -> None:
    await writer.write_positions_day(
        _positions(DI1F27),
        _valuation(DI1F27, market_value=None),
        _asset_pnl(DI1F27),
        PNL,
        uow=FakeUnitOfWork(),
        other_chain_processed=True,
    )

    assert repository.days[DAY].positions_market_value is None
    assert repository.days[DAY].valuation_status is MISSING


async def test_a_cash_day_maps_onto_its_row(
    writer: PortfolioResultsWriter, repository: InMemoryPortfolioRepository
) -> None:
    cash = CashDay(
        DAY, Decimal("10"), Decimal("-5"), Decimal("100.25"), Decimal("0.25"), Decimal("105")
    )

    await writer.write_cash_day(cash, uow=FakeUnitOfWork(), other_chain_processed=True)

    assert repository.cash[DAY] == cash


async def test_a_day_with_no_expected_asset_writes_only_the_portfolio_row(
    writer: PortfolioResultsWriter, repository: InMemoryPortfolioRepository
) -> None:
    # OQ-22 item 5: every position closed earlier; market value 0, P&L 0, cumulative carried.
    carried = PortfolioPnLResult(
        Decimal("0"), Decimal("0"), Decimal("0"), Decimal("1500"), COMPLETE
    )
    await writer.write_positions_day(
        PositionsDay(DAY, ()),
        _valuation(market_value="0"),
        {},
        carried,
        uow=FakeUnitOfWork(),
        other_chain_processed=True,
    )

    day = repository.days[DAY]
    assert repository.positions[DAY] == ()
    assert day.positions_market_value == Decimal("0")
    assert (day.position_pnl, day.trades_pnl, day.daily_pnl) == (Decimal("0"),) * 3
    assert day.valuation_status is COMPLETE
    assert day.pnl_status is COMPLETE
    assert day.cumulative_pnl == Decimal("1500")


@pytest.mark.parametrize(
    ("positions", "valued", "with_pnl"),
    [
        ((DI1F27,), (DI1F27, DI1F28), (DI1F27,)),
        ((DI1F27, DI1F28), (DI1F27, DI1F28), (DI1F27,)),
        ((DI1F27,), (DI1F27,), (DI1F27, DI1F28)),
    ],
)
async def test_the_three_inputs_must_cover_the_same_assets(
    writer: PortfolioResultsWriter,
    positions: tuple[UUID, ...],
    valued: tuple[UUID, ...],
    with_pnl: tuple[UUID, ...],
) -> None:
    with pytest.raises(ValueError):
        await writer.write_positions_day(
            _positions(*positions),
            _valuation(*valued),
            _asset_pnl(*with_pnl),
            PNL,
            uow=FakeUnitOfWork(),
            other_chain_processed=True,
        )


async def test_the_valuation_must_be_of_the_same_date(writer: PortfolioResultsWriter) -> None:
    other_day = replace(_valuation(DI1F27), date=DAY.replace(day=5))
    with pytest.raises(ValueError):
        await writer.write_positions_day(
            _positions(DI1F27),
            other_day,
            _asset_pnl(DI1F27),
            PNL,
            uow=FakeUnitOfWork(),
            other_chain_processed=True,
        )


@pytest.mark.parametrize(
    ("market_value", "status"),
    [(None, ValuationStatus.COMPLETE), ("0", ValuationStatus.MISSING)],
)
async def test_a_market_value_must_match_its_status(
    writer: PortfolioResultsWriter, market_value: str | None, status: ValuationStatus
) -> None:
    # Unavailable data is never stored as complete, nor a figure as missing (spec §8.3).
    inconsistent = replace(
        _valuation(DI1F27),
        positions_market_value=None if market_value is None else Decimal(market_value),
        status=status,
    )
    with pytest.raises(ValueError):
        await writer.write_positions_day(
            _positions(DI1F27),
            inconsistent,
            _asset_pnl(DI1F27),
            PNL,
            uow=FakeUnitOfWork(),
            other_chain_processed=True,
        )


class TestOtherChainProcessed:
    """OQ-38: AUM is cash + market value only when the other chain of the date is processed
    (PROCESSED or PROCESSED_WITH_ISSUES); otherwise it is written null."""

    CASH = CashDay(
        DAY, Decimal("0"), Decimal("0"), Decimal("49000"), Decimal("0"), Decimal("49000")
    )

    async def _positions_day(
        self, writer: PortfolioResultsWriter, other_chain_processed: bool
    ) -> None:
        await writer.write_positions_day(
            _positions(DI1F27),
            _valuation(DI1F27),
            _asset_pnl(DI1F27),
            PNL,
            uow=FakeUnitOfWork(),
            other_chain_processed=other_chain_processed,
        )

    async def test_positions_with_unprocessed_cash_write_a_null_aum(
        self, writer: PortfolioResultsWriter, repository: InMemoryPortfolioRepository
    ) -> None:
        # Cash rows of D exist (e.g. kept from before) but D's cash chain is FAILED.
        await writer.write_cash_day(self.CASH, uow=FakeUnitOfWork(), other_chain_processed=False)
        await self._positions_day(writer, other_chain_processed=False)

        assert repository.days[DAY].aum is None

    async def test_positions_with_processed_cash_write_cash_plus_market_value(
        self, writer: PortfolioResultsWriter, repository: InMemoryPortfolioRepository
    ) -> None:
        await writer.write_cash_day(self.CASH, uow=FakeUnitOfWork(), other_chain_processed=False)
        await self._positions_day(writer, other_chain_processed=True)

        assert repository.days[DAY].aum == Decimal("1000000")  # 49000 + 951000

    async def test_cash_with_unprocessed_positions_writes_a_null_aum(
        self, writer: PortfolioResultsWriter, repository: InMemoryPortfolioRepository
    ) -> None:
        await self._positions_day(writer, other_chain_processed=True)
        await writer.write_cash_day(self.CASH, uow=FakeUnitOfWork(), other_chain_processed=False)

        assert repository.days[DAY].aum is None

    async def test_cash_with_processed_positions_writes_cash_plus_market_value(
        self, writer: PortfolioResultsWriter, repository: InMemoryPortfolioRepository
    ) -> None:
        await self._positions_day(writer, other_chain_processed=False)
        await writer.write_cash_day(self.CASH, uow=FakeUnitOfWork(), other_chain_processed=True)

        assert repository.days[DAY].aum == Decimal("1000000")

    async def test_an_all_run_writes_aum_on_its_second_call(
        self, writer: PortfolioResultsWriter, repository: InMemoryPortfolioRepository
    ) -> None:
        # OQ-38, OQ-40: ALL writes positions first, passed False, then cash, passed the positions
        # outcome; AUM is set by the second call.
        await self._positions_day(writer, other_chain_processed=False)
        assert repository.days[DAY].aum is None
        await writer.write_cash_day(self.CASH, uow=FakeUnitOfWork(), other_chain_processed=True)

        assert repository.days[DAY].aum == Decimal("1000000")


ZERO_PNL = PortfolioPnLResult(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("7"), COMPLETE)


@pytest.mark.parametrize(
    ("market_value", "pnl"),
    [
        ("1", ZERO_PNL),
        (None, ZERO_PNL),
        ("0", replace(ZERO_PNL, position_pnl=Decimal("1"), daily_pnl=Decimal("1"))),
        ("0", replace(ZERO_PNL, trades_pnl=Decimal("-1"), daily_pnl=Decimal("-1"))),
        ("0", replace(ZERO_PNL, position_pnl=None, daily_pnl=None, status=MISSING)),
    ],
)
async def test_a_day_with_no_expected_asset_has_zero_value_and_zero_pnl(
    writer: PortfolioResultsWriter, market_value: str | None, pnl: PortfolioPnLResult
) -> None:
    # OQ-22 item 5: with no expected asset the market value is 0 and position, trades and daily
    # P&L are exactly 0 (reviewer m4); anything else cannot come from an empty day.
    valuation = PortfolioValuation(
        DAY,
        (),
        None if market_value is None else Decimal(market_value),
        ValuationStatus.MISSING if market_value is None else ValuationStatus.COMPLETE,
    )
    with pytest.raises(ValueError):
        await writer.write_positions_day(
            PositionsDay(DAY, ()),
            valuation,
            {},
            pnl,
            uow=FakeUnitOfWork(),
            other_chain_processed=True,
        )
