"""`AssetReader` (asset/public.py): the instruments as Pricing, Ledger, Prices, Portfolio and
Processing read them (interfaces.md "Asset")."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from uuid import UUID

from di1.modules.asset.application.interfaces.repository import AssetRepository
from di1.modules.asset.public import InstrumentDescriptor
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail


class InstrumentReader:
    """Implements `di1.modules.asset.public.AssetReader`."""

    def __init__(self, repository: AssetRepository) -> None:
        self._repository = repository

    async def get_instrument(self, instrument_id: UUID) -> InstrumentDescriptor:
        found = await self._repository.get_descriptors((instrument_id,))
        descriptor = found.get(instrument_id)
        if descriptor is None:
            raise DomainError(ErrorDetail(ErrorCode.NOT_FOUND, "Contrato não encontrado."))
        return descriptor

    async def get_instruments(
        self, instrument_ids: Collection[UUID]
    ) -> Mapping[UUID, InstrumentDescriptor]:
        if not instrument_ids:
            return {}
        return await self._repository.get_descriptors(instrument_ids)
