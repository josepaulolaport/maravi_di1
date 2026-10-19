"""The processing worker process (plan §1 ``workers/main.py``)::

    python -m di1.workers.main

It reads ``DATABASE_URL``, ``RABBITMQ_URL`` and the optional broker and ``LOG_LEVEL`` settings
(`di1.platform.config`), configures logging once, builds its consumers with the composition
root's `ConsumerFactory` (`di1.platform.messaging.worker`), declares each one's queue and
consumes it through the consumer base (`di1.platform.messaging.consumer`) until SIGTERM or
SIGINT. Everything is built with plain factories, not FastAPI dependencies (interfaces.md "DI
composition").

The handlers are Processing's: the worker holds no business logic. Delivery is at least once,
acknowledged after the handler's state change commits (the claim), and the run goes on after
the ack (`di1.platform.messaging.consumer.AfterAck`) in the worker's one `AfterAckRunner`,
shared by its consumers: one run at a time, in a task of the worker's own, so a dropped broker
connection does not cancel it. Startup checks that PostgreSQL answers, so a wrong database
fails the process instead of every command.

The system runs exactly one worker (user decision). Before it consumes, the worker awaits its
startup hook once (`di1.platform.messaging.worker.StartupHook`): Processing's recovery, under
which a run left RUNNING by a stopped or crashed worker resumes after its ``progress_date``.
A failing hook ends the process with status 1, before anything is consumed.

SIGTERM or SIGINT stops it at any time, even while the broker or the database has not
answered yet. On a stop the worker stops consuming and cancels what is in progress:

- a delivery not yet acknowledged rolls back and, when the connection closes, returns to the
  queue; one that arrives during the stop is left for the next worker the same way;
- the run in progress is cancelled: its open date transaction rolls back, the dates it
  committed stay published, and the startup hook resumes it on the next start (one worker,
  OQ-45; interfaces.md still describes recovery by lease and re-dispatch, pending its update
  by the integrator); a run still waiting is dropped and resumed the same way;
- a startup hook in progress is cancelled, and runs again on the next start.

Then it closes the broker connection and the engine. A failure is logged through the
configured logging and ends the process with status 1.

Until the composition root provides the consumers and the startup hook
(``composition.consumers``, integrator), `main` registers none and runs no recovery: the
worker consumes nothing, a command published meanwhile waits in its queue, and a run left
RUNNING stays so.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from aio_pika.abc import AbstractIncomingMessage, AbstractQueue, AbstractRobustConnection

from di1.platform.clock import SystemClock
from di1.platform.config import BrokerSettings, Settings, get_broker_settings, get_settings
from di1.platform.database.engine import check_connection, create_engine
from di1.platform.database.session import create_session_factory
from di1.platform.database.unit_of_work import unit_of_work_factory
from di1.platform.messaging.connection import connect
from di1.platform.messaging.consumer import (
    AfterAckRunner,
    MessageConsumer,
    open_consumer_channel,
)
from di1.platform.messaging.topology import Topology, declare_queue
from di1.platform.messaging.worker import (
    ConsumerFactory,
    ConsumerRegistration,
    StartupHook,
    WorkerResources,
)
from di1.shared.clock import Clock
from di1.workers.lifecycle import (
    CLOSE_TIMEOUT_SECONDS,
    close_connection,
    run_process,
    unless_stopped,
)

logger = logging.getLogger(__name__)

CONNECTION_NAME = "di1-processing-worker"


async def run_worker(
    settings: Settings,
    broker_settings: BrokerSettings,
    *,
    consumers: ConsumerFactory,
    stop: asyncio.Event,
    topology: Topology | None = None,
    clock: Clock | None = None,
    on_startup: StartupHook | None = None,
) -> None:
    """Run ``on_startup`` once, then consume until ``stop`` is set; then stop consuming, cancel
    the deliveries and the run in progress, and close the broker connection and the engine."""
    topology = topology if topology is not None else Topology()
    engine = create_engine(settings)
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
        connection = await unless_stopped(
            connect(broker_settings, connection_name=CONNECTION_NAME),
            stop,
            discard=close_connection,
        )
        if connection is None:
            logger.info("worker stopped before the broker answered")
            return
        running = _RunningConsumers()
        try:
            started = await unless_stopped(
                running.start(connection, topology, registrations, resources, broker_settings),
                stop,
            )
            if started is None:
                logger.info("worker stopped before the broker answered")
                return
            logger.info("worker started (%d consumers)", len(registrations))
            await stop.wait()
        finally:
            await running.stop()
            await close_connection(connection)
    finally:
        await engine.dispose()
    logger.info("worker stopped")


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


@dataclass
class _RunningConsumers:
    """The started consumers, the deliveries they are handling (aiormq runs each delivery in a
    task of its own) and the runner of the work after their acks."""

    consuming: list[tuple[AbstractQueue, str]] = field(default_factory=list)
    in_progress: set[asyncio.Task[object]] = field(default_factory=set)
    after_ack: AfterAckRunner = field(default_factory=AfterAckRunner)
    stopping: bool = False

    async def start(
        self,
        connection: AbstractRobustConnection,
        topology: Topology,
        registrations: Sequence[ConsumerRegistration],
        resources: WorkerResources,
        broker_settings: BrokerSettings,
    ) -> bool:
        """Declare each queue and consume it. aio-pika waits for these answers without a
        timeout, so the caller runs this under the stop."""
        if not registrations:
            return True
        channel = await open_consumer_channel(connection, broker_settings)
        for registration in registrations:
            queue = await declare_queue(
                channel, topology, registration.queue, settings=broker_settings
            )
            consumer = MessageConsumer(
                consumer_name=registration.consumer_name,
                handler=registration.handler,
                uow_factory=resources.uow_factory,
                settings=broker_settings,
                after_ack=self.after_ack,
            )
            tag = await queue.consume(self._tracked(consumer), no_ack=False)
            self.consuming.append((queue, tag))
        return True

    def _tracked(
        self, consumer: MessageConsumer
    ) -> Callable[[AbstractIncomingMessage], Awaitable[None]]:
        async def on_message(message: AbstractIncomingMessage) -> None:
            if self.stopping:
                return  # left unsettled: it returns to the queue when the connection closes
            task = asyncio.current_task()
            assert task is not None
            self.in_progress.add(task)
            try:
                await consumer.handle(message)
            finally:
                self.in_progress.discard(task)

        return on_message

    async def stop(self) -> None:
        """Stop the deliveries, cancel the ones in progress, then stop the runner. A broker that
        does not answer the cancel, or work that ignores its cancellation, does not hold the
        shutdown longer than `CLOSE_TIMEOUT_SECONDS` each."""
        self.stopping = True
        for queue, tag in self.consuming:
            try:
                await asyncio.wait_for(queue.cancel(tag), timeout=CLOSE_TIMEOUT_SECONDS)
            except Exception:
                logger.warning("could not stop consuming %s", queue.name, exc_info=True)
        self.consuming.clear()
        await self._cancel_deliveries()
        await self.after_ack.stop(timeout_seconds=CLOSE_TIMEOUT_SECONDS)

    async def _cancel_deliveries(self) -> None:
        tasks = set(self.in_progress)
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


def _no_consumers(resources: WorkerResources) -> Sequence[ConsumerRegistration]:
    """Until Processing's handler is wired: no consumer."""
    return ()


def main() -> None:
    run_process(
        "processing worker",
        lambda stop: run_worker(
            get_settings(), get_broker_settings(), consumers=_no_consumers, stop=stop
        ),
        logger,
    )


if __name__ == "__main__":
    main()
