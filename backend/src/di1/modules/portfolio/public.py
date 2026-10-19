"""Portfolio's public contract: the pure chains, the per-date writer, the predecessor readers and
the published read models (interfaces.md "Portfolio"; OQ-21, OQ-23, OQ-25, OQ-26, OQ-28).

Frozen in W0.3c. Lane E implements the writer, the readers and the query service. The read models
mirror the frozen HTTP contract (`frontend/src/api/contract/portfolio.ts` at 57b4df0); the HTTP
layer only renames and formats. A chain status of ``None`` is "not processed". Changes go through
the integrator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from di1.modules.pnl.public import AssetPnLResult, CalculationCompleteness, PortfolioPnLResult
from di1.modules.portfolio.domain.accounting import (
    AccountingDay,
    AccountingState,
    PortfolioAccounting,
)
from di1.modules.portfolio.domain.cash import CashBalance, CashCalculator, CashDay
from di1.modules.portfolio.domain.positions import (
    OpenPosition,
    PositionDay,
    PositionsDay,
    PositionsEngine,
    PositionState,
)
from di1.modules.portfolio.domain.trade import Trade
from di1.modules.portfolio.domain.valuation import (
    AssetValuation,
    AssetValuationInput,
    PortfolioValuation,
    ReferenceSource,
    ValuationCalculator,
    ValuationStatus,
)
from di1.modules.processing.public import ChainStatus
from di1.platform.database.unit_of_work import UnitOfWork

__all__ = [
    "AccountingDay",
    "AccountingState",
    "AssetValuation",
    "AssetValuationInput",
    "CashBalance",
    "CashCalculator",
    "CashDay",
    "CashSummaryView",
    "OpenPosition",
    "PnLPointView",
    "PortfolioAccounting",
    "PortfolioQueryService",
    "PortfolioReader",
    "PortfolioResultsWriter",
    "PortfolioSummaryView",
    "PortfolioValuation",
    "PositionDay",
    "PositionRowView",
    "PositionState",
    "PositionTableView",
    "PositionsDay",
    "PositionsEngine",
    "PositionsSummaryView",
    "PreviousPositionsDay",
    "ReferenceSource",
    "Trade",
    "ValuationCalculator",
    "ValuationStatus",
]


# --- Writing one date (OQ-23) -------------------------------------------------------------------


class PortfolioResultsWriter(Protocol):
    """Publishes one date of a chain inside Processing's date transaction; never commits. Each
    call upserts that date's rows and recomputes its AUM from the other chain's published value
    (OQ-21); ALL calls both in the same transaction."""

    async def write_positions_day(
        self,
        day: PositionsDay,
        valuation: PortfolioValuation,
        asset_pnl: Mapping[UUID, AssetPnLResult],
        pnl: PortfolioPnLResult,
        *,
        uow: UnitOfWork,
    ) -> None:
        """``positions``, ``position_metrics`` and ``portfolio_metrics`` for ``day.date``: the
        quantities and averages of ``day``, the valuation (reference PU and source, OQ-25) and the
        P&L of each expected asset (OQ-10), and the portfolio totals."""
        ...

    async def write_cash_day(self, day: CashDay, *, uow: UnitOfWork) -> None:
        """The ``cash_balances`` row for ``day.date``."""
        ...


# --- Predecessors (OQ-21, OQ-22, OQ-9) ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreviousPositionsDay:
    """What the positions chain of D needs from the published D−1: the closing state, the
    reference PU each asset was valued at (OQ-9) and the cumulative P&L (``None`` once the chain
    is broken, spec §8.3)."""

    state: PositionState
    reference_pus: Mapping[UUID, Decimal]
    cumulative_pnl: Decimal | None


class PortfolioReader(Protocol):
    """Published state of D−1, for Processing. Whether it is current is read from
    ``processing.date_status``, not from Portfolio (OQ-23)."""

    async def get_previous_positions(self, before_date: date) -> PreviousPositionsDay | None:
        """The positions chain published for ``before_date − 1``, or ``None`` if not published."""
        ...

    async def get_previous_cash(self, before_date: date) -> CashBalance | None:
        """The cash balance published for ``before_date − 1``, or ``None`` if not published."""
        ...


# --- Read models (HTTP contract at 57b4df0) -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class CashSummaryView:
    status: ChainStatus | None
    balance: Decimal | None
    trades_cash_flow: Decimal | None
    deposits: Decimal | None
    withdrawals: Decimal | None
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class PositionsSummaryView:
    status: ChainStatus | None
    published_at: datetime | None
    market_value: Decimal | None
    valuation_status: CalculationCompleteness | None
    position_pnl: Decimal | None
    trades_pnl: Decimal | None
    daily_pnl: Decimal | None
    cumulative_pnl: Decimal | None
    pnl_status: CalculationCompleteness | None


@dataclass(frozen=True, slots=True)
class PortfolioSummaryView:
    """``aum`` is a plain value with no status of its own: cash plus market value of the date,
    ``None`` when either side is missing (OQ-28)."""

    date: date
    cash: CashSummaryView
    positions: PositionsSummaryView
    aum: Decimal | None


@dataclass(frozen=True, slots=True)
class PositionRowView:
    asset_id: UUID
    asset_code: str
    maturity_date: date | None
    quantity: int
    average_entry_pu: Decimal | None
    average_entry_rate: Decimal | None
    reference_source: ReferenceSource | None
    reference_pu: Decimal | None
    reference_rate: Decimal | None
    financial_total: Decimal | None
    position_pnl: Decimal | None
    trades_pnl: Decimal | None
    daily_pnl: Decimal | None
    valuation_status: ValuationStatus
    pnl_status: CalculationCompleteness


@dataclass(frozen=True, slots=True)
class PositionTableView:
    date: date
    status: ChainStatus | None
    published_at: datetime | None
    items: tuple[PositionRowView, ...]


@dataclass(frozen=True, slots=True)
class PnLPointView:
    date: date
    daily_pnl: Decimal | None
    cumulative_pnl: Decimal | None
    pnl_status: CalculationCompleteness
    status: ChainStatus | None


class PortfolioQueryService(Protocol):
    """Published data only, never recalculated on read (spec §11.4); each date's chain statuses
    come from ``processing.date_status`` (OQ-23)."""

    async def get_summary(self, on: date) -> PortfolioSummaryView: ...

    async def get_position_table(self, on: date) -> PositionTableView: ...

    async def get_pnl_series(self, start_date: date, end_date: date) -> tuple[PnLPointView, ...]:
        """The published days of [start_date, end_date], in date order (OQ-16, OQ-27)."""
        ...
