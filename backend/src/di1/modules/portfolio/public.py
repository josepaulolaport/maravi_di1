"""Portfolio's public contract (interfaces.md "Portfolio"; OQ-21, OQ-23, OQ-25, OQ-26, OQ-28): the
Protocols of the per-date writer, the predecessor reader and the read models; the DTOs and enums
they carry; and the pure chain functions Processing runs for a date (the three chains and the
maturity rule; the classes, engines and helpers behind them stay in ``domain/``). The read-model
views are defined here, not in ``domain/``, because they carry other modules' enums
(``ChainStatus``, ``PriceSource``), which a domain may not import. The read models
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
from di1.modules.portfolio.domain.cash import CashBalance, CashDay, calculate_cash_day
from di1.modules.portfolio.domain.maturity import is_past_maturity, reference_pu_on
from di1.modules.portfolio.domain.positions import (
    OpenPosition,
    PositionDay,
    PositionsDay,
    PositionState,
    calculate_positions_day,
)
from di1.modules.portfolio.domain.trade import Trade
from di1.modules.portfolio.domain.valuation import (
    AssetValuation,
    AssetValuationInput,
    PortfolioValuation,
    ValuationStatus,
    value_positions,
)
from di1.modules.prices.public import PriceSource
from di1.modules.processing.public import ChainStatus

__all__ = [
    "AssetValuation",
    "AssetValuationInput",
    "CashBalance",
    "CashDay",
    "CashSummaryView",
    "OpenPosition",
    "PnLPointView",
    "PortfolioReader",
    "PortfolioResultsWriter",
    "PortfolioService",
    "PortfolioSummaryView",
    "PortfolioValuation",
    "PositionDay",
    "PositionRowView",
    "PositionState",
    "PositionTableView",
    "PositionsDay",
    "PositionsSummaryView",
    "PreviousPositionsDay",
    "Trade",
    "ValuationStatus",
    "calculate_cash_day",
    "calculate_positions_day",
    "is_past_maturity",
    "reference_pu_on",
    "value_positions",
]


# --- Writing one date (OQ-23) -------------------------------------------------------------------


class PortfolioResultsWriter(Protocol):
    """Publishes one date of a chain inside Processing's date transaction (built on its session);
    never commits. Each
    call replaces that date's rows (rows of assets no longer expected on the date are deleted,
    OQ-10). AUM is not written: ``PortfolioService`` computes it on read from the date's
    published cash and market value when both chains are processed (OQ-21, OQ-38). ALL writes
    both chains in the same transaction, positions first, then cash (integrator choice); when only
    one chain is alive on an ALL date (OQ-36), Processing makes only that chain's call."""

    async def write_positions_day(
        self,
        day: PositionsDay,
        valuation: PortfolioValuation,
        asset_pnl: Mapping[UUID, AssetPnLResult],
        pnl: PortfolioPnLResult,
    ) -> None:
        """``positions``, ``position_metrics`` and ``portfolio_metrics`` for ``day.date``: the
        quantities and averages of ``day``, each expected asset's ``financial_total`` and P&L
        (OQ-10), and the portfolio totals. The reference PU and source are not stored: they stay
        in the price table (OQ-30).

        The assets of ``day.positions``, ``valuation.assets`` and ``asset_pnl`` must be the same
        set, the expected assets of the date; the writer raises ``PortfolioError`` otherwise."""
        ...

    async def write_cash_day(self, day: CashDay) -> None:
        """The ``cash_balances`` row for ``day.date``."""
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
    """``aum`` is a plain value with no status of its own, computed on read: cash plus market
    value of the date, ``None`` when either side is missing or when either chain of the date is
    not ``PROCESSED``/``PROCESSED_WITH_ISSUES`` (OQ-21, OQ-28, OQ-38)."""

    date: date
    cash: CashSummaryView
    positions: PositionsSummaryView
    aum: Decimal | None


@dataclass(frozen=True, slots=True)
class PositionRowView:
    """``reference_source``, ``reference_pu`` and ``reference_rate`` are the current preferred
    price of the date (MANUAL, else B3, exact date; PU 0 after maturity), read from the price
    table; the stored figures are those of the last processing, so after a price correction the
    two may differ until the user processes the date again (OQ-30, OQ-31).
    ``reference_price_changed`` marks that case (OQ-50 item 3): the current preferred price of
    the date, or of the day before while Q[D−1] ≠ 0 (position P&L uses it only then, OQ-4), was
    registered (``created_at``; a set always inserts a new row, OQ-25) after the date's positions
    chain was processed (``portfolio_processed_at``). It is ``False`` with no processing time, and
    when no such price is read (after maturity, OQ-1). Removing the preferred price so an older
    one becomes current is not marked: that price predates the run (integrator reading).
    ``created_at`` is the database's ``now()`` and ``portfolio_processed_at`` the worker's
    ``SystemClock``, on one host (integrator reading)."""

    asset_id: UUID
    asset_code: str
    maturity_date: date | None
    quantity: int
    average_entry_pu: Decimal | None
    average_entry_rate: Decimal | None
    reference_source: PriceSource | None
    reference_pu: Decimal | None
    reference_rate: Decimal | None
    reference_price_changed: bool
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
    """One calendar date of the Carteira chart (OQ-16, OQ-27, OQ-41, OQ-49).

    ``range_cumulative_pnl`` is Σ ``daily_pnl`` from the requested start, summed on request. A date
    adds its ``daily_pnl`` only when its positions status is ``PROCESSED`` or
    ``PROCESSED_WITH_ISSUES`` and ``daily_pnl`` is not ``None``; otherwise it adds 0. The stored
    since-inception ``cumulative_pnl`` and the processing time stay on the summary (OQ-49)."""

    date: date
    daily_pnl: Decimal | None
    range_cumulative_pnl: Decimal
    """Never ``None``: a date without a usable daily P&L adds 0 (OQ-41)."""
    status: ChainStatus | None
    """The positions chain of the date; ``None`` is not processed, which the HTTP layer renames
    to ``NOT_PROCESSED`` (OQ-41)."""


class PortfolioService(Protocol):
    """Published data only, never recalculated on read (spec §11.4); each date's chain statuses
    come from ``processing.date_status`` (OQ-23), read in the same transaction as the published
    rows (``DateStatusReader`` is built on the same session), so figures and statuses always
    come from one snapshot."""

    async def get_summary(self, on: date) -> PortfolioSummaryView: ...

    async def get_position_table(self, on: date) -> PositionTableView: ...

    async def get_pnl_series(self, start_date: date, end_date: date) -> tuple[PnLPointView, ...]:
        """Every date of [start_date, end_date], in date order (OQ-16, OQ-27, OQ-41, OQ-49), each
        with its positions status and the running sum of ``daily_pnl`` from ``start_date``, a
        missing or incomplete date counting as 0."""
        ...
