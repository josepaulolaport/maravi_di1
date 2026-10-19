"""Pricing's public contract: PU ↔ rate by DC/365 for an instrument (interfaces.md "Pricing").

Frozen in W0.3c. Lane B implements `PricingService` over the domain calculator; Ledger and Prices
call it when an entry is typed as a PU or as a rate. Changes go through the integrator.

`QuoteValidator` is the one validation of a quote typed as a PU or a rate (code-review finding
H3): pure and synchronous, so Ledger and Prices run it with their own field names
(`QuoteFields`) and report every problem of a request at once; the calculator runs the same rule.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from di1.modules.pricing.domain.di1 import QuoteFields, QuoteValidator
from di1.modules.pricing.domain.model import Price
from di1.shared.input_kind import InputKind
from di1.shared.quotes import Quote

__all__ = ["InputKind", "Price", "PricingService", "Quote", "QuoteFields", "QuoteValidator"]


class PricingService(Protocol):
    """The calculator behind an instrument (spec §4.1, OQ-1, OQ-3)."""

    async def calculate(self, instrument_id: UUID, reference_date: date, quote: Quote) -> Price:
        """The complete PU and rate pair for ``quote`` on ``reference_date``.

        The service reads the instrument through ``asset.public.AssetReader``, so no caller
        passes a stale face value. It prices only instruments of product code ``DI1``
        (case-insensitive); another product, or an instrument without a maturity or a face value,
        is ``VALIDATION_ERROR`` on ``asset_id`` (OQ-34). It raises ``DomainError``: ``NOT_FOUND``
        for an unknown instrument, ``CONTRACT_MATURED`` after the maturity date,
        ``VALIDATION_ERROR`` for a quote out of bounds or with too many decimals. On the maturity
        date the PU is typed and the rate is 0.

        Error fields use Pricing's names, ``asset_id``, ``reference_date``, ``pu`` and ``rate``;
        each caller remaps them to its request fields (Ledger: ``date``, ``execution_pu``,
        ``execution_rate``) (OQ-34).
        """
        ...
