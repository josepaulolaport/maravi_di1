"""`PricingService` over the DI1 calculator (interfaces "Pricing"; OQ-2, OQ-34)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from di1.modules.asset.public import AssetReader, Instrument
from di1.modules.pricing.domain.di1 import DI1Calculator
from di1.modules.pricing.domain.model import FuturesTerms, Price, Quote
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail

_DI1 = "DI1"


class PricingService:
    """Public `PricingService`. Reads only; the caller's transaction is the reader's."""

    def __init__(self, asset_reader: AssetReader, calculator: DI1Calculator) -> None:
        self._asset_reader = asset_reader
        self._calculator = calculator

    async def calculate(self, instrument_id: UUID, reference_date: date, quote: Quote) -> Price:
        instrument = (await self._asset_reader.get_instruments([instrument_id])).get(instrument_id)
        if instrument is None:
            raise DomainError(ErrorDetail(ErrorCode.NOT_FOUND, "Contrato não encontrado."))
        return self._calculator.calculate(_di1_terms(instrument), reference_date, quote)


def _di1_terms(instrument: Instrument) -> FuturesTerms:
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
