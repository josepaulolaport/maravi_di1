"""A first connection that fails, or is cancelled, leaves no reconnect loop behind.

aio-pika's robust connection starts a background reconnect task as soon as it tries to connect.
If the first attempt fails or is cancelled (SIGTERM while the broker hangs), that task kept
retrying every 5 s and kept the event loop from closing, so the process could not exit.
interfaces.md "Transaction boundaries" 7 (relay and workers recover; they must also stop).
No RabbitMQ is needed: the brokers here are a closed port and a server that never answers.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from aio_pika.exceptions import AMQPConnectionError
from pydantic import SecretStr

from di1.platform.messaging.connection import connect


def _broker(url: str) -> SecretStr:
    return SecretStr(url)


def _connection_tasks() -> list[str]:
    return [
        name
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and "Connection" in (name := task.get_coro().__qualname__)  # type: ignore[union-attr]
    ]


@pytest.fixture
async def hanging_broker_url() -> AsyncIterator[str]:
    """A TCP server that accepts connections and never answers."""
    held: list[asyncio.StreamWriter] = []

    async def hold(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        held.append(writer)

    server = await asyncio.start_server(hold, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"amqp://guest:guest@127.0.0.1:{port}/"
    finally:
        for writer in held:
            writer.close()
        server.close()
        await server.wait_closed()


async def test_a_refused_first_connection_raises_and_leaves_no_task() -> None:
    with pytest.raises(AMQPConnectionError):
        await connect(_broker("amqp://guest:guest@127.0.0.1:1/"), connection_name="test")

    await asyncio.sleep(0.1)
    assert _connection_tasks() == []


async def test_a_cancelled_first_connection_leaves_no_task(hanging_broker_url: str) -> None:
    connecting = asyncio.create_task(connect(_broker(hanging_broker_url), connection_name="test"))
    await asyncio.sleep(0.3)
    assert not connecting.done()

    connecting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await connecting

    await asyncio.sleep(0.1)
    assert _connection_tasks() == []
