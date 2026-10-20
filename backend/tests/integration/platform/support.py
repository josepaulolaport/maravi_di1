"""Helpers shared by the worker, relay and reconnect tests.

The handler's "state change" writes a row in ``public.test_effects``, a table of the test's
own (`CREATE_EFFECTS`), so no business table is touched.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from aio_pika.abc import AbstractQueue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.platform.messaging.consumer import Job, JobLoop, MessageConsumer, MessageHandler
from di1.platform.messaging.envelope import Envelope

CREATE_EFFECTS = text(
    "CREATE TABLE IF NOT EXISTS public.test_effects (message_id UUID PRIMARY KEY,"
    " written_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())"
)
EFFECT = text("INSERT INTO public.test_effects (message_id) VALUES (:m)")


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
            text("SELECT message_id FROM public.test_effects ORDER BY written_at")
        )
        return [row[0] for row in rows]


async def has_effects(engine: AsyncEngine, expected: list[uuid.UUID]) -> bool:
    return await effects(engine) == expected


@dataclass
class RecordingHandler:
    """Commits the effect of each message and starts nothing after it. ``calls`` records a
    message only once its effect has committed, so a test waiting on it sees the effect."""

    uow_factory: Callable[[], SqlAlchemyUnitOfWork]
    calls: list[uuid.UUID] = field(default_factory=list)

    async def __call__(self, envelope: Envelope) -> Job | None:
        async with self.uow_factory() as uow:
            await uow.session.execute(EFFECT, {"m": envelope.message_id})
            await uow.commit()
        self.calls.append(envelope.message_id)
        return None


async def _no_sweep() -> None:
    return None


@contextlib.asynccontextmanager
async def consuming(queue: AbstractQueue, handler: MessageHandler) -> AsyncIterator[None]:
    """Consume ``queue`` with ``handler`` through a job loop of the test's own."""
    jobs = JobLoop(sweep=_no_sweep, sweep_interval_seconds=3600)
    loop = asyncio.create_task(jobs.run())
    consumer = MessageConsumer(name="test", handler=handler, jobs=jobs)
    tag = await queue.consume(consumer.handle, no_ack=False)
    try:
        yield
    finally:
        await queue.cancel(tag)
        loop.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop
