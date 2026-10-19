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

SIGTERM or SIGINT stops it at any time, even while the broker or the database has not
answered yet. On a stop the worker stops consuming and cancels what is in progress:

- a delivery not yet acknowledged rolls back and, when the connection closes, returns to the
  queue; one that arrives during the stop is left for the next worker the same way;
- the run in progress is cancelled: its open date transaction rolls back, the dates it
  committed stay published, and the run is recovered from its lease by the dispatcher
  (interfaces.md "Transaction boundaries" 6); a run still waiting is dropped and recovered
  the same way.

Then it closes the broker connection and the engine. A failure is logged through the
configured logging and ends the process with status 1.

Until the composition root provides the consumers (``composition.consumers``, integrator),
`main` registers none: the worker consumes nothing, and a command published meanwhile waits in
its queue.
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
) -> None:
    """Consume until ``stop`` is set, then stop consuming, cancel the deliveries and the run in
    progress, and close the broker connection and the engine."""
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
