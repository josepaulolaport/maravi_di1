"""Portfolio's public contract: the pure chains, the per-date writer, the predecessor readers and
the published read models (interfaces.md "Portfolio"; OQ-21, OQ-23, OQ-25, OQ-26, OQ-28).

Frozen in W0.3c. Lane E implements the writer, the readers and the query service. The read models
mirror the frozen HTTP contract (`frontend/src/api/contract/portfolio.ts` at 57b4df0, with the
OQ-31 status names, which lane I applies); the HTTP layer only renames and formats. A chain
status of ``None`` is "not processed"; each ``published_at`` is that chain's ``*_processed_at`` in
``processing.date_status`` ("Processado em dd/mm/aaaa hh:mm", OQ-31). Changes go through the
integrator.
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
    call replaces that date's rows (rows of assets no longer expected on the date are deleted,
    OQ-10) and recomputes the date's AUM from the other chain's published value (OQ-21).

    ``other_chain_processed`` is Processing's answer for the other chain on that date: ``True``
    when it is ``PROCESSED`` or ``PROCESSED_WITH_ISSUES``. When ``False`` (``FAILED`` or not
    processed) the written AUM is null (OQ-38). ALL writes both chains in the same transaction:
    the first call passes ``False`` and the second, made after both chains are computed, passes
    the first chain's outcome, so AUM never sees a chain ``RUNNING``."""

    async def write_positions_day(
        self,
        day: PositionsDay,
        valuation: PortfolioValuation,
        asset_pnl: Mapping[UUID, AssetPnLResult],
        pnl: PortfolioPnLResult,
        *,
        uow: UnitOfWork,
        other_chain_processed: bool,
    ) -> None:
        """``positions``, ``position_metrics`` and ``portfolio_metrics`` for ``day.date``: the
        quantities and averages of ``day``, each expected asset's ``financial_total`` and P&L
        (OQ-10), and the portfolio totals. The reference PU and source are not stored: they stay
        in the price table (OQ-30).

        The assets of ``day.positions``, ``valuation.assets`` and ``asset_pnl`` must be the same
        set, the expected assets of the date; the writer raises ``ValueError`` otherwise.
        ``valuation.aum`` is not stored: the written AUM is recomputed from the published cash,
        or null when ``other_chain_processed`` is ``False`` (OQ-38)."""
        ...

    async def write_cash_day(
        self, day: CashDay, *, uow: UnitOfWork, other_chain_processed: bool
    ) -> None:
        """The ``cash_balances`` row for ``day.date``, and the date's AUM (null when
        ``other_chain_processed`` is ``False``, OQ-38)."""
        ...


# --- Predecessors (OQ-21, OQ-22, OQ-9) ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreviousPositionsDay:
    """What the positions chain of D needs from the published D−1: the closing state and the
    cumulative P&L (``None`` once the chain is broken, spec §8.3). The D−1 reference PUs are not
    here: they come from the price table through ``PriceReader`` (OQ-30)."""

    state: PositionState
    cumulative_pnl: Decimal | None


class PortfolioReader(Protocol):
    """Published state of D−1, for Processing. Whether D−1 was processed is read from
    ``processing.date_status``, not from Portfolio (OQ-23, OQ-31): a published D−1 whose status
    is ``FAILED`` or absent is not used; Processing's status check decides."""

    async def get_previous_positions(self, before_date: date) -> PreviousPositionsDay | None:
        """The positions chain published for ``before_date − 1``, or ``None`` if not published.
        ``None`` is a usable start only in the zero state (no trade dated on or before
        ``before_date − 1``); otherwise ``before_date`` fails with
        ``POSITIONS_PREDECESSOR_MISSING`` and the run stops (OQ-31)."""
        ...

    async def get_previous_cash(self, before_date: date) -> CashBalance | None:
        """The cash balance published for ``before_date − 1``, or ``None`` if not published.
        ``None`` is a usable start only in the cash zero state (no active entry dated on or before
        ``before_date − 1``); otherwise ``before_date`` fails with ``CASH_PREDECESSOR_MISSING``
        and the run stops (OQ-31)."""
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
    """``reference_source``, ``reference_pu`` and ``reference_rate`` are the current preferred
    price of the date (MANUAL, else B3, exact date; PU 0 after maturity), read from the price
    table; the stored figures are those of the last processing, so after a price correction the
    two may differ until the user processes the date again (OQ-30, OQ-31)."""

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
    """One date of the positions chain for the Carteira chart (OQ-16, OQ-27, OQ-31 item 8).
    ``cumulative_pnl`` is the stored since-inception figure; ``range_cumulative_pnl`` is
    Σ ``daily_pnl`` from the requested start date to this date, summed in the backend on
    request."""

    date: date
    daily_pnl: Decimal | None
    cumulative_pnl: Decimal | None
    range_cumulative_pnl: Decimal | None
    """``None`` from the first date of the range whose ``daily_pnl`` is ``None`` or that has no
    published positions day."""
    pnl_status: CalculationCompleteness
    status: ChainStatus
    """A published day always has a status (never "not processed")."""
    published_at: datetime
    """When the positions chain of the date was last processed (OQ-31)."""


class PortfolioQueryService(Protocol):
    """Published data only, never recalculated on read (spec §11.4); each date's chain statuses
    come from ``processing.date_status`` (OQ-23), read in the same transaction as the published
    rows (``DateStatusReader`` takes the caller's Unit of Work), so figures and statuses always
    come from one snapshot."""

    async def get_summary(self, on: date) -> PortfolioSummaryView: ...

    async def get_position_table(self, on: date) -> PositionTableView: ...

    async def get_pnl_series(self, start_date: date, end_date: date) -> tuple[PnLPointView, ...]:
        """The published positions days of [start_date, end_date], in date order (OQ-16,
        OQ-27), each with its positions status and processing time only (OQ-31 item 8) and the
        running sum of ``daily_pnl`` from ``start_date``."""
        ...
