"""Pricing's public contract: PU ↔ rate by DC/365 for an instrument (interfaces.md "Pricing").

Frozen in W0.3c. Lane B implements `PricingService` over the domain calculator; Ledger and Prices
call it when an entry is typed as a PU or as a rate. Changes go through the integrator.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from di1.modules.pricing.domain.futures.model import Price, Quote
from di1.shared.input_kind import InputKind

__all__ = ["InputKind", "Price", "PricingService", "Quote"]


class PricingService(Protocol):
    """The calculator behind an instrument (spec §4.1, OQ-1, OQ-3)."""

    async def calculate(self, instrument_id: UUID, reference_date: date, quote: Quote) -> Price:
        """The complete PU and rate pair for ``quote`` on ``reference_date``.

        The service reads the instrument through ``asset.public.AssetReader``, so no caller
        passes a stale face value. It raises ``DomainError``: ``NOT_FOUND`` for an unknown
        instrument, ``CONTRACT_MATURED`` after the maturity date, ``VALIDATION_ERROR`` for a quote
        out of bounds or with too many decimals. On the maturity date the PU is typed and the
        rate is 0.
        """
        ...
