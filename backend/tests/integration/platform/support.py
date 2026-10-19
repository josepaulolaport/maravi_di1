"""Helpers shared by the consumer and reconnect tests.

The handler's "state change" writes a row for consumer ``effect`` in ``platform.inbox_messages``:
a neutral table, so no business table is touched.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.platform.config import BrokerSettings
from di1.platform.database.unit_of_work import UnitOfWork, unit_of_work_factory
from di1.platform.messaging.consumer import MessageConsumer, PermanentMessageError
from di1.platform.messaging.envelope import Envelope

EFFECT = text(
    "INSERT INTO platform.inbox_messages (consumer_name, message_id) VALUES ('effect', :m)"
)


def make_envelope() -> Envelope:
    return Envelope(
        message_id=uuid.uuid4(),
        message_type="test.command",
        schema_version=1,
        created_at=datetime(2026, 10, 18, 15, 30, tzinfo=UTC),
        payload={},
    )


async def effects(engine: AsyncEngine) -> list[uuid.UUID]:
    """What another connection sees: only committed state changes."""
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT message_id FROM platform.inbox_messages"
                " WHERE consumer_name = 'effect' ORDER BY processed_at"
            )
        )
        return [row[0] for row in rows]


async def has_effects(engine: AsyncEngine, expected: list[uuid.UUID]) -> bool:
    return await effects(engine) == expected


@dataclass
class RecordingHandler:
    """Writes the effect; fails its first ``failures`` calls (``permanent`` or transient)."""

    failures: int = 0
    permanent: bool = False
    commits_itself: bool = False
    calls: list[uuid.UUID] = field(default_factory=list)

    async def __call__(self, envelope: Envelope, *, uow: UnitOfWork) -> None:
        self.calls.append(envelope.message_id)
        await uow.session.execute(EFFECT, {"m": envelope.message_id})
        if len(self.calls) <= self.failures:
            raise PermanentMessageError if self.permanent else RuntimeError("transient")
        if self.commits_itself:
            await uow.commit()


FAST_RETRIES = BrokerSettings(
    rabbitmq_url=SecretStr("amqp://unused/"), rabbitmq_retry_base_delay_seconds=0.01
)
"""For tests that call the consumer directly, without a broker."""


def make_consumer(
    session_factory: async_sessionmaker[AsyncSession],
    handler: RecordingHandler,
    settings: BrokerSettings = FAST_RETRIES,
) -> MessageConsumer:
    return MessageConsumer(
        consumer_name="worker",
        handler=handler,
        uow_factory=unit_of_work_factory(session_factory),
        settings=settings,
    )


async def eventually(condition: Callable[[], bool | Awaitable[bool]], within: float = 10.0) -> None:
    """Poll state that lives in the broker or the database: there is no event to await."""
    async with asyncio.timeout(within):
        while True:
            result = condition()
            if await result if inspect.isawaitable(result) else result:
                return
            await asyncio.sleep(0.05)
