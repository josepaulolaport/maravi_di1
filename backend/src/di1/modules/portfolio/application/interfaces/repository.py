"""What Portfolio's services need from persistence: the published tables, one date at a time.

The repository maps rows to these records and holds no business rule (backend CLAUDE.md).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from di1.modules.pnl.public import CalculationCompleteness
from di1.modules.portfolio.domain.valuation import ValuationStatus


@dataclass(frozen=True, slots=True)
class PublishedPosition:
    """One expected asset on one date: a ``positions`` row with its ``position_metrics`` row."""

    asset_id: UUID
    quantity: int
    average_entry_pu: Decimal | None
    average_entry_rate: Decimal | None
    financial_total: Decimal | None
    position_pnl: Decimal | None
    trades_pnl: Decimal | None
    daily_pnl: Decimal | None
    valuation_status: ValuationStatus
    pnl_status: CalculationCompleteness


@dataclass(frozen=True, slots=True)
class PublishedPortfolioDay:
    """A ``portfolio_metrics`` row. ``aum`` is read back as stored; on a write it is ignored and
    recomputed from the date's published cash (OQ-21, OQ-28)."""

    date: date
    positions_market_value: Decimal | None
    aum: Decimal | None
    position_pnl: Decimal | None
    trades_pnl: Decimal | None
    daily_pnl: Decimal | None
    cumulative_pnl: Decimal | None
    valuation_status: CalculationCompleteness
    pnl_status: CalculationCompleteness


@dataclass(frozen=True, slots=True)
class PublishedCash:
    """A ``cash_balances`` row."""

    date: date
    cash_balance: Decimal
    trades_cash_flow: Decimal
    deposits: Decimal
    withdrawals: Decimal


class PortfolioRepository(Protocol):
    async def start_read_snapshot(self) -> None:
        """Make the rest of the transaction one read-only snapshot (REPEATABLE READ), so every
        read of a request sees the same commits. It must be the transaction's first statement."""
        ...

    async def replace_positions_day(
        self, day: PublishedPortfolioDay, positions: Sequence[PublishedPosition]
    ) -> None:
        """Replace ``day.date``'s ``positions``, ``position_metrics`` and ``portfolio_metrics``
        rows (rows of assets not in ``positions`` are deleted, OQ-10) and set its AUM from the
        date's published cash, ``NULL`` when either side is missing."""
        ...

    async def upsert_cash_day(self, cash: PublishedCash) -> None:
        """Insert or replace ``cash.date``'s ``cash_balances`` row and recompute that date's AUM
        when its ``portfolio_metrics`` row exists."""
        ...

    async def get_cash(self, on: date) -> PublishedCash | None: ...

    async def get_portfolio_day(self, on: date) -> PublishedPortfolioDay | None: ...

    async def get_portfolio_days(
        self, start_date: date, end_date: date
    ) -> Sequence[PublishedPortfolioDay]:
        """The ``portfolio_metrics`` rows of [start_date, end_date], in date order."""
        ...

    async def get_positions(self, on: date) -> Sequence[PublishedPosition]:
        """``on``'s position rows, in asset id order."""
        ...
