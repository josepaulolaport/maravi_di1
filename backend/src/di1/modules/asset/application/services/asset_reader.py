"""`AssetReader` (asset/public.py): the instruments as Pricing, Ledger, Prices, Portfolio and
Processing read them (interfaces.md "Asset")."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from uuid import UUID

from di1.modules.asset.application.services.repository import AssetRepository
from di1.modules.asset.domain.model import Instrument


class AssetReader:
    """Public `AssetReader` on the caller's session."""

    def __init__(self, repository: AssetRepository) -> None:
        self._repository = repository

    async def get_instruments(self, instrument_ids: Collection[UUID]) -> Mapping[UUID, Instrument]:
        if not instrument_ids:
            return {}
        return await self._repository.get_instruments(instrument_ids)
