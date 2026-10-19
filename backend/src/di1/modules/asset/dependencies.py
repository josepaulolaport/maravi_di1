"""Asset's module-local factories (interfaces.md "DI composition"). The composition root calls them
from its providers (HTTP) and plain factories (workers)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.application.services.asset_reader import AssetReader
from di1.modules.asset.application.services.asset_service import AssetService
from di1.modules.asset.infrastructure.persistence.repositories import SqlAssetRepository
from di1.platform.database.unit_of_work import UnitOfWork


def asset_service(uow: UnitOfWork) -> AssetService:
    """The service on the request's Unit of Work: its writes commit that same transaction."""
    return AssetService(SqlAssetRepository(uow.session))


def asset_reader(session: AsyncSession) -> AssetReader:
    """`AssetReader` on the caller's session, so a read sees the caller's transaction."""
    return AssetReader(SqlAssetRepository(session))
