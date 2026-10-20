"""The processing worker process: consumes its registered queues through the consumer base,
runs one job at a time in its job loop (a message's start, its work, then the sweep; and the
sweep on every interval), and shuts down cleanly on SIGTERM, during startup and during work.

interfaces.md "Transaction boundaries" 7 (at-least-once; ACK once the start is decided) and "DI
composition" (plain factories); plan §7. One worker only (user decision): a run
left RUNNING resumes at the worker's next start, through ``on_startup``. The handler here is a
fake: the real one is Processing's.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from aio_pika.abc import AbstractRobustConnection
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.platform.config import Settings
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.platform.messaging.connection import connect
from di1.platform.messaging.consumer import Job
from di1.platform.messaging.envelope import Envelope
from di1.platform.messaging.publisher import MessagePublisher
from di1.platform.messaging.topology import QueueSpec, Topology, declare_queue
from di1.platform.messaging.worker import ConsumerRegistration, WorkerResources
from di1.platform.observability.heartbeat import Heartbeat
from di1.shared.clock import FixedClock
from di1.workers import lifecycle
from di1.workers import main as worker
from di1.workers.main import JobFailedError, run_worker
from tests.integration.platform.conftest import queue_spec
from tests.integration.platform.support import (
    EFFECT,
    PUBLISH_TIMEOUT_SECONDS,
    close_connections,
    effects,
    eventually,
    make_envelope,
    with_broker,
    worker_parts,
)


@dataclass
class _Run:
    """The fake processing handler: the start is the effect row; ``hold_before_ack`` blocks
    before the start commits, ``hold_after_ack`` blocks the run after the ack. The factory
    gives it the worker's Units of Work."""

    hold_before_ack: bool = False
    hold_after_ack: bool = False
    fail_after_ack: bool = False
    claimed: list[Envelope] = field(default_factory=list)
    ran: list[Envelope] = field(default_factory=list)
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    uow_factory: Callable[[], SqlAlchemyUnitOfWork] | None = None

    async def __call__(self, envelope: Envelope) -> Job:
        self.claimed.append(envelope)
        assert self.uow_factory is not None
        async with self.uow_factory() as uow:
            await uow.session.execute(EFFECT, {"m": envelope.message_id})
            if self.hold_before_ack:
                await self._hold()
            await uow.commit()

        async def run() -> None:
            if self.hold_after_ack and not self.ran:
                await self._hold()
            if self.fail_after_ack:
                raise RuntimeError("the end of the run was not recorded")
            self.ran.append(envelope)

        return run

    async def _hold(self) -> None:
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


def _consumers(
    spec: QueueSpec, handler: _Run, given: list[WorkerResources] | None = None
) -> Callable[[WorkerResources], Sequence[ConsumerRegistration]]:
    def factory(resources: WorkerResources) -> Sequence[ConsumerRegistration]:
        if given is not None:
            given.append(resources)
        handler.uow_factory = resources.uow_factory
        return [ConsumerRegistration(queue=spec, name="worker", handler=handler)]

    return factory


async def _ready_messages(broker: AbstractRobustConnection, queue_name: str) -> int:
    channel = await broker.channel()
    try:
        queue = await channel.declare_queue(queue_name, passive=True)
        return queue.declaration_result.message_count or 0
    finally:
        await channel.close()


@pytest.fixture
async def publisher(
    broker: AbstractRobustConnection, broker_url: SecretStr, topology: Topology
) -> MessagePublisher:
    return await MessagePublisher.create(
        broker, topology, confirm_timeout_seconds=PUBLISH_TIMEOUT_SECONDS
    )


async def test_the_worker_consumes_its_queue_and_runs_the_work_after_the_ack(
    settings: Settings,
    engine: AsyncEngine,
    broker: AbstractRobustConnection,
    broker_url: SecretStr,
    topology: Topology,
    publisher: MessagePublisher,
) -> None:
    """The worker declares its own queue, so it consumes a command published after it started;
    the factory receives the process's clock."""
    spec = queue_spec(topology, "test.command")
    handler = _Run()
    given: list[WorkerResources] = []
    clock = FixedClock(date(2026, 10, 19))
    stop = asyncio.Event()
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, broker_url),
            build=worker_parts(consumers=_consumers(spec, handler, given)),
            stop=stop,
            topology=topology,
            clock=clock,
        )
    )
    envelope = make_envelope()
    await eventually(lambda: _is_consumed(broker, spec.name))

    await publisher.publish(envelope)

    await eventually(lambda: handler.ran == [envelope])
    stop.set()
    await asyncio.wait_for(running, timeout=10)
    assert await effects(engine) == [envelope.message_id]
    assert await _ready_messages(broker, spec.name) == 0
    [resources] = given
    assert resources.clock is clock


