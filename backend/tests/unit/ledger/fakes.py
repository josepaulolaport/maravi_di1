"""Test doubles for Ledger's persistence, and Asset's reader over the contracts Ledger's tests
trade. Pricing is the real, pure service through `tests.support.fakes.PricingSpy`, which only
records what Ledger passes to it.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any
from uuid import UUID, uuid4

from di1.modules.ledger.domain.entries import EntryType, LedgerEntry, NewCashMovement, NewTrade
from di1.modules.ledger.domain.listing import PageRequest
from di1.shared.clock import SAO_PAULO
from tests.support.builders import DI1F27, DI1F28, DI1F29, DI1V26
from tests.support.fakes import FakeAssetReader


def contracts() -> FakeAssetReader:
    """Asset's reader over the catalogue contracts Ledger's tests trade."""
    return FakeAssetReader(DI1F27, DI1F28, DI1F29, DI1V26)


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
