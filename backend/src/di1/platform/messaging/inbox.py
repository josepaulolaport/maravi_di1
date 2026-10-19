"""Inbox idempotency: a consumer handles each message once, however often it is delivered.

interfaces.md "Transaction boundaries" 7: delivery is at least once. The consumer records the
``message_id`` in ``platform.inbox_messages`` in the same transaction as the handler's state
change, so the record and the change commit or roll back together. A concurrent duplicate
waits on the primary key until the first transaction ends, then sees the record.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from di1.platform.database.unit_of_work import UnitOfWork

CONSUMER_NAME_MAX_LENGTH = 128
"""``platform.inbox_messages.consumer_name`` is ``VARCHAR(128)``."""

_INSERT = text(
    "INSERT INTO platform.inbox_messages (consumer_name, message_id)"
    " VALUES (:consumer_name, :message_id)"
    " ON CONFLICT (consumer_name, message_id) DO NOTHING"
    " RETURNING message_id"
)


async def record_delivery(uow: UnitOfWork, *, consumer_name: str, message_id: uuid.UUID) -> bool:
    """Record the delivery in ``uow``'s transaction; `False` when it was already recorded (a
    duplicate the handler must not process again)."""
    recorded = await uow.session.scalar(
        _INSERT, {"consumer_name": consumer_name, "message_id": message_id}
    )
    return recorded is not None
