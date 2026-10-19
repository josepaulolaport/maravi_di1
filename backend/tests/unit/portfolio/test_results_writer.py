"""`PortfolioResultsWriter`: one date of each chain, mapped onto the published rows (OQ-10, OQ-21,
OQ-23, OQ-28, OQ-30)."""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.pnl.public import AssetPnLResult, CalculationCompleteness, PortfolioPnLResult
from di1.modules.portfolio.application.interfaces.repository import (
    PublishedCash,
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.portfolio.application.services.results_writer import ResultsWriter
from di1.modules.portfolio.domain.cash import CashDay
from di1.modules.portfolio.domain.positions import PositionDay, PositionsDay
from di1.modules.portfolio.domain.trade import Trade
from di1.modules.portfolio.domain.valuation import (
    AssetValuation,
    PortfolioValuation,
    ReferenceSource,
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
                ReferenceSource.MANUAL,
                Decimal("951000"),
                ValuationStatus.COMPLETE,
            )
            for a in asset_ids
        ),
        positions_market_value=None if market_value is None else Decimal(market_value),
        aum=Decimal("123"),  # never stored: the writer recomputes AUM from the published cash
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
    cumulative_status=COMPLETE,
    incomplete_assets=frozenset(),
)


@pytest.fixture
def repository() -> InMemoryPortfolioRepository:
    return InMemoryPortfolioRepository()


@pytest.fixture
def writer(repository: InMemoryPortfolioRepository) -> ResultsWriter:
    return ResultsWriter(lambda uow: repository)


async def test_a_positions_day_maps_onto_the_published_rows(
    writer: ResultsWriter, repository: InMemoryPortfolioRepository
) -> None:
    await writer.write_positions_day(
        _positions(DI1F27), _valuation(DI1F27), _asset_pnl(DI1F27), PNL, uow=FakeUnitOfWork()
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
    writer: ResultsWriter, repository: InMemoryPortfolioRepository
) -> None:
    # OQ-21, OQ-28: AUM = cash + market value of the date: 49000 + 951000.
    cash = CashDay(
        DAY, Decimal("0"), Decimal("-950000"), Decimal("999000"), Decimal("0"), Decimal("49000")
    )
    await writer.write_cash_day(cash, uow=FakeUnitOfWork())
    await writer.write_positions_day(
        _positions(DI1F27), _valuation(DI1F27), _asset_pnl(DI1F27), PNL, uow=FakeUnitOfWork()
    )

    assert repository.days[DAY].aum == Decimal("1000000")


async def test_a_missing_market_value_is_stored_missing(
    writer: ResultsWriter, repository: InMemoryPortfolioRepository
) -> None:
    await writer.write_positions_day(
        _positions(DI1F27),
        _valuation(DI1F27, market_value=None),
        _asset_pnl(DI1F27),
        PNL,
        uow=FakeUnitOfWork(),
    )

    assert repository.days[DAY].positions_market_value is None
    assert repository.days[DAY].valuation_status is MISSING


async def test_a_cash_day_maps_onto_its_row(
    writer: ResultsWriter, repository: InMemoryPortfolioRepository
) -> None:
    cash = CashDay(
        DAY, Decimal("10"), Decimal("-5"), Decimal("100.25"), Decimal("0.25"), Decimal("105")
    )

    await writer.write_cash_day(cash, uow=FakeUnitOfWork())

    assert repository.cash[DAY] == PublishedCash(
        date=DAY,
        cash_balance=Decimal("105"),
        trades_cash_flow=Decimal("-5"),
        deposits=Decimal("100.25"),
        withdrawals=Decimal("0.25"),
    )


async def test_a_day_with_no_expected_asset_writes_only_the_portfolio_row(
    writer: ResultsWriter, repository: InMemoryPortfolioRepository
) -> None:
    # OQ-22 item 5: every position closed earlier; market value 0, P&L 0, cumulative carried.
    carried = PortfolioPnLResult(
        Decimal("0"), Decimal("0"), Decimal("0"), Decimal("1500"), COMPLETE, COMPLETE, frozenset()
    )
    await writer.write_positions_day(
        PositionsDay(DAY, ()), _valuation(market_value="0"), {}, carried, uow=FakeUnitOfWork()
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
    writer: ResultsWriter,
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
        )


async def test_the_valuation_must_be_of_the_same_date(writer: ResultsWriter) -> None:
    other_day = PortfolioValuation(
        DAY.replace(day=5), (), Decimal("0"), None, ValuationStatus.COMPLETE
    )
    with pytest.raises(ValueError):
        await writer.write_positions_day(
            PositionsDay(DAY, ()), other_day, {}, PNL, uow=FakeUnitOfWork()
        )


@pytest.mark.parametrize(
    ("market_value", "status"),
    [(None, ValuationStatus.COMPLETE), ("0", ValuationStatus.MISSING)],
)
async def test_a_market_value_must_match_its_status(
    writer: ResultsWriter, market_value: str | None, status: ValuationStatus
) -> None:
    # Unavailable data is never stored as complete, nor a figure as missing (spec §8.3).
    inconsistent = PortfolioValuation(
        DAY, (), None if market_value is None else Decimal(market_value), None, status
    )
    with pytest.raises(ValueError):
        await writer.write_positions_day(
            PositionsDay(DAY, ()), inconsistent, {}, PNL, uow=FakeUnitOfWork()
        )
