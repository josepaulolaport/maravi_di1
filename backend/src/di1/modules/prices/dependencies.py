"""Prices' module-local factories (interfaces.md "DI composition"). The composition root calls them
from its providers (HTTP) and plain factories (workers), passing the collaborators of other
modules built on the same Unit of Work or session."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import AssetReader
from di1.modules.prices.application.services.price_service import (
    PreferredPriceReader,
    PriceService,
)
from di1.modules.prices.infrastructure.persistence.repositories import (
    SqlReferencePriceRepository,
)
from di1.modules.prices.public import LatestPriceReader, PriceReader
from di1.modules.pricing.public import PricingService
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock


def price_service(
    uow: UnitOfWork, *, assets: AssetReader, pricing: PricingService, clock: Clock
) -> PriceService:
    """The service for the request's Unit of Work: each write receives ``uow`` and commits that
    same transaction. ``assets`` and ``pricing`` should read through ``uow.session`` too."""
    del uow  # the service takes each write's Unit of Work as an argument
    return PriceService(
        assets=assets,
        pricing=pricing,
        repositories=SqlReferencePriceRepository.of,
        clock=clock,
    )


def price_reader(session: AsyncSession) -> PriceReader:
    """`prices.public.PriceReader` on the caller's session, so a read sees the caller's
    transaction: Processing's run of a date and Portfolio's reads take each date's reference PU,
    rate and source from it (OQ-30)."""
    return PreferredPriceReader(SqlReferencePriceRepository(session))


def latest_price_reader(session: AsyncSession) -> LatestPriceReader:
    """`prices.public.LatestPriceReader` on the caller's session: each asset's latest preferred
    price, for Asset's ``Instrument.last_reference`` (OQ-48)."""
    return PreferredPriceReader(SqlReferencePriceRepository(session))
