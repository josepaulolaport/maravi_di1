"""What both worker processes, the processing worker and the outbox relay, must do alike: stop on
SIGTERM while a dependency hangs (before Docker's SIGKILL), close a connection made as they are
cancelled, stop cleanly as a process, and exit 1 on a startup failure without a secret in the
logs.

Each test runs once per process that has the step (`di1.workers.lifecycle.unless_stopped` is the
shared mechanism). The relay does not check the database at startup, so only the worker has the
"database hangs" case.
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from aio_pika.abc import AbstractRobustConnection
from pydantic import SecretStr

from di1.platform.config import Settings
from di1.platform.messaging.connection import connect
from di1.platform.messaging.consumer import Job
from di1.platform.messaging.envelope import Envelope
from di1.platform.messaging.publisher import MessagePublisher
from di1.platform.messaging.topology import Topology
from di1.platform.messaging.worker import ConsumerRegistration, WorkerResources
from di1.workers import main as worker
from di1.workers import outbox_relay
from di1.workers.main import run_worker
from di1.workers.outbox_relay import run_outbox_relay
from tests.integration.platform.support import with_broker, worker_parts
from tests.support.broker import SilentServer, queue_spec
from tests.support.waits import eventually


async def _no_start(envelope: Envelope) -> Job | None:
    return None


@dataclass(frozen=True)
class _Process:
    name: str
    module: ModuleType
    start: Callable[[Settings, asyncio.Event, Topology | None], asyncio.Task[None]]


def _start_worker(
    settings: Settings, stop: asyncio.Event, topology: Topology | None
) -> asyncio.Task[None]:
    """The worker with one consumer, on a queue of the test's own when it has a topology."""

    def consumers(resources: WorkerResources) -> tuple[ConsumerRegistration, ...]:
        if topology is None:
            return ()
        spec = queue_spec(topology, "test.command")
        return (ConsumerRegistration(queue=spec, name="worker", handler=_no_start),)

    return asyncio.create_task(
        run_worker(
            settings,
            build=worker_parts(consumers=consumers),
            stop=stop,
            topology=topology,
        )
    )


def _start_relay(
    settings: Settings, stop: asyncio.Event, topology: Topology | None
) -> asyncio.Task[None]:
    queues = [queue_spec(topology, "test.command")] if topology is not None else []
    return asyncio.create_task(
        run_outbox_relay(settings, queues=queues, stop=stop, topology=topology)
    )


WORKER = _Process("worker", worker, _start_worker)
RELAY = _Process("relay", outbox_relay, _start_relay)


@pytest.mark.parametrize(
    ("process", "hangs"),
    [(WORKER, "database"), (WORKER, "broker"), (RELAY, "broker")],
    ids=["worker-database", "worker-broker", "relay-broker"],
)
async def test_a_stop_while_a_dependency_hangs_at_startup_ends_the_process(
    settings: Settings,
    broker_url: SecretStr,
    hanging_broker_url: str,
    hanging_database_settings: Settings,
    silent: SilentServer,
    process: _Process,
    hangs: str,
) -> None:
    """The dependency accepted the connection and never answers: the process is stuck on it
    until the stop, then ends at once."""
    if hangs == "database":
        configured = with_broker(hanging_database_settings, broker_url)
    else:
        configured = with_broker(settings, SecretStr(hanging_broker_url))
    stop = asyncio.Event()
    running = process.start(configured, stop, None)
    await eventually(lambda: silent.accepted > 0)  # stuck on the silent server
    assert not running.done()

    stop.set()

    await asyncio.wait_for(running, timeout=2)


async def _hang(*args: object, **kwargs: object) -> None:
    await asyncio.Event().wait()


