"""Test doubles for Ledger's collaborators: Asset, Pricing, the Unit of Work and persistence.

Pricing is the real, pure service (`build_pricing_service`) over `FakeAssets`; `PricingSpy`
only records what Ledger passes to it.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import Instrument
from di1.modules.ledger.domain.entries import EntryType, LedgerEntry, NewCashMovement, NewTrade
from di1.modules.ledger.domain.listing import PageRequest
from di1.modules.pricing.dependencies import build_pricing_service
from di1.modules.pricing.public import Price, Quote
from di1.shared.clock import SAO_PAULO
from tests.fakes.asset import CREATED_AT

PRODUCT_ID = UUID("6f1c2a10-0000-4000-8000-000000000001")


def di1_future(code: str, instrument_id: UUID, maturity: date) -> Instrument:
    return Instrument(
        id=instrument_id,
        code=code,
        product_id=PRODUCT_ID,
        product_code="DI1",
        instrument_type="FUTURE",
        asset_class="INTEREST_RATE_FUTURE",
        maturity_date=maturity,
        face_value=Decimal("100000"),
        multiplier=Decimal("1"),
        settlement_method="CASH",
        created_at=CREATED_AT,
    )


# The contracts of the frontend's test fixtures (frontend/src/test/msw/fixtures.ts; before #114,
# frontend/src/api/mocks/fixtures.ts at 57b4df0).
DI1F27 = di1_future("DI1F27", UUID("6f1c2a10-0000-4000-8000-0000000000f7"), date(2027, 1, 4))
DI1F28 = di1_future("DI1F28", UUID("6f1c2a10-0000-4000-8000-0000000000f8"), date(2028, 1, 3))
DI1F29 = di1_future("DI1F29", UUID("6f1c2a10-0000-4000-8000-0000000000f9"), date(2029, 1, 2))
# Not in the fixtures: a contract that matured before today (OQ-1).
DI1V26 = di1_future("DI1V26", UUID("6f1c2a10-0000-4000-8000-0000000000a1"), date(2026, 10, 1))


@dataclass
class FakeAssets:
    """`AssetReader` over a fixed catalogue."""

    instruments: dict[UUID, Instrument] = field(
        default_factory=lambda: {i.id: i for i in (DI1F27, DI1F28, DI1F29, DI1V26)}
    )

    async def get_instruments(self, instrument_ids: Collection[UUID]) -> Mapping[UUID, Instrument]:
        return {i: self.instruments[i] for i in instrument_ids if i in self.instruments}


@dataclass
class PricingSpy:
    """The real `PricingService` over ``assets``, recording each call Ledger makes to it."""

    assets: FakeAssets
    calls: list[tuple[UUID, date, Quote]] = field(default_factory=list)

    async def calculate(self, instrument_id: UUID, reference_date: date, quote: Quote) -> Price:
        self.calls.append((instrument_id, reference_date, quote))
        return await build_pricing_service(self.assets).calculate(
            instrument_id, reference_date, quote
        )


class FakeUnitOfWork:
    """Counts commits; has no session."""

    def __init__(self) -> None:
        self.commits = 0

    @property
    def session(self) -> AsyncSession:
        raise AssertionError("the in-memory repository needs no session")

    async def commit(self) -> None:
        self.commits += 1


@dataclass
class InMemoryLedgerRepository:
    """`LedgerRepository` over a list, for service tests; SQL behaviour is tested against
    PostgreSQL in tests/integration/ledger."""

    rows: list[LedgerEntry] = field(default_factory=list)
    next_seq: int = 1
    now: datetime = datetime(2026, 10, 18, 12, 0, tzinfo=SAO_PAULO)
    page_calls: list[tuple[PageRequest, set[UUID]]] = field(default_factory=list)

    async def add_trade(self, trade: NewTrade) -> LedgerEntry:
        return self._add(
            type=EntryType.TRADE,
            entry_date=trade.entry_date,
            entry_time=trade.entry_time,
            asset_id=trade.asset_id,
            signed_quantity=trade.signed_quantity,
            execution_pu=trade.execution_pu,
            execution_rate=trade.execution_rate,
            input_kind=trade.input_kind,
            cash_amount=None,
        )

    async def add_cash_movement(self, movement: NewCashMovement) -> LedgerEntry:
        return self._add(
            type=EntryType.CASH,
            entry_date=movement.entry_date,
            entry_time=movement.entry_time,
            asset_id=None,
            signed_quantity=None,
            execution_pu=None,
            execution_rate=None,
            input_kind=None,
            cash_amount=movement.amount,
            description=movement.description,
        )

    async def lock_existing(self, ids: Collection[UUID]) -> set[UUID]:
        return {row.id for row in self.rows if row.id in set(ids)}

    async def delete(self, ids: Collection[UUID]) -> None:
        self.rows = [row for row in self.rows if row.id not in set(ids)]

    async def trade_asset_ids(self, start_date: date, end_date: date) -> set[UUID]:
        return {
            row.asset_id for row in self._active(start_date, end_date) if row.asset_id is not None
        }

    async def page(
        self, request: PageRequest, *, matching_asset_ids: Collection[UUID]
    ) -> Sequence[LedgerEntry]:
        """The first ``limit + 1`` stored rows, as stored: ordering, search and keyset paging are
        SQL, tested in tests/integration/ledger. Records what the service asked for."""
        self.page_calls.append((request, set(matching_asset_ids)))
        return self.rows[: request.limit + 1]

    def _active(self, start_date: date, end_date: date) -> list[LedgerEntry]:
        return [row for row in self.rows if start_date <= row.entry_date <= end_date]

    def _add(self, **fields: Any) -> LedgerEntry:
        entry = LedgerEntry(id=uuid4(), seq=self.next_seq, created_at=self.now, **fields)
        self.next_seq += 1
        self.rows.append(entry)
        return entry


def at(hour: int, minute: int = 0) -> time:
    return time(hour, minute)
