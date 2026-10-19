"""What Ledger needs from Pricing: the complete execution PU/rate pair of a typed quote.

``pricing/public.py`` is not frozen yet (lane X). Ledger codes against this port; the composition
adapts ``PricingService.calculate(instrument_id, reference_date, quote) -> Price`` to it once
that lands (interfaces.md "Pricing"). Pricing reads the contract's maturity and face value from
Asset itself; on the maturity date it returns the typed PU with a rate of 0 (OQ-1). It raises
`di1.shared.errors.DomainError` for a pair it cannot produce.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from di1.shared.input_kind import InputKind


@dataclass(frozen=True, slots=True)
class ExecutionPrice:
    """The calculated pair: the typed value as typed, the other as stored (OQ-3)."""

    pu: Decimal
    rate: Decimal


class ExecutionPricer(Protocol):
    async def price(
        self, instrument_id: UUID, trade_date: date, input_kind: InputKind, typed_value: Decimal
    ) -> ExecutionPrice: ...
