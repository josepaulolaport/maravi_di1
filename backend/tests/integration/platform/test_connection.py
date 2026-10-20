"""A first connection that fails, or is cancelled, leaves no reconnect loop behind.

aio-pika's robust connection starts a background reconnect task as soon as it tries to connect.
If the first attempt fails or is cancelled (SIGTERM while the broker hangs), that task kept
retrying every 5 s and kept the event loop from closing, so the process could not exit.
interfaces.md "Transaction boundaries" 7 (relay and workers recover; they must also stop).
No RabbitMQ is needed: the brokers here are a closed port and a server that never answers.
"""

from __future__ import annotations

import asyncio

import pytest
from aio_pika.exceptions import AMQPConnectionError
from pydantic import SecretStr

from di1.platform.config import BrokerSettings
from di1.platform.messaging.connection import connect
from tests.support.broker import SilentServer
from tests.support.waits import eventually


def _broker(url: str) -> BrokerSettings:
    return BrokerSettings(rabbitmq_url=SecretStr(url))


def _connection_tasks() -> list[str]:
    return [
        name
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and "Connection" in (name := task.get_coro().__qualname__)  # type: ignore[union-attr]
    ]


async def test_a_refused_first_connection_raises_and_leaves_no_task() -> None:
    with pytest.raises(AMQPConnectionError):
        await connect(_broker("amqp://guest:guest@127.0.0.1:1/"), connection_name="test")

    await eventually(lambda: _connection_tasks() == [], every=0.05)


async def test_a_cancelled_first_connection_leaves_no_task(
    hanging_broker_url: str, silent: SilentServer
) -> None:
    connecting = asyncio.create_task(connect(_broker(hanging_broker_url), connection_name="test"))
    await eventually(lambda: silent.accepted > 0)  # stuck on the silent server
    # A window in which nothing may happen: the connection keeps hanging.
    done, _ = await asyncio.wait({connecting}, timeout=0.3)
    assert not done

    connecting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await connecting

    await eventually(lambda: _connection_tasks() == [], every=0.05)
