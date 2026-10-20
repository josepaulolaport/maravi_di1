"""`PortfolioResultsWriter`: one date of each chain, mapped onto the published rows (OQ-10, OQ-21,
OQ-23, OQ-28, OQ-30)."""

from __future__ import annotations

from dataclasses import replace
from datetime import time
from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.pnl.public import AssetPnLResult, CalculationCompleteness, PortfolioPnLResult
from di1.modules.portfolio.application.ports import (
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.portfolio.application.services.results_writer import DefaultResultsWriter
from di1.modules.portfolio.domain.cash import CashDay
from di1.modules.portfolio.domain.positions import PositionDay, PositionsDay
from di1.modules.portfolio.domain.trade import Trade
from di1.modules.portfolio.domain.valuation import (
    AssetValuation,
    PortfolioValuation,
    ValuationStatus,
)
from tests.support.builders import DAY, DI1F27, DI1F28
from tests.unit.portfolio.fakes import InMemoryPortfolioRepository

COMPLETE = CalculationCompleteness.COMPLETE
MISSING = CalculationCompleteness.MISSING


def _buy(asset_id: UUID = DI1F27.id) -> Trade:
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
def writer(repository: InMemoryPortfolioRepository) -> DefaultResultsWriter:
    return DefaultResultsWriter(repository)


async def test_a_positions_day_maps_onto_the_published_rows(
    writer: DefaultResultsWriter, repository: InMemoryPortfolioRepository
) -> None:
    await writer.write_positions_day(
        _positions(DI1F27.id),
        _valuation(DI1F27.id),
        _asset_pnl(DI1F27.id),
        PNL,
    )

    assert repository.positions[DAY] == (
        PublishedPosition(
            asset_id=DI1F27.id,
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
        position_pnl=Decimal("0"),
        trades_pnl=Decimal("1000"),
        daily_pnl=Decimal("1000"),
        cumulative_pnl=Decimal("1500"),
        valuation_status=COMPLETE,
        pnl_status=COMPLETE,
    )


async def test_a_missing_market_value_is_stored_missing(
    writer: DefaultResultsWriter, repository: InMemoryPortfolioRepository
) -> None:
    await writer.write_positions_day(
        _positions(DI1F27.id),
        _valuation(DI1F27.id, market_value=None),
        _asset_pnl(DI1F27.id),
        PNL,
    )

    assert repository.days[DAY].positions_market_value is None
    assert repository.days[DAY].valuation_status is MISSING


async def test_a_cash_day_maps_onto_its_row(
    writer: DefaultResultsWriter, repository: InMemoryPortfolioRepository
) -> None:
    cash = CashDay(
        DAY, Decimal("10"), Decimal("-5"), Decimal("100.25"), Decimal("0.25"), Decimal("105")
    )

    await writer.write_cash_day(cash)

    assert repository.cash[DAY] == cash


async def test_a_day_with_no_expected_asset_writes_only_the_portfolio_row(
    writer: DefaultResultsWriter, repository: InMemoryPortfolioRepository
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
        ((DI1F27.id,), (DI1F27.id, DI1F28.id), (DI1F27.id,)),
        ((DI1F27.id, DI1F28.id), (DI1F27.id, DI1F28.id), (DI1F27.id,)),
        ((DI1F27.id,), (DI1F27.id,), (DI1F27.id, DI1F28.id)),
    ],
)
async def test_the_three_inputs_must_cover_the_same_assets(
    writer: DefaultResultsWriter,
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
        )


async def test_the_valuation_must_be_of_the_same_date(writer: DefaultResultsWriter) -> None:
    other_day = replace(_valuation(DI1F27.id), date=DAY.replace(day=5))
    with pytest.raises(ValueError):
        await writer.write_positions_day(
            _positions(DI1F27.id),
            other_day,
            _asset_pnl(DI1F27.id),
            PNL,
        )


@pytest.mark.parametrize(
    ("market_value", "status"),
    [(None, ValuationStatus.COMPLETE), ("0", ValuationStatus.MISSING)],
)
async def test_a_market_value_must_match_its_status(
    writer: DefaultResultsWriter, market_value: str | None, status: ValuationStatus
) -> None:
    # Unavailable data is never stored as complete, nor a figure as missing (spec §8.3).
    inconsistent = replace(
        _valuation(DI1F27.id),
        positions_market_value=None if market_value is None else Decimal(market_value),
        status=status,
    )
    with pytest.raises(ValueError):
        await writer.write_positions_day(
            _positions(DI1F27.id),
            inconsistent,
            _asset_pnl(DI1F27.id),
            PNL,
        )


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
    writer: DefaultResultsWriter, market_value: str | None, pnl: PortfolioPnLResult
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
        )
