"""SQL over ``processing.requests``. Row locks are taken in one order: a run's row, then its
dates ascending. ``claim_token``, ``lease_expires_at`` and ``attempt_count`` are unused since
OQ-45."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Insert, Select, TextClause, Update, exists, insert, select, text, tuple_
from sqlalchemy import update as sql_update

from di1.modules.processing.infrastructure.persistence.models import RequestRow

QUEUE_LOCK_KEY = 0x44_49_31_51  # "DI1Q": the one advisory lock key of the processing queue

_QUEUED, _RUNNING = "QUEUED", "RUNNING"
_OLDEST_FIRST = (RequestRow.created_at, RequestRow.id)


def insert_request(values: dict[str, Any]) -> Insert:
    return insert(RequestRow).values(**values)


def update_request(request_id: UUID, values: dict[str, Any]) -> Update:
    return sql_update(RequestRow).where(RequestRow.id == request_id).values(**values)


def request(request_id: UUID, *, for_update: bool) -> Select[RequestRow]:
    statement = select(RequestRow).where(RequestRow.id == request_id)
    return statement.with_for_update() if for_update else statement


def newest_first(limit: int, after: tuple[datetime, UUID] | None) -> Select[RequestRow]:
    """Keyset page on ``(created_at, id)`` descending (OQ-26 item 1)."""
    statement = select(RequestRow)
    if after is not None:
        statement = statement.where(tuple_(*_OLDEST_FIRST) < tuple_(*after))
    return statement.order_by(RequestRow.created_at.desc(), RequestRow.id.desc()).limit(limit)


def running(*, for_update: bool) -> Select[RequestRow]:
    statement = select(RequestRow).where(RequestRow.status == _RUNNING).order_by(*_OLDEST_FIRST)
    return statement.with_for_update() if for_update else statement


def oldest_queued() -> Select[RequestRow]:
    """Row-locked: the take sets it RUNNING in the same transaction (OQ-5 item 4, OQ-46)."""
    return (
        select(RequestRow)
        .where(RequestRow.status == _QUEUED)
        .order_by(*_OLDEST_FIRST)
        .limit(1)
        .with_for_update()
    )


def any_queued() -> Select[tuple[bool]]:
    return select(exists().where(RequestRow.status == _QUEUED))


LOCK_QUEUE: TextClause = text("SELECT pg_advisory_xact_lock(:key)")
"""The queue's transaction-scoped advisory lock (no Core construct for it)."""
