"""The processing worker process (plan §1 ``workers/main.py``)::

    python -m di1.workers.main

It reads its `Settings` (``DATABASE_URL``, ``RABBITMQ_URL``, ``WORKER_SWEEP_INTERVAL_SECONDS``,
``LOG_LEVEL``, ...; a missing ``RABBITMQ_URL`` fails it at startup), configures logging once,
builds its consumers with the composition root's `ConsumerFactory`
(`di1.platform.messaging.worker`), declares each one's queue and consumes it through the
consumer base (`di1.platform.messaging.consumer`) until SIGTERM or SIGINT. Everything is built
with plain factories, not FastAPI dependencies (interfaces.md "DI composition").

The handlers are Processing's: the worker holds no business logic. Its one `JobLoop` runs one
job at a time, in a task of the worker's own, so a dropped broker connection does not cancel a
run: the start a message asks for (acknowledged once it is decided), the run that follows, then
the sweep, which also runs every ``WORKER_SWEEP_INTERVAL_SECONDS``, so a request whose message
was lost still runs. Startup checks that PostgreSQL answers, so a wrong database fails the
process instead of every message.

The system runs exactly one worker and no dispatcher process (OQ-45, OQ-46). Before it
consumes, the worker awaits its startup hook once (`di1.platform.messaging.worker.StartupHook`):
Processing's recovery, under which a run left RUNNING by a stopped or crashed worker resumes
after its ``progress_date``, then one sweep. A failing hook ends the process with status 1,
before anything is consumed.

SIGTERM or SIGINT stops it at any time, even while the broker or the database has not
answered yet. On a stop the worker stops consuming and cancels what is in progress:

- a delivery not yet acknowledged returns to the queue when the connection closes; one that
  arrives during the stop is left for the next worker the same way;
- the job in progress is cancelled: a start not yet committed rolls back; a run's open date
  transaction rolls back, the dates it committed stay published, and the startup hook resumes
  it on the next start (one worker, OQ-45);
- a startup hook in progress is cancelled, and runs again on the next start.

A job or a sweep that fails (a run that could not record its end, so stays RUNNING and blocks
the queue) stops the worker the same way, then raises `JobFailedError`: the process exits with
status 1, Docker restarts it, and the startup hook resumes the run (OQ-45).

Then it closes the broker connection and the engine. A failure is logged through the
configured logging and ends the process with status 1.

With ``HEARTBEAT_FILE`` set (`di1.platform.config.Settings`), a task of the event loop
touches that file every ``HEARTBEAT_INTERVAL_SECONDS`` while the process runs; compose.yaml's
health check (`di1.workers.healthcheck`) reads its age.

`main` takes the consumers, the startup hook and the sweep from the composition root
(``composition.consumers``): Processing's run message consumer, its recovery then sweep, and its
sweep.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Sequence

from aio_pika.abc import AbstractIncomingMessage, AbstractQueue, AbstractRobustConnection

from di1.composition import consumers as composition
from di1.platform.clock import SystemClock
from di1.platform.config import Settings
from di1.platform.database.engine import check_connection, create_worker_engine
from di1.platform.database.session import create_session_factory
from di1.platform.database.unit_of_work import unit_of_work_factory
from di1.platform.messaging.connection import connect
from di1.platform.messaging.consumer import (
    JobLoop,
    MessageConsumer,
    open_consumer_channel,
)
from di1.platform.messaging.topology import Topology, declare_queue
from di1.platform.messaging.worker import (
    ConsumerFactory,
    ConsumerRegistration,
    StartupHook,
    SweepFactory,
    WorkerResources,
)
from di1.platform.observability.heartbeat import Heartbeat, beat_until_stopped
from di1.shared.clock import Clock
from di1.workers.lifecycle import (
    CLOSE_TIMEOUT_SECONDS,
    close_connection,
    run_process,
    unless_stopped,
)

logger = logging.getLogger(__name__)

CONNECTION_NAME = "di1-processing-worker"


class JobFailedError(Exception):
    """A job or a sweep failed; the worker stops so that its startup recovery repairs the state
    it left (``__cause__`` is the job's error)."""


async def _no_sweep() -> None:
    return None


async def run_worker(
    settings: Settings,
    *,
    consumers: ConsumerFactory,
    stop: asyncio.Event,
    topology: Topology | None = None,
    clock: Clock | None = None,
    on_startup: StartupHook | None = None,
    sweep: SweepFactory | None = None,
    heartbeat: Heartbeat | None = None,
) -> None:
    """`_serve`, with ``heartbeat`` beaten every ``heartbeat_interval_seconds`` from a task of
    the event loop, from the start (the startup step included) until the worker stops: a
    fresh file shows the loop is responsive (compose.yaml's health check)."""
    if heartbeat is None:
        await _serve(
            settings,
            consumers=consumers,
            stop=stop,
            topology=topology,
            clock=clock,
            on_startup=on_startup,
            sweep=sweep,
        )
        return
    stopped = asyncio.Event()
    beating = asyncio.create_task(
        beat_until_stopped(heartbeat, stopped, interval_seconds=settings.heartbeat_interval_seconds)
    )
    try:
        await _serve(
            settings,
            consumers=consumers,
            stop=stop,
            topology=topology,
            clock=clock,
            on_startup=on_startup,
            sweep=sweep,
        )
    finally:
        stopped.set()
        await beating


async def _serve(
    settings: Settings,
    *,
    consumers: ConsumerFactory,
    stop: asyncio.Event,
    topology: Topology | None,
    clock: Clock | None,
    on_startup: StartupHook | None,
    sweep: SweepFactory | None,
) -> None:
    """Run ``on_startup`` once, then run the job loop and consume until ``stop`` is set or a job
    fails; then stop consuming, cancel the deliveries and the job in progress, and close the
    broker connection and the engine. A failed job is then raised as `JobFailedError`."""
    broker_url = settings.broker_url()
    topology = topology if topology is not None else Topology()
    engine = create_worker_engine(settings)
    try:
        resources = WorkerResources(
            uow_factory=unit_of_work_factory(create_session_factory(engine)),
            clock=clock if clock is not None else SystemClock(),
        )
        registrations = tuple(consumers(resources))
        if not registrations:
            logger.warning("no consumer is configured: the worker consumes nothing")
        await unless_stopped(check_connection(engine), stop)
        if stop.is_set():
            logger.info("worker stopped before the database answered")
            return
        if on_startup is not None:
            if not await _run_startup_step(on_startup(resources), stop):
                logger.info("worker stopped during its startup step")
                return
            logger.info("worker startup step done")
        jobs = JobLoop(
            sweep=sweep(resources) if sweep is not None else _no_sweep,
            sweep_interval_seconds=settings.worker_sweep_interval_seconds,
        )
        loop = asyncio.create_task(jobs.run())
        try:
            connection = await unless_stopped(
                connect(broker_url, connection_name=CONNECTION_NAME),
                stop,
                discard=close_connection,
            )
            if connection is None:
                logger.info("worker stopped before the broker answered")
                return
            running = _RunningConsumers(jobs)
            try:
                started = await unless_stopped(
                    running.start(connection, topology, registrations), stop
                )
                if started is None:
                    logger.info("worker stopped before the broker answered")
                    return
                logger.info("worker started (%d consumers)", len(registrations))
                await _until_stopped_or_done(stop, loop)
            finally:
                await running.stop()
                await close_connection(connection)
        finally:
            failure = await _stop_loop(loop)
    finally:
        await engine.dispose()
    if failure is not None:
        logger.error("worker stopped: a job failed")
        raise JobFailedError("a job failed") from failure
    logger.info("worker stopped")


async def _until_stopped_or_done(stop: asyncio.Event, loop: asyncio.Task[None]) -> None:
    waiting = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({waiting, loop}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiting.cancel()


async def _stop_loop(loop: asyncio.Task[None]) -> BaseException | None:
    """Cancel the job loop, waiting for it at most `CLOSE_TIMEOUT_SECONDS`: a job that ignores
    its cancellation is left behind with a warning. Return the error it ended with, if any."""
    if not loop.done():
        loop.cancel()
        _, pending = await asyncio.wait({loop}, timeout=CLOSE_TIMEOUT_SECONDS)
        if pending:
            logger.warning("the job in progress did not stop in %s s", CLOSE_TIMEOUT_SECONDS)
            return None
    if loop.cancelled():
        return None
    return loop.exception()


async def _run_startup_step(step: Awaitable[None], stop: asyncio.Event) -> bool:
    """Await ``step``; return `False` if ``stop`` came first. The step is then cancelled and
    waited for at most `CLOSE_TIMEOUT_SECONDS`: a step that ignores its cancellation is left
    behind with a warning rather than holding the stop until Docker's SIGKILL. A failure of the
    step is raised."""
    running = asyncio.ensure_future(step)
    stopping = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({running, stopping}, return_when=asyncio.FIRST_COMPLETED)
    except BaseException:
        running.cancel()
        raise
    finally:
        stopping.cancel()
    if running.done():
        running.result()
        return not stop.is_set()
    running.cancel()
    _, pending = await asyncio.wait({running}, timeout=CLOSE_TIMEOUT_SECONDS)
    if pending:
        logger.warning("the startup step did not stop in %s s", CLOSE_TIMEOUT_SECONDS)
    return False


class _RunningConsumers:
    """The started consumers and the deliveries they are handling (aiormq runs each delivery in
    a task of its own); they share the worker's job loop."""

    def __init__(self, jobs: JobLoop) -> None:
        self._jobs = jobs
        self._consuming: list[tuple[AbstractQueue, str]] = []
        self._in_progress: set[asyncio.Task[object]] = set()
        self._stopping = False

    async def start(
        self,
        connection: AbstractRobustConnection,
        topology: Topology,
        registrations: Sequence[ConsumerRegistration],
    ) -> bool:
        """Declare each queue and consume it. aio-pika waits for these answers without a
        timeout, so the caller runs this under the stop."""
        if not registrations:
            return True
        channel = await open_consumer_channel(connection)
        for registration in registrations:
            queue = await declare_queue(channel, topology, registration.queue)
            consumer = MessageConsumer(
                name=registration.name, handler=registration.handler, jobs=self._jobs
            )
            tag = await queue.consume(self._tracked(consumer), no_ack=False)
            self._consuming.append((queue, tag))
        return True

    def _tracked(
        self, consumer: MessageConsumer
    ) -> Callable[[AbstractIncomingMessage], Awaitable[None]]:
        async def on_message(message: AbstractIncomingMessage) -> None:
            if self._stopping:
                return  # left unsettled: it returns to the queue when the connection closes
            task = asyncio.current_task()
            assert task is not None
            self._in_progress.add(task)
            try:
                await consumer.handle(message)
            finally:
                self._in_progress.discard(task)

        return on_message

    async def stop(self) -> None:
        """Stop the deliveries and cancel the ones in progress. A broker that does not answer
        the cancel does not hold the shutdown longer than `CLOSE_TIMEOUT_SECONDS` per queue."""
        self._stopping = True
        for queue, tag in self._consuming:
            try:
                await asyncio.wait_for(queue.cancel(tag), timeout=CLOSE_TIMEOUT_SECONDS)
            except Exception:
                logger.warning("could not stop consuming %s", queue.name, exc_info=True)
        self._consuming.clear()
        tasks = set(self._in_progress)
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        _, pending = await asyncio.wait(tasks, timeout=CLOSE_TIMEOUT_SECONDS)
        if pending:
            logger.warning(
                "%d deliveries did not stop in %s s", len(pending), CLOSE_TIMEOUT_SECONDS
            )
        for task in tasks - pending:
            with contextlib.suppress(asyncio.CancelledError):
                task.exception()


def main() -> None:
    def run(settings: Settings, stop: asyncio.Event) -> Awaitable[None]:
        path = settings.heartbeat_file
        return run_worker(
            settings,
            consumers=composition.consumers,
            on_startup=composition.processing_startup,
            sweep=composition.processing_sweep,
            stop=stop,
            heartbeat=Heartbeat(path) if path is not None else None,
        )

    run_process("processing worker", run, logger)


if __name__ == "__main__":
    main()
