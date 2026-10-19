"""The outbox writer: a message to publish is saved in the business write's own transaction.

A write that must reach the worker (Processing's doorbell, OQ-46) saves its outbox command in
the same transaction as the fact it signals, with one COMMIT. Nothing is sent to the broker here;
the outbox relay publishes committed rows later, so a rolled-back write never publishes and a
committed one is published at least once.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import JsonValue
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from di1.platform.database.unit_of_work import UnitOfWork
from di1.platform.messaging.envelope import Envelope

_INSERT = text(
    "INSERT INTO platform.outbox_messages"
    " (message_id, message_type, schema_version, payload, created_at)"
    " VALUES (:message_id, :message_type, :schema_version, :payload, :created_at)"
).bindparams(bindparam("payload", type_=JSONB))


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
