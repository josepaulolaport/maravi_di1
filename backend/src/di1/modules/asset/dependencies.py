"""Asset's module-local factories (interfaces.md "DI composition"). The composition root calls them
from its providers (HTTP) and plain factories (workers)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.application.services.asset_service import AssetService
from di1.modules.asset.application.services.instrument_reader import InstrumentReader
from di1.modules.asset.infrastructure.persistence.repositories import SqlAlchemyAssetRepository
from di1.modules.asset.public import AssetReader
from di1.modules.prices.public import LatestPriceReader
from di1.platform.database.unit_of_work import UnitOfWork


def asset_service(uow: UnitOfWork, latest_prices: LatestPriceReader | None = None) -> AssetService:
    """The service on the request's Unit of Work: its writes commit that same transaction.
    ``latest_prices`` (Prices, on the same session) fills ``Instrument.last_reference`` (OQ-48)."""
    return AssetService(SqlAlchemyAssetRepository(uow.session), latest_prices)


def asset_reader(session: AsyncSession) -> AssetReader:
    """`AssetReader` on the caller's session, so a read sees the caller's transaction."""
    return InstrumentReader(SqlAlchemyAssetRepository(session))