@pytest.mark.parametrize(
    ("process", "step"),
    [(WORKER, "declare_queue"), (RELAY, "declare_queue"), (RELAY, "MessagePublisher.create")],
    ids=["worker-declare", "relay-declare", "relay-publisher"],
)
async def test_a_stop_while_the_broker_stalls_after_connecting_ends_the_process(
    settings: Settings,
    broker_url: SecretStr,
    topology: Topology,
    monkeypatch: pytest.MonkeyPatch,
    process: _Process,
    step: str,
) -> None:
    """The broker accepted the connection but never answers a declaration: aio-pika waits
    without a timeout, so the startup steps must observe the stop as well, and the connection
    is closed."""
    stalled = asyncio.Event()

    async def stall(*args: object, **kwargs: object) -> None:
        stalled.set()
        await _hang()

    if step == "declare_queue":
        monkeypatch.setattr(process.module, "declare_queue", stall)
    else:
        monkeypatch.setattr(MessagePublisher, "create", stall)
    connections: list[AbstractRobustConnection] = []

    async def recording_connect(*args: Any, **kwargs: Any) -> AbstractRobustConnection:
        connection = await connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(process.module, "connect", recording_connect)
    stop = asyncio.Event()
    running = process.start(with_broker(settings, broker_url), stop, topology)
    await asyncio.wait_for(stalled.wait(), timeout=10)

    stop.set()

    await asyncio.wait_for(running, timeout=2)
    [connection] = connections
    assert connection.is_closed


@pytest.mark.parametrize("process", [WORKER, RELAY], ids=["worker", "relay"])
async def test_a_connection_made_as_the_process_is_cancelled_is_closed(
    settings: Settings,
    broker_url: SecretStr,
    monkeypatch: pytest.MonkeyPatch,
    process: _Process,
) -> None:
    """The cancellation lands in the same loop step as the connection: it must not leak a
    connection, and its reconnect task, that nobody closes."""
    connections: list[AbstractRobustConnection] = []
    tasks: list[asyncio.Task[None]] = []

    async def connect_then_cancel(*args: Any, **kwargs: Any) -> AbstractRobustConnection:
        connection = await connect(*args, **kwargs)
        connections.append(connection)
        tasks[0].cancel()
        return connection

    monkeypatch.setattr(process.module, "connect", connect_then_cancel)
    tasks.append(process.start(with_broker(settings, broker_url), asyncio.Event(), None))

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(tasks[0], timeout=10)

    [connection] = connections
    assert connection.is_closed


@dataclass(frozen=True)
class _Command:
    module: str
    started: bytes
    logged: tuple[str, ...]
    failed: str


WORKER_COMMAND = _Command(
    "di1.workers.main",
    b"worker started",
    ("worker startup step done", "worker started (1 consumers)", "worker stopped"),
    "processing worker failed",
)
RELAY_COMMAND = _Command(
    "di1.workers.outbox_relay",
    b"outbox relay started",
    ("outbox relay started (1 queues declared)", "outbox relay stopped"),
    "outbox relay failed",
)
COMMANDS = pytest.mark.parametrize(
    "command", [WORKER_COMMAND, RELAY_COMMAND], ids=["worker", "relay"]
)


def _environment(settings: Settings, broker_url: str) -> dict[str, str]:
    return os.environ | {
        "DATABASE_URL": settings.database_url.get_secret_value(),
        "RABBITMQ_URL": broker_url,
        "LOG_LEVEL": "INFO",
    }


@COMMANDS
async def test_the_process_stops_cleanly_on_sigterm(
    settings: Settings, broker_url: SecretStr, tmp_path: Path, command: _Command
) -> None:
    """The real composition: the worker runs Processing's startup and its one consumer
    (``processing.run``); the relay declares that queue. Both use the real topology
    (``di1.commands``), whose declarations are idempotent."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        command.module,
        cwd=tmp_path,
        env=_environment(settings, broker_url.get_secret_value()),
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stderr is not None
    try:
        async with asyncio.timeout(30):
            started = b""
            while command.started not in started:
                line = await process.stderr.readline()
                assert line, f"the process exited early: {started.decode()}"
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
    for expected in command.logged:
        assert expected in output
    assert broker_url.get_secret_value() not in output
    assert settings.database_url.get_secret_value() not in output


@COMMANDS
async def test_a_startup_failure_is_logged_and_exits_with_status_1(
    settings: Settings, tmp_path: Path, command: _Command
) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        command.module,
        cwd=tmp_path,
        env=_environment(settings, "amqp://guest:s3cret-pw@127.0.0.1:1/"),
        stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(30):
        _, error_output = await process.communicate()

    output = error_output.decode()
    assert process.returncode == 1, output
    # Run with ``-m``, the module's logger is ``__main__``.
    assert re.search(rf"Z ERROR __main__ {command.failed}\n", output), output
    assert "s3cret-pw" not in output
