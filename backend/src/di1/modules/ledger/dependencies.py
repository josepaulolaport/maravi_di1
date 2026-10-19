"""Ledger's module-local factories (interfaces.md "DI composition"). The composition passes the
collaborators of other modules (Asset's reader, Pricing) and the clock;
workers call these plain factories too."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import AssetReader
from di1.modules.ledger.application.interfaces.repository import LedgerRepository
from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.modules.ledger.infrastructure.persistence.repositories import SqlLedgerRepository
from di1.modules.ledger.public import LedgerReader
from di1.modules.pricing.public import PricingService
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock


def ledger_repository(uow: UnitOfWork) -> LedgerRepository:
    return SqlLedgerRepository(uow.session)


def ledger_reader(session: AsyncSession) -> LedgerReader:
    """`LedgerReader` over ``session``: reads join the caller's transaction (Processing reads a
    date's facts in that date's transaction)."""
    return SqlLedgerRepository(session)


def create_ledger_service(
    *,
    clock: Clock,
    assets: AssetReader,
    pricing: PricingService,
) -> LedgerService:
    return LedgerService(
        clock=clock,
        assets=assets,
        pricing=pricing,
        repository_for=ledger_repository,
    )
