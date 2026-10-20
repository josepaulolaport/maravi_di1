"""`PricingService` over the DI1 calculator (interfaces "Pricing"; OQ-2, OQ-34)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from di1.modules.asset.public import AssetReader, Instrument
from di1.modules.pricing.domain.di1 import price
from di1.modules.pricing.domain.model import DI1Terms, Price, Quote
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail

_DI1 = "DI1"


class DefaultPricingService:
    """Implements `pricing.public.PricingService`. Reads only; the caller's transaction is the
    reader's."""

    def __init__(self, assets: AssetReader) -> None:
        self._assets = assets

    async def calculate(self, instrument_id: UUID, reference_date: date, quote: Quote) -> Price:
        instrument = (await self._assets.get_instruments([instrument_id])).get(instrument_id)
        if instrument is None:
            raise DomainError(ErrorDetail(ErrorCode.NOT_FOUND, "Contrato não encontrado."))
        return price(_di1_terms(instrument), reference_date, quote)


def _di1_terms(instrument: Instrument) -> DI1Terms:
    if (
        instrument.product_code.casefold() != _DI1.casefold()
        or instrument.maturity_date is None
        or instrument.face_value is None
    ):
        raise DomainError(
            ErrorDetail.validation(
                "O contrato não pode ser precificado: só contratos futuros DI1 têm cálculo de PU"
                " e taxa.",
                "asset_id",
            )
        )
    return DI1Terms(maturity_date=instrument.maturity_date, face_value=instrument.face_value)
