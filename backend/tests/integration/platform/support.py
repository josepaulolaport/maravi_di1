"""Helpers shared by the worker, relay and reconnect tests.

The handler's "state change" writes a row in ``public.test_effects``, a table of the test's
own (`CREATE_EFFECTS`), so no business table is touched.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import json
import urllib.parse
import urllib.request
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aio_pika.abc import AbstractQueue
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.platform.config import Settings
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.platform.messaging.consumer import Job, JobLoop, MessageConsumer, MessageHandler
from di1.platform.messaging.envelope import Envelope

PUBLISH_TIMEOUT_SECONDS = 5.0
"""The tests' publisher confirm timeout (``RABBITMQ_PUBLISH_TIMEOUT_SECONDS``)."""


def with_broker(settings: Settings, broker_url: SecretStr, **updates: Any) -> Settings:
    """``settings`` (the test's database) with the test broker and ``updates`` (sweep and
    heartbeat intervals): what a worker process reads."""
    return settings.model_copy(
        update={
            "rabbitmq_url": broker_url,
            "rabbitmq_publish_timeout_seconds": PUBLISH_TIMEOUT_SECONDS,
            **updates,
        }
    )


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


async def eventually(condition: Callable[[], bool | Awaitable[bool]], within: float = 10.0) -> None:
    """Poll state that lives in the broker or the database: there is no event to await."""
    async with asyncio.timeout(within):
        while True:
            result = condition()
            if await result if inspect.isawaitable(result) else result:
                return
            await asyncio.sleep(0.05)


def _management(url: str, method: str, path: str) -> object:
    parsed = urllib.parse.urlsplit(url)
    credentials = f"{parsed.username}:{parsed.password}".encode()
    request = urllib.request.Request(
        f"{parsed.scheme}://{parsed.hostname}:{parsed.port}{path}",
        method=method,
        headers={"Authorization": f"Basic {base64.b64encode(credentials).decode()}"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read()
    return json.loads(body) if body else None


async def close_connections(url: str, connection_name: str) -> int:
    def close() -> int:
        connections = _management(url, "GET", "/api/connections")
        names = [
            entry["name"]
            for entry in connections  # type: ignore[attr-defined]
            if entry.get("user_provided_name") == connection_name
        ]
        for name in names:
            _management(url, "DELETE", f"/api/connections/{urllib.parse.quote(name, safe='')}")
        return len(names)

    closed = 0

    async def any_closed() -> bool:  # the management API lists new connections late
        nonlocal closed
        closed = await asyncio.to_thread(close)
        return closed > 0

    await eventually(any_closed, within=15)
    return closed
