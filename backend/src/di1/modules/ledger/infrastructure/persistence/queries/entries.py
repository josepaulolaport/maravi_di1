"""The SQL of ``ledger.entries``. Reads follow the order ``(entry_date, entry_time, seq)``. A
deletion removes the rows for good (user decision 2026-10-19)."""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import date
from typing import Any, cast

from sqlalchemy import (
    ColumnElement,
    Delete,
    Insert,
    Select,
    Table,
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

from di1.modules.ledger.domain.entries import EntryType
from di1.modules.ledger.domain.listing import EntrySearch, ListOrder, PageRequest
from di1.modules.ledger.infrastructure.persistence.models import LedgerEntryRow

entries = cast(Table, LedgerEntryRow.__table__)
_ORDER_KEY = (entries.c.entry_date, entries.c.entry_time, entries.c.seq)


def insert_entry(values: dict[str, Any]) -> Insert:
    """Insert one entry; the database assigns ``id``, ``seq`` and ``created_at``."""
    return insert(entries).values(**values).returning(*entries.c)


def ids_for_update(ids: Collection[uuid.UUID]) -> Select[Any]:
    """The ids among ``ids`` that name an entry, those rows locked in id order so that two
    concurrent deletions lock in the same order. A row deleted by a concurrent transaction is
    absent once that transaction commits."""
    return (
        select(entries.c.id)
        .where(entries.c.id.in_(list(ids)))
        .order_by(entries.c.id)
        .with_for_update()
    )


def delete_entries(ids: Collection[uuid.UUID]) -> Delete:
    return delete(entries).where(entries.c.id.in_(list(ids)))


def entries_of_type(entry_type: EntryType, start_date: date, end_date: date) -> Select[Any]:
    """Entries of one type dated in [start_date, end_date], in order."""
    return (
        select(*entries.c)
        .where(
            entries.c.type == entry_type.value,
            entries.c.entry_date.between(start_date, end_date),
        )
        .order_by(*_ORDER_KEY)
    )


def any_on_or_before(day: date, entry_type: EntryType | None) -> Select[Any]:
    """Whether an entry, of ``entry_type`` or of either type, is dated on or before ``day``."""
    conditions = [entries.c.entry_date <= day]
    if entry_type is not None:
        conditions.append(entries.c.type == entry_type.value)
    return select(exists().where(*conditions))


def trade_asset_ids(start_date: date, end_date: date) -> Select[Any]:
    """The contracts of the trades dated in [start_date, end_date]."""
    return (
        select(entries.c.asset_id)
        .where(
            entries.c.type == EntryType.TRADE.value,
            entries.c.entry_date.between(start_date, end_date),
        )
        .distinct()
    )


def page(request: PageRequest, matching_asset_ids: Collection[uuid.UUID]) -> Select[Any]:
    """One page of entries plus one more row, which tells whether a next page exists.
    ``matching_asset_ids`` are the contracts whose code matches the search, if any."""
    conditions: list[ColumnElement[bool]] = [
        entries.c.entry_date.between(request.start_date, request.end_date),
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
    return select(*entries.c).where(and_(*conditions)).order_by(*order_by).limit(request.limit + 1)


def _matches(search: EntrySearch, matching_asset_ids: Collection[uuid.UUID]) -> ColumnElement[bool]:
    is_cash = entries.c.type == EntryType.CASH.value
    options: list[ColumnElement[bool]] = []
    if matching_asset_ids:
        options.append(
            and_(
                entries.c.type == EntryType.TRADE.value,
                entries.c.asset_id.in_(list(matching_asset_ids)),
            )
        )
    if search.includes_deposits:
        options.append(and_(is_cash, entries.c.cash_amount > 0))
    if search.includes_withdrawals:
        options.append(and_(is_cash, entries.c.cash_amount < 0))
    return or_(*options) if options else false()
