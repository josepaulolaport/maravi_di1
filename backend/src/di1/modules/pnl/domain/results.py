"""P&L result values and completeness states (spec §8.3; schema ``pnl_status``).

A figure that depends on a missing reference price is ``None``, never zero. Re-exported by
``pnl.public``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class CalculationCompleteness(StrEnum):
    """Mirrors the schema's ``pnl_status`` values."""

    COMPLETE = "COMPLETE"
    MISSING = "MISSING"


class MissingReferencePrice(StrEnum):
    """Which exact-date reference PU a calculation needed and did not get."""

    PREVIOUS = "PREVIOUS"  # D-1, needed only when Q[D-1] != 0 (OQ-4)
    CURRENT = "CURRENT"  # D, needed when Q[D-1] != 0 or the asset trades on D


@dataclass(frozen=True, slots=True)
class PnLTrade:
    """Buys positive, sells negative (schema ``INTEGER``), at the execution PU. The application
    layer maps Ledger's trade record to it."""

    signed_quantity: int
    execution_pu: Decimal


@dataclass(frozen=True, slots=True)
class AssetPnLResult:
    """One asset on one day. ``daily_pnl`` is set only when both components are."""

    position_pnl: Decimal | None
    trades_pnl: Decimal | None
    daily_pnl: Decimal | None
    status: CalculationCompleteness
    missing_prices: frozenset[MissingReferencePrice]


@dataclass(frozen=True, slots=True)
class PortfolioPnLResult:
    """The portfolio on one day, summed over every expected asset (OQ-10).

    ``status`` is the completeness of the day's P&L. A complete day after a gap still has a valid
    ``daily_pnl`` but no ``cumulative_pnl``: the cumulative chain stays broken (§8.3).
    """

    position_pnl: Decimal | None
    trades_pnl: Decimal | None
    daily_pnl: Decimal | None
    cumulative_pnl: Decimal | None
    status: CalculationCompleteness
