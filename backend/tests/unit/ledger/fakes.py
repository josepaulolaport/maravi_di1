"""Test doubles for Ledger's collaborators: Asset, Pricing, the Unit of Work and persistence.

`FormulaPricing` implements ``pricing.public.PricingService`` with the spec's DC/365 formula
until lane B's service is wired, so the golden values of the frontend fixtures hold. Like
production code, these doubles reach other modules only through their ``public.py``.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from di1.modules.ledger.domain.entries import EntryType, LedgerEntry, NewCashMovement, NewTrade
from di1.modules.ledger.domain.listing import ListOrder, PageRequest
from di1.modules.pricing.public import Price, Quote
from di1.shared.calendar import DAYS_PER_YEAR, calendar_days
from di1.shared.clock import SAO_PAULO
from di1.shared.decimals import financial_context, quantize_pu, quantize_rate
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind
from tests.support.builders import DI1F27, DI1F28, DI1F29, DI1V26
from tests.support.fakes import FakeAssetReader


def contracts() -> FakeAssetReader:
    """Asset's reader over the catalogue contracts Ledger's tests trade."""
    return FakeAssetReader(DI1F27, DI1F28, DI1F29, DI1V26)


@dataclass
class FormulaPricing:
    """`PricingService` by the spec's DC/365 formula (spec §4.1, OQ-1, OQ-3), reading the contract
    from ``assets`` as the real service does. It refuses like lane B's service: a `DomainError`
    naming Pricing's own parameters (``reference_date``, ``pu``, ``rate``), which Ledger maps to
    its request fields. Only the cases Ledger can reach after its own validation are modelled."""

    assets: FakeAssetReader
    calls: list[tuple[UUID, date, Quote]] = field(default_factory=list)

    async def calculate(self, instrument_id: UUID, reference_date: date, quote: Quote) -> Price:
        self.calls.append((instrument_id, reference_date, quote))
        contract = (await self.assets.get_instruments([instrument_id])).get(instrument_id)
        if contract is None:
            raise DomainError(ErrorDetail(ErrorCode.NOT_FOUND, "Contrato não encontrado."))
        assert contract.maturity_date is not None and contract.face_value is not None
        days = calendar_days(reference_date, contract.maturity_date)
        if days < 0:
            raise DomainError(
                ErrorDetail(
                    ErrorCode.CONTRACT_MATURED,
                    "O contrato já venceu nesta data.",
                    "reference_date",
                )
            )
        face_value = contract.face_value
        if quote.kind is InputKind.PU:
            if days == 0:  # on the maturity date the PU is typed and the rate is 0 (OQ-1)
                return Price(pu=quote.value, rate=quantize_rate(Decimal(0)), input_kind=quote.kind)
            with financial_context():
                rate = (face_value / quote.value) ** (DAYS_PER_YEAR / Decimal(days)) - 1
            return Price(pu=quote.value, rate=quantize_rate(rate), input_kind=quote.kind)
        if days == 0:
            raise _refused("Na data de vencimento informe o PU.", "rate")
        with financial_context():
            pu = face_value / (1 + quote.value) ** (Decimal(days) / DAYS_PER_YEAR)
        stored = quantize_pu(pu)
        if stored <= 0:
            raise _refused("A taxa resulta em um PU que arredonda para zero.", "rate")
        return Price(pu=stored, rate=quote.value, input_kind=quote.kind)


def _refused(message: str, field: str) -> DomainError:
    return DomainError(ErrorDetail(ErrorCode.VALIDATION_ERROR, message, field))


@dataclass
class InMemoryLedgerRepository:
    """`LedgerRepository` over a list, for service tests; SQL behaviour is tested against
    PostgreSQL in tests/integration/ledger."""

    rows: list[LedgerEntry] = field(default_factory=list)
    next_seq: int = 1
    now: datetime = datetime(2026, 10, 18, 12, 0, tzinfo=SAO_PAULO)

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
        descending = request.order is ListOrder.DESC
        rows = sorted(
            self._active(request.start_date, request.end_date),
            key=lambda row: row.order_key,
            reverse=descending,
        )
        if request.search is not None:
            search = request.search

            def matches(row: LedgerEntry) -> bool:
                if row.type is EntryType.TRADE:
                    return row.asset_id in set(matching_asset_ids)
                assert row.cash_amount is not None
                if search.matches_description(row.description):
                    return True
                if row.cash_amount > 0:
                    return search.includes_deposits
                return search.includes_withdrawals

            rows = [row for row in rows if matches(row)]
        if request.after is not None:
            after = (request.after.entry_date, request.after.entry_time, request.after.seq)
            rows = [r for r in rows if (r.order_key < after if descending else r.order_key > after)]
        return rows[: request.limit + 1]

    def _active(self, start_date: date, end_date: date) -> list[LedgerEntry]:
        return [row for row in self.rows if start_date <= row.entry_date <= end_date]

    def _add(self, **fields: Any) -> LedgerEntry:
        entry = LedgerEntry(id=uuid4(), seq=self.next_seq, created_at=self.now, **fields)
        self.next_seq += 1
        self.rows.append(entry)
        return entry


def at(hour: int, minute: int = 0) -> time:
    return time(hour, minute)
