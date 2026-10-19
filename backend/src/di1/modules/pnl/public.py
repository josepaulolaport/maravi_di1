"""PnL's public contract: the pure per-asset and portfolio calculators and their results
(interfaces.md "PnL").

Frozen in W0.3c. The calculators are synchronous and pure; Processing (and Portfolio's writer)
use them through this module. ``PnLTrade`` is PnL's own view of a trade: the application maps
``ledger.public.TradeRecord`` onto it. Changes go through the integrator.
"""

from __future__ import annotations

from di1.modules.pnl.domain.asset_pnl import AssetPnLCalculator
from di1.modules.pnl.domain.portfolio_pnl import PortfolioPnLCalculator
from di1.modules.pnl.domain.results import (
    AssetPnLResult,
    CalculationCompleteness,
    MissingReferencePrice,
    PortfolioPnLResult,
)
from di1.modules.pnl.domain.trade import PnLTrade

__all__ = [
    "AssetPnLCalculator",
    "AssetPnLResult",
    "CalculationCompleteness",
    "MissingReferencePrice",
    "PnLTrade",
    "PortfolioPnLCalculator",
    "PortfolioPnLResult",
]
