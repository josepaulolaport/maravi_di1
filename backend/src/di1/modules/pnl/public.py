"""PnL's public contract: the pure per-asset attribution and portfolio aggregation, and their
results (interfaces.md "PnL").

Both functions are synchronous and pure; Processing uses them through this module. ``PnLTrade`` is
PnL's own view of a trade: the application maps ``ledger.public.LedgerEntry`` onto it. Changes go
through the integrator.
"""

from __future__ import annotations

from di1.modules.pnl.domain.asset_pnl import calculate_asset_pnl
from di1.modules.pnl.domain.portfolio_pnl import aggregate_pnl
from di1.modules.pnl.domain.results import (
    AssetPnLResult,
    CalculationCompleteness,
    MissingReferencePrice,
    PnLTrade,
    PortfolioPnLResult,
)

__all__ = [
    "AssetPnLResult",
    "CalculationCompleteness",
    "MissingReferencePrice",
    "PnLTrade",
    "PortfolioPnLResult",
    "aggregate_pnl",
    "calculate_asset_pnl",
]