async def test_the_worker_beats_its_heartbeat_from_its_start_until_it_stops(
    settings: Settings,
    broker_url: SecretStr,
    topology: Topology,
    tmp_path: Path,
) -> None:
    """The heartbeat shows the event loop is responsive (compose.yaml's health check), also
    during the startup step: recovery may run a long range before the worker consumes."""
    path = tmp_path / "worker.heartbeat"
    release = asyncio.Event()

    async def recover(resources: WorkerResources) -> None:
        await release.wait()

    stop = asyncio.Event()
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, broker_url, heartbeat_interval_seconds=0.05),
            build=worker_parts(consumers=lambda resources: [], on_startup=recover),
            stop=stop,
            topology=topology,
            heartbeat=Heartbeat(path),
        )
    )
    await eventually(path.exists)
    os.utime(path, (1000.0, 1000.0))
    await eventually(lambda: path.stat().st_mtime > 1000.0)  # still beating, mid-startup

    release.set()
    stop.set()
    await asyncio.wait_for(running, timeout=10)
    os.utime(path, (1000.0, 1000.0))
    await asyncio.sleep(0.2)
    assert path.stat().st_mtime == 1000.0  # stopped with the worker


async def _is_consumed(broker: AbstractRobustConnection, name: str) -> bool:
    """Whether the worker consumes the queue. A queue that merely exists is not enough: the
    worker declares it, then binds it to its message types, then consumes it, and a publish
    between the declaration and the binding is refused (NO_ROUTE). Once the queue has a
    consumer, its bindings are in place."""
    channel = await broker.channel()
    try:
        queue = await channel.declare_queue(name, passive=True)
        return (queue.declaration_result.consumer_count or 0) > 0
    except Exception:
        return False
    finally:
        if not channel.is_closed:
            await channel.close()


async def test_a_stop_during_the_run_after_the_ack_cancels_it_and_the_message_stays_acked(
    settings: Settings,
    engine: AsyncEngine,
    broker: AbstractRobustConnection,
    broker_url: SecretStr,
    topology: Topology,
    publisher: MessagePublisher,
) -> None:
    """SIGTERM mid-range: the run is cancelled (its open date transaction rolls back), the claim
    stays committed and the message is not redelivered: the run resumes at the next start."""
    spec = queue_spec(topology, "test.command")
    handler = _Run(hold_after_ack=True)
    stop = asyncio.Event()
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, broker_url),
            build=worker_parts(consumers=_consumers(spec, handler)),
            stop=stop,
            topology=topology,
        )
    )
    envelope = make_envelope()
    await eventually(lambda: _is_consumed(broker, spec.name))
    await publisher.publish(envelope)
    await asyncio.wait_for(handler.entered.wait(), timeout=10)

    stop.set()

    await asyncio.wait_for(running, timeout=10)
    assert handler.cancelled.is_set()
    assert handler.ran == []
    assert await effects(engine) == [envelope.message_id]
    assert await _ready_messages(broker, spec.name) == 0


async def test_a_failure_after_the_ack_ends_the_worker_with_an_error(
    settings: Settings,
    engine: AsyncEngine,
    broker: AbstractRobustConnection,
    broker_url: SecretStr,
    topology: Topology,
    publisher: MessagePublisher,
) -> None:
    """Work after the ack that fails left state only a restart repairs: a run that could not
    record its end stays RUNNING, and no later run starts while it does. The worker stops with
    an error (the process exits 1 and Docker restarts it) instead of idling with a stuck queue;
    its startup recovery then resumes the run (OQ-45). The message stays acknowledged."""
    spec = queue_spec(topology, "test.command")
    handler = _Run(fail_after_ack=True)
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, broker_url),
            build=worker_parts(consumers=_consumers(spec, handler)),
            stop=asyncio.Event(),
            topology=topology,
        )
    )
    envelope = make_envelope()
    await eventually(lambda: _is_consumed(broker, spec.name))

    await publisher.publish(envelope)

    with pytest.raises(JobFailedError) as raised:
        await asyncio.wait_for(running, timeout=15)
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert await effects(engine) == [envelope.message_id]
    assert await _ready_messages(broker, spec.name) == 0


