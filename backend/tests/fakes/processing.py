"""An in-memory `FinancialResultInvalidator` for Ledger's and Prices' tests (plan §3, W0.3b).

It records each call and the Unit of Work it received, so a test can assert that a write
invalidated the right date in the same transaction as the fact. It never commits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from di1.platform.database.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class TradesChanged:
    effective_date: date
    uow: UnitOfWork


@dataclass(frozen=True, slots=True)
class CashMovementsChanged:
    effective_date: date
    uow: UnitOfWork


@dataclass(frozen=True, slots=True)
class PricesChanged:
    asset_id: UUID
    reference_date: date
    uow: UnitOfWork


@dataclass
class RecordingInvalidator:
    """Satisfies `di1.modules.processing.public.FinancialResultInvalidator`."""

    calls: list[TradesChanged | CashMovementsChanged | PricesChanged] = field(default_factory=list)

    async def trades_changed(self, effective_date: date, *, uow: UnitOfWork) -> None:
        self.calls.append(TradesChanged(effective_date, uow))

    async def cash_movements_changed(self, effective_date: date, *, uow: UnitOfWork) -> None:
        self.calls.append(CashMovementsChanged(effective_date, uow))

    async def prices_changed(
        self, asset_id: UUID, reference_date: date, *, uow: UnitOfWork
    ) -> None:
        self.calls.append(PricesChanged(asset_id, reference_date, uow))
