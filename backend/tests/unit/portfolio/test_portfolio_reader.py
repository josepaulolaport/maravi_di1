"""`PortfolioReader`: the published D−1 each chain starts from (OQ-21, OQ-22, OQ-31)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.pnl.public import CalculationCompleteness
from di1.modules.portfolio.application.ports import (
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.portfolio.application.services.portfolio_reader import DefaultPortfolioReader
from di1.modules.portfolio.domain.cash import CashBalance
from di1.modules.portfolio.domain.errors import PortfolioError
from di1.modules.portfolio.domain.positions import PositionState
from di1.modules.portfolio.domain.valuation import ValuationStatus
from tests.support.builders import DAY, DI1F27, DI1F28, open_position
from tests.unit.portfolio.fakes import InMemoryPortfolioRepository, stored_cash

YESTERDAY = DAY - timedelta(days=1)
COMPLETE = CalculationCompleteness.COMPLETE


def _published(
    asset_id: UUID, quantity: int, pu: str | None, rate: str | None
) -> PublishedPosition:
    return PublishedPosition(
        asset_id=asset_id,
        quantity=quantity,
        average_entry_pu=None if pu is None else Decimal(pu),
        average_entry_rate=None if rate is None else Decimal(rate),
        financial_total=Decimal("0"),
        position_pnl=Decimal("0"),
        trades_pnl=Decimal("0"),
        daily_pnl=Decimal("0"),
        valuation_status=ValuationStatus.COMPLETE,
        pnl_status=COMPLETE,
    )


def _portfolio_day(cumulative: str | None) -> PublishedPortfolioDay:
    return PublishedPortfolioDay(
        YESTERDAY,
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        None if cumulative is None else Decimal(cumulative),
        COMPLETE,
        COMPLETE,
    )


async def test_nothing_published_the_day_before_reads_none() -> None:
    reader = DefaultPortfolioReader(InMemoryPortfolioRepository())

    assert await reader.get_previous_positions(DAY) is None
    assert await reader.get_previous_cash(DAY) is None


async def test_the_positions_start_from_the_open_positions_and_cumulative_pnl() -> None:
    # A position closed on D−1 (quantity 0) is not carried: it is not expected on D (OQ-10).
    repository = InMemoryPortfolioRepository()
    repository.days[YESTERDAY] = _portfolio_day("-8034.1345282660")
    repository.positions[YESTERDAY] = (
        _published(DI1F27.id, 10, "95000.0000000000", "0.105000000000"),
        _published(DI1F28.id, 0, None, None),
    )

    previous = await DefaultPortfolioReader(repository).get_previous_positions(DAY)

    assert previous is not None
    assert previous.state == PositionState(
        as_of=YESTERDAY, positions=(open_position(10, "95000", "0.105"),)
    )
    assert previous.cumulative_pnl == Decimal("-8034.1345282660")


async def test_a_published_day_with_no_position_starts_empty() -> None:
    # OQ-22 item 5: a day with no expected asset is still published, with its cumulative P&L.
    repository = InMemoryPortfolioRepository()
    repository.days[YESTERDAY] = _portfolio_day(None)

    previous = await DefaultPortfolioReader(repository).get_previous_positions(DAY)

    assert previous is not None
    assert previous.state == PositionState.zero(YESTERDAY)
    assert previous.cumulative_pnl is None  # the chain was already broken


async def test_a_published_open_position_without_an_average_is_rejected() -> None:
    # A held position always carries its average entry PU and rate (spec §7.2): rows that disagree
    # are a technical fault, never a silent opening at an unknown price.
    repository = InMemoryPortfolioRepository()
    repository.days[YESTERDAY] = _portfolio_day("0")
    repository.positions[YESTERDAY] = (_published(DI1F27.id, 10, None, None),)

    with pytest.raises(PortfolioError, match="has no average"):
        await DefaultPortfolioReader(repository).get_previous_positions(DAY)


async def test_the_cash_starts_from_the_published_balance() -> None:
    repository = InMemoryPortfolioRepository()
    repository.cash[YESTERDAY] = stored_cash(YESTERDAY, Decimal("109090.9090909091"))

    previous = await DefaultPortfolioReader(repository).get_previous_cash(DAY)

    assert previous == CashBalance(as_of=YESTERDAY, balance=Decimal("109090.9090909091"))
