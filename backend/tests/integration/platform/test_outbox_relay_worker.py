"""The outbox relay process: declares the consumer queues it is given, relays committed outbox
rows until it is stopped, and shuts down cleanly on SIGTERM.

interfaces.md "Transaction boundaries" 3 and 7 ("DI composition": workers use plain
factories); plan §5 H and the H3 row of plan "Remaining, by lane". The queues are declared at
startup so a command published before its worker has started is routed, not refused
(NO_ROUTE).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from aio_pika.abc import AbstractRobustConnection
from aio_pika.exceptions import ChannelClosed, ChannelInvalidStateError
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.platform.config import Settings
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.platform.messaging.envelope import Envelope
from di1.platform.messaging.outbox import add_outbox_message
from di1.platform.messaging.topology import Topology
from di1.platform.observability.heartbeat import Heartbeat
from di1.workers.outbox_relay import run_outbox_relay
from tests.integration.platform.support import with_broker
from tests.support.broker import queue_spec
from tests.support.waits import eventually


async def test_the_relay_declares_the_queues_and_publishes_until_stopped(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    broker: AbstractRobustConnection,
    broker_url: SecretStr,
    topology: Topology,
) -> None:
    """No worker has declared the queue yet: the relay does, so the command is routed."""
    spec = queue_spec(topology, "test.command")
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        written = await add_outbox_message(uow, message_type="test.command", payload={"n": 1})
        await uow.commit()
    stop = asyncio.Event()

    running = asyncio.create_task(
        run_outbox_relay(
            with_broker(settings, broker_url), queues=[spec], stop=stop, topology=topology
        )
    )
    message = await _first_message(broker, spec.name, running)
    stop.set()
    await asyncio.wait_for(running, timeout=10)

    assert Envelope.from_json(message) == written


async def test_the_relay_beats_its_heartbeat_once_it_relays(
    settings: Settings,
    broker_url: SecretStr,
    topology: Topology,
    tmp_path: Path,
) -> None:
    """The heartbeat follows the poll loop (compose.yaml's health check): a stale file left by
    a previous process is removed at start, and the loop writes it again on its first turn."""
    path = tmp_path / "relay.heartbeat"
    path.touch()
    os.utime(path, (1000.0, 1000.0))
    stop = asyncio.Event()
    running = asyncio.create_task(
        run_outbox_relay(
            with_broker(settings, broker_url),
            queues=[],
            stop=stop,
            topology=topology,
            heartbeat=Heartbeat(path),
        )
    )

    await eventually(lambda: path.exists() and path.stat().st_mtime > 1000.0, every=0.05)
    stop.set()
    await asyncio.wait_for(running, timeout=10)


async def _first_message(
    broker: AbstractRobustConnection, queue_name: str, running: asyncio.Task[None]
) -> bytes:
    """Wait until the relay has declared the queue and a message is in it. A passive declare of
    a queue that does not exist yet closes its channel, so each try uses a new one; a relay that
    failed ends the wait with its own error."""
    bodies: list[bytes] = []

    async def published() -> bool:
        if running.done():
            running.result()
            raise AssertionError("the relay stopped before publishing")
        channel = await broker.channel()
        try:
            queue = await channel.declare_queue(queue_name, passive=True)
            message = await queue.get(fail=False)
            if message is not None:
                await message.ack()
                bodies.append(message.body)
        except (ChannelClosed, ChannelInvalidStateError):
            pass
        finally:
            if not channel.is_closed:
                await channel.close()
        return bool(bodies)

    await eventually(published, within=15, every=0.05)
    return bodies[0]
