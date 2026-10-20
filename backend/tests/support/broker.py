"""RabbitMQ for integration tests: the test broker from the environment, queue names of each
test's own, polling for state that lives in the broker or the database, and the management API.

``TEST_RABBITMQ_URL`` is a test broker (``amqp://guest:guest@127.0.0.1:5672/``) and
``TEST_RABBITMQ_MANAGEMENT_URL`` its management API (``http://guest:guest@127.0.0.1:15672``).
Without them the broker tests are skipped and reported, so **not verified**; with
``REQUIRE_BROKER_TESTS=1`` (set by ``make test-backend``) a missing variable fails the run.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator

import pytest
from aio_pika.abc import AbstractRobustConnection

from di1.platform.messaging.topology import QueueSpec, Topology
from tests.support.waits import eventually


def broker_url(variable: str = "TEST_RABBITMQ_URL") -> str:
    """The URL in ``variable``; the test is skipped, or failed when broker tests are required,
    without it."""
    url = os.environ.get(variable)
    if not url:
        if os.environ.get("REQUIRE_BROKER_TESTS") == "1":
            pytest.fail(f"REQUIRE_BROKER_TESTS=1 but {variable} is not set")
        pytest.skip(f"{variable} is not set: broker tests not run")
    return url


TEST_QUEUES = ("work", "other")
"""Queue names the broker tests use, prefixed by their topology's exchange name."""


def queue_spec(topology: Topology, *routing_keys: str, name: str = "work") -> QueueSpec:
    assert name in TEST_QUEUES, "add the name to TEST_QUEUES so the test deletes it"
    return QueueSpec(name=f"{topology.exchange}.{name}", routing_keys=routing_keys)


async def delete_topology(connection: AbstractRobustConnection, topology: Topology) -> None:
    channel = await connection.channel()
    for queue in TEST_QUEUES:
        await channel.queue_delete(f"{topology.exchange}.{queue}")
    await channel.exchange_delete(topology.exchange)
    await channel.close()


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

    await eventually(any_closed, within=15, every=0.05)
    return closed


class SilentServer:
    """A TCP server that accepts connections and never answers: a broker or a database that
    hangs. ``accepted`` counts the connections it took, so a test can wait until a client is
    stuck on it instead of sleeping."""

    def __init__(self) -> None:
        self.accepted = 0
        self.port = 0
        self._held: list[asyncio.StreamWriter] = []

    async def _hold(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.accepted += 1
        self._held.append(writer)
        await reader.read()
        writer.close()


@contextlib.asynccontextmanager
async def silent_server() -> AsyncIterator[SilentServer]:
    silent = SilentServer()
    server = await asyncio.start_server(silent._hold, "127.0.0.1", 0)
    silent.port = server.sockets[0].getsockname()[1]
    try:
        yield silent
    finally:
        for writer in silent._held:
            writer.close()
        server.close()
        await server.wait_closed()
