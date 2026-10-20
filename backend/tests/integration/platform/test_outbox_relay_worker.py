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
import re
import signal
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from aio_pika.abc import AbstractRobustConnection
from aio_pika.exceptions import ChannelClosed, ChannelInvalidStateError
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.platform.config import Settings
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.platform.messaging.connection import connect
from di1.platform.messaging.envelope import Envelope
from di1.platform.messaging.outbox import add_outbox_message
from di1.platform.messaging.publisher import MessagePublisher
from di1.platform.messaging.topology import Topology
from di1.platform.observability.heartbeat import Heartbeat
from di1.workers import outbox_relay
from di1.workers.outbox_relay import run_outbox_relay
from tests.integration.platform.conftest import queue_spec
from tests.integration.platform.support import eventually, with_broker


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

    await eventually(lambda: path.exists() and path.stat().st_mtime > 1000.0)
    stop.set()
    await asyncio.wait_for(running, timeout=10)


async def _first_message(
    broker: AbstractRobustConnection, queue_name: str, running: asyncio.Task[None]
) -> bytes:
    """Wait until the relay has declared the queue and a message is in it. A passive declare of
    a queue that does not exist yet closes its channel, so each try uses a new one; a relay that
    failed ends the wait with its own error."""
    async with asyncio.timeout(15):
        while True:
            if running.done():
                running.result()
                raise AssertionError("the relay stopped before publishing")
            channel = await broker.channel()
            try:
                queue = await channel.declare_queue(queue_name, passive=True)
                message = await queue.get(fail=False)
                if message is not None:
                    await message.ack()
                    return message.body
            except (ChannelClosed, ChannelInvalidStateError):
                pass
            finally:
                if not channel.is_closed:
                    await channel.close()
            await asyncio.sleep(0.05)


async def _silent_server() -> AsyncIterator[str]:
    """A TCP server that accepts connections and never answers: a broker that hangs."""

    async def hold(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read()
        writer.close()

    server = await asyncio.start_server(hold, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"amqp://guest:s3cret-pw@127.0.0.1:{port}/"
    finally:
        server.close()


@pytest.fixture
async def hanging_broker_url() -> AsyncIterator[str]:
    async for url in _silent_server():
        yield url


async def test_a_stop_while_connecting_to_the_broker_ends_the_relay(
    settings: Settings, hanging_broker_url: str
) -> None:
    """SIGTERM must work even when the broker hangs at startup, before Docker's SIGKILL."""
    stop = asyncio.Event()
    running = asyncio.create_task(
        run_outbox_relay(
            with_broker(settings, SecretStr(hanging_broker_url)),
            queues=(),
            stop=stop,
        )
    )
    await asyncio.sleep(0.3)
    assert not running.done()

    stop.set()

    await asyncio.wait_for(running, timeout=2)


async def test_the_relay_process_stops_cleanly_on_sigterm(
    settings: Settings, broker_url: SecretStr, tmp_path: Path
) -> None:
    """The process runs its real topology (``di1.commands``): the one exception to test-owned
    broker names. It declares the composition's one queue, ``processing.run``; the declarations
    are idempotent, so it leaves nothing that another test could conflict with."""
    environment = os.environ | {
        "DATABASE_URL": settings.database_url.get_secret_value(),
        "RABBITMQ_URL": broker_url.get_secret_value(),
        "LOG_LEVEL": "INFO",
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "di1.workers.outbox_relay",
        cwd=tmp_path,
        env=environment,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stderr is not None
    try:
        async with asyncio.timeout(30):
            started = b""
            while b"outbox relay started" not in started:
                line = await process.stderr.readline()
                assert line, f"the relay exited early: {started.decode()}"
                started += line
        process.send_signal(signal.SIGTERM)
        async with asyncio.timeout(15):
            rest = await process.stderr.read()
            code = await process.wait()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()

    output = (started + rest).decode()
    assert code == 0, output
    assert "outbox relay started (1 queues declared)" in output
    assert "outbox relay stopped" in output
    assert broker_url.get_secret_value() not in output
    assert settings.database_url.get_secret_value() not in output


async def test_a_startup_failure_is_logged_and_exits_with_status_1(
    settings: Settings, tmp_path: Path
) -> None:
    environment = os.environ | {
        "DATABASE_URL": settings.database_url.get_secret_value(),
        "RABBITMQ_URL": "amqp://guest:s3cret-pw@127.0.0.1:1/",
        "LOG_LEVEL": "INFO",
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "di1.workers.outbox_relay",
        cwd=tmp_path,
        env=environment,
        stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(30):
        _, error_output = await process.communicate()

    output = error_output.decode()
    assert process.returncode == 1, output
    # Run with ``-m``, the module's logger is ``__main__``.
    assert re.search(r"Z ERROR __main__ outbox relay failed\n", output), output
    assert "s3cret-pw" not in output


async def _hang(*args: object, **kwargs: object) -> None:
    await asyncio.Event().wait()


@pytest.mark.parametrize("step", ["declare_queue", "MessagePublisher.create"])
async def test_a_stop_while_the_broker_stalls_after_connecting_ends_the_relay(
    settings: Settings,
    broker_url: SecretStr,
    topology: Topology,
    monkeypatch: pytest.MonkeyPatch,
    step: str,
) -> None:
    """The broker accepted the connection but never answers a declaration: aio-pika waits
    without a timeout, so the startup steps must observe the stop as well."""
    stalled = asyncio.Event()

    async def stall(*args: object, **kwargs: object) -> None:
        stalled.set()
        await _hang()

    if step == "declare_queue":
        monkeypatch.setattr(outbox_relay, "declare_queue", stall)
    else:
        monkeypatch.setattr(MessagePublisher, "create", stall)
    connections: list[AbstractRobustConnection] = []

    async def recording_connect(*args: Any, **kwargs: Any) -> AbstractRobustConnection:
        connection = await connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(outbox_relay, "connect", recording_connect)
    stop = asyncio.Event()
    running = asyncio.create_task(
        run_outbox_relay(
            with_broker(settings, broker_url),
            queues=[queue_spec(topology, "test.command")],
            stop=stop,
            topology=topology,
        )
    )
    await asyncio.wait_for(stalled.wait(), timeout=10)

    stop.set()

    await asyncio.wait_for(running, timeout=2)
    [connection] = connections
    assert connection.is_closed


async def test_a_connection_made_as_the_relay_is_cancelled_is_closed(
    settings: Settings, broker_url: SecretStr, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cancellation lands in the same loop step as the connection: it must not leak a
    connection, and its reconnect task, that nobody closes."""
    connections: list[AbstractRobustConnection] = []
    running: asyncio.Task[None] | None = None

    async def connect_then_cancel(*args: Any, **kwargs: Any) -> AbstractRobustConnection:
        connection = await connect(*args, **kwargs)
        connections.append(connection)
        assert running is not None
        running.cancel()
        return connection

    monkeypatch.setattr(outbox_relay, "connect", connect_then_cancel)
    running = asyncio.create_task(
        run_outbox_relay(with_broker(settings, broker_url), queues=(), stop=asyncio.Event())
    )

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, timeout=10)

    [connection] = connections
    assert connection.is_closed
