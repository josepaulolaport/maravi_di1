"""The dispatcher process: builds Processing's tick with the process's Units of Work and clock,
calls it until stopped, and shuts down cleanly on SIGTERM, even while the database hangs.

interfaces.md "Transaction boundaries" 3 (dispatch, outbox in the same transaction) and
"DI composition" (workers use plain factories); plan §7. The tick here is a fake: the real
one is Processing's.
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.platform.config import DispatcherSettings, Settings
from di1.platform.database.engine import check_connection, create_engine
from di1.platform.messaging.worker import DispatchTick, WorkerResources
from di1.shared.clock import FixedClock
from di1.workers.dispatcher import run_dispatcher
from tests.integration.platform.support import EFFECT, effects, make_envelope

BACKEND = Path(__file__).resolve().parents[3]
FAST = DispatcherSettings(dispatcher_poll_interval_seconds=0.05)


async def test_the_tick_works_through_the_process_units_of_work_until_stopped(
    settings: Settings, engine: AsyncEngine
) -> None:
    """Two queued jobs: each tick commits one dispatch; then nothing is left to dispatch."""
    clock = FixedClock(date(2026, 10, 19))
    queued = [make_envelope().message_id for _ in range(2)]
    given: list[WorkerResources] = []
    idle = asyncio.Event()

    def tick_factory(resources: WorkerResources) -> DispatchTick:
        given.append(resources)

        async def tick() -> uuid.UUID | None:
            if not queued:
                idle.set()
                return None
            async with resources.uow_factory() as uow:
                await uow.session.execute(EFFECT, {"m": queued[0]})
                await uow.commit()
            return queued.pop(0)

        return tick

    expected = list(queued)
    stop = asyncio.Event()
    running = asyncio.create_task(
        run_dispatcher(settings, FAST, tick_factory=tick_factory, stop=stop, clock=clock)
    )
    await asyncio.wait_for(idle.wait(), timeout=10)
    stop.set()
    await asyncio.wait_for(running, timeout=5)

    assert await effects(engine) == expected
    [resources] = given
    assert resources.clock is clock


async def test_a_tick_factory_that_fails_ends_the_dispatcher_with_its_error(
    settings: Settings,
) -> None:
    def broken(resources: WorkerResources) -> DispatchTick:
        raise RuntimeError("not wired")

    with pytest.raises(RuntimeError, match="not wired"):
        await asyncio.wait_for(
            run_dispatcher(settings, FAST, tick_factory=broken, stop=asyncio.Event()), 5
        )


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


async def test_a_stop_while_the_database_hangs_at_startup_ends_the_dispatcher(
    hanging_database_settings: Settings,
) -> None:
    ticks: list[None] = []

    def tick_factory(resources: WorkerResources) -> DispatchTick:
        async def tick() -> None:
            ticks.append(None)

        return tick

    stop = asyncio.Event()
    running = asyncio.create_task(
        run_dispatcher(hanging_database_settings, FAST, tick_factory=tick_factory, stop=stop)
    )
    await asyncio.sleep(0.3)
    assert not running.done()

    stop.set()

    await asyncio.wait_for(running, timeout=2)
    assert ticks == []


async def test_the_dispatcher_process_stops_cleanly_on_sigterm(settings: Settings) -> None:
    environment = os.environ | {
        "DATABASE_URL": settings.database_url.get_secret_value(),
        "DISPATCHER_POLL_INTERVAL_SECONDS": "0.1",
        "LOG_LEVEL": "INFO",
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "di1.workers.dispatcher",
        cwd=BACKEND,
        env=environment,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stderr is not None
    try:
        async with asyncio.timeout(30):
            started = b""
            while b"dispatcher started" not in started:
                line = await process.stderr.readline()
                assert line, f"the dispatcher exited early: {started.decode()}"
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
    assert "dispatch tick failed" not in output  # the composition's tick on a migrated database
    assert "dispatcher started (poll interval 0.1 s)" in output
    assert "dispatcher stopped" in output
    assert settings.database_url.get_secret_value() not in output


async def test_a_dispatcher_startup_failure_is_logged_and_exits_with_status_1() -> None:
    environment = os.environ | {
        "DATABASE_URL": "postgresql+psycopg://u:s3cret-pw@127.0.0.1:1/db",
        "LOG_LEVEL": "INFO",
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "di1.workers.dispatcher",
        cwd=BACKEND,
        env=environment,
        stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(30):
        _, error_output = await process.communicate()

    output = error_output.decode()
    assert process.returncode == 1, output
    # Run with ``-m``, the module's logger is ``__main__``.
    assert re.search(r"Z ERROR __main__ dispatcher failed\n", output), output
    assert "s3cret-pw" not in output


async def test_the_startup_check_gives_up_on_a_database_that_never_answers(
    hanging_database_settings: Settings,
) -> None:
    """Without a stop, a database that hangs must still end the process (exit 1), so the
    restart policy applies."""
    engine = create_engine(hanging_database_settings)
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(check_connection(engine, timeout_seconds=0.3), timeout=5)
    finally:
        await engine.dispose()
