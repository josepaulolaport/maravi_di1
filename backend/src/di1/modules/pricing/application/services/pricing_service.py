"""`PricingService` over the DI1 calculator (pricing/public.py; interfaces "Pricing").

The instrument's maturity and face value are read through Asset's `AssetReader`, so no caller
passes a stale face value. Only DI1 futures have a calculator (spec §4.1): the instrument's product
code must be ``DI1``, compared case-insensitively like Asset's codes (user decision, 2026-10-19);
any other instrument is refused. The multiplier is not used (OQ-2).

Error fields use Pricing's names (``asset_id``, ``reference_date``, ``pu``, ``rate``); a caller
whose request names them differently (Ledger's ``entry_date``, ``execution_pu``, ``execution_rate``)
remaps them.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from di1.modules.asset.public import AssetReader, InstrumentDescriptor
from di1.modules.pricing.domain.futures.di1 import DI1Calculator
from di1.modules.pricing.domain.futures.model import FuturesTerms, Price, Quote
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail

_DI1 = "DI1"


class InstrumentPricingService:
    """Implements `PricingService`. Reads only; the caller's transaction is the reader's."""

    def __init__(self, asset_reader: AssetReader, calculator: DI1Calculator) -> None:
        self._asset_reader = asset_reader
        self._calculator = calculator

    async def calculate(self, instrument_id: UUID, reference_date: date, quote: Quote) -> Price:
        instrument = await self._asset_reader.get_instrument(instrument_id)
        return self._calculator.calculate(_di1_terms(instrument), reference_date, quote)


def _di1_terms(instrument: InstrumentDescriptor) -> FuturesTerms:
    if (
        instrument.product_code.casefold() != _DI1.casefold()
        or instrument.maturity_date is None
        or instrument.face_value is None
    ):
        raise DomainError(
            ErrorDetail(
                ErrorCode.VALIDATION_ERROR,
                "O contrato não pode ser precificado: só contratos futuros DI1 têm cálculo de PU"
                " e taxa.",
                "asset_id",
            )
        )
    return FuturesTerms(maturity_date=instrument.maturity_date, face_value=instrument.face_value)