async def test_a_stop_before_the_ack_rolls_back_and_returns_the_message(
    settings: Settings,
    engine: AsyncEngine,
    broker: AbstractRobustConnection,
    broker_url: SecretStr,
    topology: Topology,
    publisher: MessagePublisher,
) -> None:
    """SIGTERM while the claim is still open: nothing is committed and the broker keeps the
    command for the next worker (ACK only after the durable state change)."""
    spec = queue_spec(topology, "test.command")
    handler = _Run(hold_before_ack=True)
    stop = asyncio.Event()
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, broker_url),
            build=worker_parts(consumers=_consumers(spec, handler)),
            stop=stop,
            topology=topology,
        )
    )
    envelope = make_envelope()
    await eventually(lambda: _is_consumed(broker, spec.name))
    await publisher.publish(envelope)
    await asyncio.wait_for(handler.entered.wait(), timeout=10)

    stop.set()

    await asyncio.wait_for(running, timeout=10)
    assert handler.cancelled.is_set()
    assert await effects(engine) == []
    await eventually(lambda: _has_ready(broker, spec.name, 1))


async def _has_ready(broker: AbstractRobustConnection, name: str, count: int) -> bool:
    return await _ready_messages(broker, name) == count


async def test_a_dropped_broker_connection_does_not_cancel_the_run(
    settings: Settings,
    engine: AsyncEngine,
    broker: AbstractRobustConnection,
    broker_url: SecretStr,
    topology: Topology,
    publisher: MessagePublisher,
    management_url: str,
) -> None:
    """The run no longer depends on the broker once its claim is acked: a broker restart or a
    missed heartbeat closes the channel, and the run goes on to its end."""
    spec = queue_spec(topology, "test.command")
    handler = _Run(hold_after_ack=True)
    stop = asyncio.Event()
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, broker_url),
            build=worker_parts(consumers=_consumers(spec, handler)),
            stop=stop,
            topology=topology,
        )
    )
    envelope = make_envelope()
    await eventually(lambda: _is_consumed(broker, spec.name))
    await publisher.publish(envelope)
    await asyncio.wait_for(handler.entered.wait(), timeout=10)

    assert await close_connections(management_url, worker.CONNECTION_NAME) >= 1
    await asyncio.sleep(0.5)
    assert not handler.cancelled.is_set()
    handler.release.set()

    await eventually(lambda: handler.ran == [envelope])
    stop.set()
    await asyncio.wait_for(running, timeout=10)
    assert handler.claimed == [envelope]


async def test_a_message_arriving_during_a_run_is_acked_at_once_and_starts_nothing(
    settings: Settings,
    engine: AsyncEngine,
    broker: AbstractRobustConnection,
    broker_url: SecretStr,
    topology: Topology,
    publisher: MessagePublisher,
) -> None:
    """The second message is not left unacked behind the first run (RabbitMQ's consumer
    timeout) and starts nothing: its work stays waiting in the database, and the sweep after the
    first run takes it."""
    spec = queue_spec(topology, "test.command")
    handler = _Run(hold_after_ack=True)
    sweeps: list[int] = []

    def sweep(resources: WorkerResources) -> Job:
        async def run() -> None:
            sweeps.append(len(handler.ran))

        return run

    stop = asyncio.Event()
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, broker_url),
            build=worker_parts(consumers=_consumers(spec, handler), sweep=sweep),
            stop=stop,
            topology=topology,
        )
    )
    first, second = make_envelope(), make_envelope()
    await eventually(lambda: _is_consumed(broker, spec.name))
    await publisher.publish(first)
    await asyncio.wait_for(handler.entered.wait(), timeout=10)

    await publisher.publish(second)

    await asyncio.sleep(0.3)
    assert handler.claimed == [first]
    assert sweeps == []
    handler.release.set()
    await eventually(lambda: sweeps == [1])  # the sweep right after the run
    stop.set()
    await asyncio.wait_for(running, timeout=10)
    assert handler.claimed == [first]
    assert await effects(engine) == [first.message_id]
    assert await _ready_messages(broker, spec.name) == 0  # both acknowledged


