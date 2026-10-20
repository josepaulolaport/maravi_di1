"""Asset's module-local factories (interfaces.md "DI composition"). The composition root calls them
from its providers (HTTP) and plain factories (workers)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.application.services.asset_service import AssetService
from di1.modules.asset.infrastructure.persistence.repositories import SqlAssetRepository
from di1.modules.asset.public import AssetReader
from di1.platform.database.unit_of_work import UnitOfWork


def build_asset_service(uow: UnitOfWork) -> AssetService:
    """The service on the request's Unit of Work: its writes commit that same transaction."""
    return AssetService(SqlAssetRepository(uow.session), uow)


def build_asset_reader(session: AsyncSession) -> AssetReader:
    """`AssetReader` on the caller's session, so a read sees the caller's transaction. A plain
    read, so it is the repository itself."""
    return SqlAssetRepository(session)
