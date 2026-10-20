"""The SQL of ``ledger.entries``. Reads follow the order ``(entry_date, entry_time, seq)``. A
deletion removes the rows for good (user decision 2026-10-19)."""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import date

from sqlalchemy import (
    ColumnElement,
    Delete,
    Select,
    and_,
    delete,
    exists,
    false,
    insert,
    literal,
    or_,
    select,
    tuple_,
)
from sqlalchemy.sql.dml import ReturningInsert

from di1.modules.ledger.domain.entries import EntryType, NewCashMovement, NewTrade
from di1.modules.ledger.domain.listing import EntrySearch, ListOrder, PageRequest
from di1.modules.ledger.infrastructure.persistence.models import LedgerEntryRow

_ORDER_KEY = (LedgerEntryRow.entry_date, LedgerEntryRow.entry_time, LedgerEntryRow.seq)


def insert_trade(trade: NewTrade) -> ReturningInsert[LedgerEntryRow]:
    """Insert one trade; the database assigns ``id``, ``seq`` and ``created_at``."""
    return (
        insert(LedgerEntryRow)
        .values(
            type=EntryType.TRADE.value,
            entry_date=trade.entry_date,
            entry_time=trade.entry_time,
            asset_id=trade.asset_id,
            signed_quantity=trade.signed_quantity,
            execution_pu=trade.execution_pu,
            execution_rate=trade.execution_rate,
            input_kind=trade.input_kind.value,
        )
        .returning(LedgerEntryRow)
    )


def insert_cash_movement(movement: NewCashMovement) -> ReturningInsert[LedgerEntryRow]:
    """Insert one aporte or retirada; the database assigns ``id``, ``seq`` and ``created_at``."""
    return (
        insert(LedgerEntryRow)
        .values(
            type=EntryType.CASH.value,
            entry_date=movement.entry_date,
            entry_time=movement.entry_time,
            cash_amount=movement.amount,
        )
        .returning(LedgerEntryRow)
    )


def ids_for_update(ids: Collection[uuid.UUID]) -> Select[uuid.UUID]:
    """The ids among ``ids`` that name an entry, those rows locked in id order so that two
    concurrent deletions lock in the same order. A row deleted by a concurrent transaction is
    absent once that transaction commits."""
    return (
        select(LedgerEntryRow.id)
        .where(LedgerEntryRow.id.in_(list(ids)))
        .order_by(LedgerEntryRow.id)
        .with_for_update()
    )


def delete_entries(ids: Collection[uuid.UUID]) -> Delete:
    return delete(LedgerEntryRow).where(LedgerEntryRow.id.in_(list(ids)))


def entries_of_type(
    entry_type: EntryType, start_date: date, end_date: date
) -> Select[LedgerEntryRow]:
    """Entries of one type dated in [start_date, end_date], in order."""
    return (
        select(LedgerEntryRow)
        .where(
            LedgerEntryRow.type == entry_type.value,
            LedgerEntryRow.entry_date.between(start_date, end_date),
        )
        .order_by(*_ORDER_KEY)
    )


def any_on_or_before(day: date, entry_type: EntryType | None) -> Select[bool]:
    """Whether an entry, of ``entry_type`` or of either type, is dated on or before ``day``."""
    conditions = [LedgerEntryRow.entry_date <= day]
    if entry_type is not None:
        conditions.append(LedgerEntryRow.type == entry_type.value)
    return select(exists().where(*conditions))


def trade_asset_ids(start_date: date, end_date: date) -> Select[uuid.UUID | None]:
    """The contracts of the trades dated in [start_date, end_date]."""
    return (
        select(LedgerEntryRow.asset_id)
        .where(
            LedgerEntryRow.type == EntryType.TRADE.value,
            LedgerEntryRow.entry_date.between(start_date, end_date),
        )
        .distinct()
    )


def page(request: PageRequest, matching_asset_ids: Collection[uuid.UUID]) -> Select[LedgerEntryRow]:
    """One page of entries plus one more row, which tells whether a next page exists.
    ``matching_asset_ids`` are the contracts whose code matches the search, if any."""
    conditions: list[ColumnElement[bool]] = [
        LedgerEntryRow.entry_date.between(request.start_date, request.end_date),
    ]
    if request.search is not None:
        conditions.append(_matches(request.search, matching_asset_ids))
    descending = request.order is ListOrder.DESC
    if request.after is not None:
        key = tuple_(*_ORDER_KEY)
        after = tuple_(
            literal(request.after.entry_date),
            literal(request.after.entry_time),
            literal(request.after.seq),
        )
        conditions.append(key < after if descending else key > after)
    order_by = [column.desc() if descending else column.asc() for column in _ORDER_KEY]
    return (
        select(LedgerEntryRow).where(and_(*conditions)).order_by(*order_by).limit(request.limit + 1)
    )


def _matches(search: EntrySearch, matching_asset_ids: Collection[uuid.UUID]) -> ColumnElement[bool]:
    is_cash = LedgerEntryRow.type == EntryType.CASH.value
    options: list[ColumnElement[bool]] = []
    if matching_asset_ids:
        options.append(
            and_(
                LedgerEntryRow.type == EntryType.TRADE.value,
                LedgerEntryRow.asset_id.in_(list(matching_asset_ids)),
            )
        )
    if search.includes_deposits:
        options.append(and_(is_cash, LedgerEntryRow.cash_amount > 0))
    if search.includes_withdrawals:
        options.append(and_(is_cash, LedgerEntryRow.cash_amount < 0))
    return or_(*options) if options else false()