async def test_the_sweep_runs_on_every_interval_without_any_message(
    settings: Settings,
    broker_url: SecretStr,
    topology: Topology,
) -> None:
    """A request whose message was lost still runs: the sweep does not wait for a message."""
    sweeps: list[WorkerResources] = []

    def sweep(resources: WorkerResources) -> Job:
        async def run() -> None:
            sweeps.append(resources)

        return run

    stop = asyncio.Event()
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, broker_url, worker_sweep_interval_seconds=0.05),
            build=worker_parts(consumers=lambda resources: [], sweep=sweep),
            stop=stop,
            topology=topology,
        )
    )

    await eventually(lambda: len(sweeps) >= 3)
    stop.set()
    await asyncio.wait_for(running, timeout=10)


async def test_a_failing_sweep_ends_the_worker_with_an_error(
    settings: Settings,
    broker_url: SecretStr,
    topology: Topology,
) -> None:
    """The process then exits 1 and Docker restarts it; the startup recovery repairs whatever
    the sweep's run left (OQ-45)."""

    def sweep(resources: WorkerResources) -> Job:
        async def run() -> None:
            raise RuntimeError("the sweep's run could not record its end")

        return run

    with pytest.raises(JobFailedError) as raised:
        await asyncio.wait_for(
            run_worker(
                with_broker(settings, broker_url, worker_sweep_interval_seconds=0.05),
                build=worker_parts(consumers=lambda resources: [], sweep=sweep),
                stop=asyncio.Event(),
                topology=topology,
            ),
            timeout=10,
        )
    assert isinstance(raised.value.__cause__, RuntimeError)


@pytest.fixture
async def hanging_database_settings() -> AsyncIterator[Settings]:
    """A TCP server that accepts connections and never answers: a database that hangs."""

    async def hold(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read()
        writer.close()

    server = await asyncio.start_server(hold, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield Settings(
            database_url=SecretStr(f"postgresql+psycopg://u:s3cret-pw@127.0.0.1:{port}/db")
        )
    finally:
        server.close()


async def test_a_stop_while_the_database_hangs_at_startup_ends_the_worker(
    hanging_database_settings: Settings, broker_url: SecretStr
) -> None:
    stop = asyncio.Event()
    running = asyncio.create_task(
        run_worker(
            with_broker(hanging_database_settings, broker_url),
            build=worker_parts(consumers=lambda resources: ()),
            stop=stop,
        )
    )
    await asyncio.sleep(0.3)
    assert not running.done()

    stop.set()

    await asyncio.wait_for(running, timeout=2)


async def test_an_unreachable_database_ends_the_worker_before_it_consumes(
    broker_url: SecretStr,
) -> None:
    """Otherwise every message would fail its start and be dropped."""
    unreachable = Settings(
        database_url=SecretStr("postgresql+psycopg://u:s3cret-pw@127.0.0.1:1/db")
    )

    with pytest.raises(OperationalError, match="port 1 failed"):
        await asyncio.wait_for(
            run_worker(
                with_broker(unreachable, broker_url),
                build=worker_parts(consumers=lambda resources: ()),
                stop=asyncio.Event(),
            ),
            timeout=10,
        )


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


async def test_a_stop_while_connecting_to_the_broker_ends_the_worker(
    settings: Settings, hanging_broker_url: str
) -> None:
    stop = asyncio.Event()
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, SecretStr(hanging_broker_url)),
            build=worker_parts(consumers=lambda resources: ()),
            stop=stop,
        )
    )
    await asyncio.sleep(0.3)
    assert not running.done()

    stop.set()

    await asyncio.wait_for(running, timeout=2)


async def _hang(*args: object, **kwargs: object) -> None:
    await asyncio.Event().wait()


