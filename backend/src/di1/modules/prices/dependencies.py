"""Prices' module-local factories (interfaces.md "DI composition"). The composition root calls them
from its providers (HTTP) and plain factories (workers), passing the collaborators of other
modules built on the same Unit of Work or session."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import AssetReader
from di1.modules.prices.application.services.price_service import DefaultPriceReader, PriceService
from di1.modules.prices.infrastructure.persistence.repositories import (
    SqlReferencePriceRepository,
)
from di1.modules.prices.public import PriceReader
from di1.modules.pricing.public import PricingService
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock


def build_price_service(
    uow: UnitOfWork, *, assets: AssetReader, pricing: PricingService, clock: Clock
) -> PriceService:
    """The service on the request's Unit of Work: its writes commit that same transaction.
    ``assets`` and ``pricing`` should read through ``uow.session`` too."""
    return PriceService(
        SqlReferencePriceRepository(uow.session), uow, assets=assets, pricing=pricing, clock=clock
    )


def build_price_reader(session: AsyncSession) -> PriceReader:
    """`PriceReader` on the caller's session, so a read sees the caller's transaction: Processing
    and Portfolio take each date's reference PU from it (OQ-30); Asset HTTP fills
    ``last_reference`` from ``latest`` (OQ-48)."""
    return DefaultPriceReader(SqlReferencePriceRepository(session))
