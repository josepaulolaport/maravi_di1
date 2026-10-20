"""Inbox idempotency: a consumer handles each message once, however often it is delivered.

interfaces.md "Transaction boundaries" 7: delivery is at least once. The consumer records the
``message_id`` in ``platform.inbox_messages`` in the same transaction as the handler's state
change, so the record and the change commit or roll back together. A concurrent duplicate
waits on the primary key until the first transaction ends, then sees the record.

Retention (user decision M9, 2026-10-19): a row only guards against a redelivery, which comes
within seconds or minutes, so rows older than ``inbox_retention_days`` are deleted
(`InboxRetention`, run by the outbox relay's poll loop). A message delivered again after that
would be handled again; the only message today is the doorbell, which is harmless twice.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import text

from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from di1.platform.messaging.retention import Retention

CONSUMER_NAME_MAX_LENGTH = 128
"""``platform.inbox_messages.consumer_name`` is ``VARCHAR(128)``."""

_INSERT = text(
    "INSERT INTO platform.inbox_messages (consumer_name, message_id)"
    " VALUES (:consumer_name, :message_id)"
    " ON CONFLICT (consumer_name, message_id) DO NOTHING"
    " RETURNING message_id"
)
_DELETE_PROCESSED_BEFORE = text(
    "DELETE FROM platform.inbox_messages WHERE processed_at < now() - :older_than"
)


async def record_delivery(uow: UnitOfWork, *, consumer_name: str, message_id: uuid.UUID) -> bool:
    """Record the delivery in ``uow``'s transaction; `False` when it was already recorded (a
    duplicate the handler must not process again)."""
    recorded = await uow.session.scalar(
        _INSERT, {"consumer_name": consumer_name, "message_id": message_id}
    )
    return recorded is not None


async def delete_processed_before(uow: UnitOfWork, *, older_than: timedelta) -> int:
    """Delete the records processed more than ``older_than`` ago; return how many."""
    result = await uow.session.execute(_DELETE_PROCESSED_BEFORE, {"older_than": older_than})
    return int(result.rowcount)  # type: ignore[attr-defined]


class InboxRetention(Retention):
    """Deletes the inbox records processed more than ``older_than`` ago, at most once per
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
            return await delete_processed_before(uow, older_than=older_than)

        super().__init__(
            uow_factory, name="inbox", delete=delete, interval_seconds=interval_seconds, clock=clock
        )