async def test_a_stop_while_the_broker_stalls_after_connecting_ends_the_worker(
    settings: Settings,
    broker_url: SecretStr,
    topology: Topology,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The broker accepted the connection but never answers the queue declaration: aio-pika
    waits without a timeout, so the startup must observe the stop as well."""
    stalled = asyncio.Event()

    async def stall(*args: object, **kwargs: object) -> None:
        stalled.set()
        await _hang()

    monkeypatch.setattr(worker, "declare_queue", stall)
    connections: list[AbstractRobustConnection] = []

    async def recording_connect(*args: Any, **kwargs: Any) -> AbstractRobustConnection:
        connection = await connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(worker, "connect", recording_connect)
    stop = asyncio.Event()
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, broker_url),
            build=worker_parts(consumers=_consumers(queue_spec(topology, "test.command"), _Run())),
            stop=stop,
            topology=topology,
        )
    )
    await asyncio.wait_for(stalled.wait(), timeout=10)

    stop.set()

    await asyncio.wait_for(running, timeout=2)
    [connection] = connections
    assert connection.is_closed


async def test_a_connection_made_as_the_worker_is_cancelled_is_closed(
    settings: Settings, broker_url: SecretStr, monkeypatch: pytest.MonkeyPatch
) -> None:
    connections: list[AbstractRobustConnection] = []
    running: asyncio.Task[None] | None = None

    async def connect_then_cancel(*args: Any, **kwargs: Any) -> AbstractRobustConnection:
        connection = await connect(*args, **kwargs)
        connections.append(connection)
        assert running is not None
        running.cancel()
        return connection

    monkeypatch.setattr(worker, "connect", connect_then_cancel)
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, broker_url),
            build=worker_parts(consumers=lambda resources: ()),
            stop=asyncio.Event(),
        )
    )

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, timeout=10)

    [connection] = connections
    assert connection.is_closed


async def test_the_worker_process_stops_cleanly_on_sigterm(
    settings: Settings, broker_url: SecretStr, tmp_path: Path
) -> None:
    """The process runs the composition's startup step and its one consumer
    (``processing.run``), then stops on SIGTERM."""
    environment = os.environ | {
        "DATABASE_URL": settings.database_url.get_secret_value(),
        "RABBITMQ_URL": broker_url.get_secret_value(),
        "LOG_LEVEL": "INFO",
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "di1.workers.main",
        cwd=tmp_path,
        env=environment,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stderr is not None
    try:
        async with asyncio.timeout(30):
            started = b""
            while b"worker started" not in started:
                line = await process.stderr.readline()
                assert line, f"the worker exited early: {started.decode()}"
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
    assert "worker startup step done" in output
    assert "worker started (1 consumers)" in output
    assert "worker stopped" in output
    assert broker_url.get_secret_value() not in output
    assert settings.database_url.get_secret_value() not in output


async def test_a_worker_startup_failure_is_logged_and_exits_with_status_1(
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
        "di1.workers.main",
        cwd=tmp_path,
        env=environment,
        stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(30):
        _, error_output = await process.communicate()

    output = error_output.decode()
    assert process.returncode == 1, output
    # Run with ``-m``, the module's logger is ``__main__``.
    assert re.search(r"Z ERROR __main__ processing worker failed\n", output), output
    assert "s3cret-pw" not in output


# The startup hook: Processing's recovery (a run left RUNNING resumes after its
# ``progress_date``), run once before the worker consumes. One worker only (user decision).


async def test_the_startup_hook_runs_once_before_the_first_delivery(
    settings: Settings,
    engine: AsyncEngine,
    broker: AbstractRobustConnection,
    broker_url: SecretStr,
    topology: Topology,
    publisher: MessagePublisher,
) -> None:
    """A command already queued waits until the recovery has committed."""
    spec = queue_spec(topology, "test.command")
    channel = await broker.channel()
    await declare_queue(channel, topology, spec)
    await channel.close()
    queued = make_envelope()
    await publisher.publish(queued)
    recovered = make_envelope().message_id
    order: list[str] = []
    release = asyncio.Event()

    async def recover(resources: WorkerResources) -> None:
        order.append("startup")
        await release.wait()
        async with resources.uow_factory() as uow:
            await uow.session.execute(EFFECT, {"m": recovered})
            await uow.commit()

    class _Claim(_Run):
        async def __call__(self, envelope: Envelope) -> Job:
            order.append("claim")
            return await super().__call__(envelope)

    handler = _Claim()
    stop = asyncio.Event()
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, broker_url),
            build=worker_parts(consumers=_consumers(spec, handler), on_startup=recover),
            stop=stop,
            topology=topology,
        )
    )
    await eventually(lambda: order == ["startup"])
    await asyncio.sleep(0.3)
    assert order == ["startup"]

    release.set()

    await eventually(lambda: handler.ran == [queued])
    stop.set()
    await asyncio.wait_for(running, timeout=10)
    assert order == ["startup", "claim"]
    assert await effects(engine) == [recovered, queued.message_id]


async def _queued_before_start(
    broker: AbstractRobustConnection,
    broker_url: SecretStr,
    topology: Topology,
    publisher: MessagePublisher,
) -> QueueSpec:
    """A command waiting in the worker's queue before the worker starts."""
    spec = queue_spec(topology, "test.command")
    channel = await broker.channel()
    await declare_queue(channel, topology, spec)
    await channel.close()
    envelope = make_envelope()
    await publisher.publish(envelope)
    return spec


async def test_a_failing_startup_hook_ends_the_worker_before_it_consumes(
    settings: Settings,
    engine: AsyncEngine,
    broker: AbstractRobustConnection,
    broker_url: SecretStr,
    topology: Topology,
    publisher: MessagePublisher,
) -> None:
    """The process then exits 1 (`di1.workers.lifecycle.run_process`) and Docker restarts it.
    The hook takes a moment before failing, so a worker that consumed early would claim."""
    spec = await _queued_before_start(broker, broker_url, topology, publisher)
    handler = _Run()

    async def recover(resources: WorkerResources) -> None:
        await asyncio.sleep(0.3)
        raise RuntimeError("recovery failed")

    with pytest.raises(RuntimeError, match="recovery failed"):
        await asyncio.wait_for(
            run_worker(
                with_broker(settings, broker_url),
                build=worker_parts(consumers=_consumers(spec, handler), on_startup=recover),
                stop=asyncio.Event(),
                topology=topology,
            ),
            timeout=10,
        )
    assert handler.claimed == []
    assert await effects(engine) == []
    assert await _ready_messages(broker, spec.name) == 1


async def test_a_stop_during_the_startup_hook_cancels_it_and_consumes_nothing(
    settings: Settings,
    engine: AsyncEngine,
    broker: AbstractRobustConnection,
    broker_url: SecretStr,
    topology: Topology,
    publisher: MessagePublisher,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A long recovery must not keep SIGTERM waiting; it runs again on the next start."""
    caplog.set_level(logging.INFO, logger=worker.__name__)
    spec = await _queued_before_start(broker, broker_url, topology, publisher)
    handler = _Run()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def recover(resources: WorkerResources) -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    stop = asyncio.Event()
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, broker_url),
            build=worker_parts(consumers=_consumers(spec, handler), on_startup=recover),
            stop=stop,
            topology=topology,
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=10)

    stop.set()

    await asyncio.wait_for(running, timeout=2)
    assert cancelled.is_set()
    assert handler.claimed == []
    assert await _ready_messages(broker, spec.name) == 1
    assert "worker stopped during its startup step" in caplog.text


async def test_a_startup_hook_that_ignores_its_cancellation_does_not_hold_the_stop(
    settings: Settings,
    broker_url: SecretStr,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A recovery that swallows the cancellation (a retry around a commit) is waited for at
    most `CLOSE_TIMEOUT_SECONDS`, then left behind with a warning, before Docker's SIGKILL."""
    monkeypatch.setattr(worker, "CLOSE_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(lifecycle, "CLOSE_TIMEOUT_SECONDS", 0.3)
    entered = asyncio.Event()
    finish = asyncio.Event()

    async def recover(resources: WorkerResources) -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await finish.wait()

    stop = asyncio.Event()
    running = asyncio.create_task(
        run_worker(
            with_broker(settings, broker_url),
            build=worker_parts(consumers=lambda resources: (), on_startup=recover),
            stop=stop,
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=10)

    stop.set()

    await asyncio.wait_for(running, timeout=3)
    assert "a startup step did not stop in 0.3 s" in caplog.text
    finish.set()
