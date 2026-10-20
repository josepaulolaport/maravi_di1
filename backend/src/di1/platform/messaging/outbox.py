"""The outbox writer: a message to publish is saved in the business write's own transaction.

A write that must reach the worker (Processing's run message) saves its outbox command in
the same transaction as the fact it signals, with one COMMIT. Nothing is sent to the broker here;
the outbox relay publishes committed rows later, so a rolled-back write never publishes and a
committed one is published at least once.

Retention: a published row is only history, so rows published more than
``outbox_retention_days`` ago are deleted (`OutboxRetention`, run by the outbox relay's poll
loop). An unpublished row is never deleted, however old.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

from pydantic import JsonValue
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from di1.platform.messaging.envelope import Envelope
from di1.platform.messaging.retention import Retention

_INSERT = text(
    "INSERT INTO platform.outbox_messages"
    " (message_id, message_type, schema_version, payload, created_at)"
    " VALUES (:message_id, :message_type, :schema_version, :payload, :created_at)"
).bindparams(bindparam("payload", type_=JSONB))
_DELETE_PUBLISHED_BEFORE = text(
    "DELETE FROM platform.outbox_messages"
    " WHERE published_at IS NOT NULL AND published_at < now() - :older_than"
)


async def add_outbox_message(
    uow: UnitOfWork,
    *,
    message_type: str,
    payload: Mapping[str, JsonValue],
    schema_version: int = 1,
) -> Envelope:
    """Save a message in ``uow``'s transaction and return its envelope.

    The caller commits ``uow`` as usual. An invalid message (a float in the payload, for
    instance) raises `pydantic.ValidationError` before anything is written.
    """
    envelope = Envelope(
        message_id=uuid.uuid4(),
        message_type=message_type,
        schema_version=schema_version,
        created_at=datetime.now(UTC),
        payload=dict(payload),
    )
    await uow.session.execute(_INSERT, envelope.model_dump())
    return envelope


async def delete_published_before(uow: UnitOfWork, *, older_than: timedelta) -> int:
    """Delete the rows published more than ``older_than`` ago; return how many."""
    result = await uow.session.execute(_DELETE_PUBLISHED_BEFORE, {"older_than": older_than})
    return int(result.rowcount)  # type: ignore[attr-defined]


class OutboxRetention(Retention):
    """Deletes the outbox rows published more than ``older_than`` ago, at most once per
    ``interval_seconds``."""

    def __init__(
        self,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        *,
        older_than: timedelta,
        interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        async def delete(uow: UnitOfWork) -> int:
            return await delete_published_before(uow, older_than=older_than)

        super().__init__(
            uow_factory,
            name="outbox",
            delete=delete,
            interval_seconds=interval_seconds,
            clock=clock,
        )
