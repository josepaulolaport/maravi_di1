"""The worker's consumer and its job loop: one job at a time, a message only a hint.

PostgreSQL holds the state and the order of the work; a message only says that work is waiting
(Processing's run message; the handler takes the oldest waiting request, OQ-50 item 2).
Delivery is at least once and a message may be lost, so the worker also sweeps: `JobLoop` calls
the module's ``sweep`` after every job and every ``sweep_interval_seconds``, and the sweep takes
whatever work is still waiting. A lost message only delays its work; a duplicate takes the next
waiting work or finds none.

`JobLoop` runs everything in one task the worker owns, not in aiormq's delivery task, which a
closed channel (a broker restart, a missed heartbeat) cancels. For each delivery,
`MessageConsumer`:

1. parses the body as an `Envelope`; a body that is not one is logged, acknowledged and dropped;
2. while no job runs, offers the handler's start to the loop and waits for it: the handler
   commits the start (a request set RUNNING) and hands back the work that follows (the run),
   or nothing when the message starts nothing;
3. acknowledges the delivery. If the process dies before the ack, the broker delivers it again
   and the handler takes the next waiting work or finds none; the same happens when the
   delivery is cancelled while its start is decided (the loop still finishes that start).

A message that arrives while a job runs is acknowledged at once and starts nothing: its work
stays waiting in the database, and the sweep after the running job takes it. Nothing waits
unacknowledged behind a long job (RabbitMQ's consumer timeout), and there is no redelivery,
backoff or dead-letter queue: a handler that fails (a bad payload, the database down) is logged
and its message acknowledged, since the sweep retries anything still waiting.

The work and the sweep must handle every failure they can recover from. One that escapes stops
the loop with its error (`JobLoop.run` raises it): the work may have left state only a restart
repairs (a run that could not record its end stays RUNNING, and nothing else starts while it
does), so the worker stops with status 1, Docker restarts it, and its startup recovery resumes
the run (OQ-45).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from aio_pika.abc import AbstractRobustChannel, AbstractRobustConnection
from pydantic import ValidationError

from di1.platform.messaging.envelope import Envelope

logger = logging.getLogger(__name__)

PREFETCH_COUNT = 1
"""Unacknowledged deliveries for the worker: it starts one job at a time (OQ-45)."""

type Job = Callable[[], Awaitable[None]]
"""Work the loop runs: what a handler hands back after its start, or the sweep."""


class IncomingMessage(Protocol):
    """What the consumer needs of an aio-pika delivery."""

    @property
    def body(self) -> bytes: ...

    @property
    def message_id(self) -> str | None: ...

    async def ack(self) -> None: ...


class MessageHandler(Protocol):
    async def __call__(self, envelope: Envelope) -> Job | None:
        """Commits the start of the work ``envelope`` asks for and hands back the work that
        follows, or ``None`` when it starts nothing."""
        ...


type Start = Callable[[], Awaitable[Job | None]]


class JobLoop:
    """Runs the worker's jobs one at a time in a task of its own (`run`): the work a message
    starts, then the sweep; and the sweep again every ``sweep_interval_seconds``."""

    def __init__(self, *, sweep: Job, sweep_interval_seconds: float) -> None:
        self._sweep = sweep
        self._interval = sweep_interval_seconds
        self._wake = asyncio.Event()
        self._offered: tuple[Start, asyncio.Future[None], str] | None = None
        self._busy = False

    def offer(self, start: Start, description: str) -> asyncio.Future[None] | None:
        """Hand ``start`` to the loop; the future resolves once it has run (a failure is logged
        with ``description``). ``None`` while a job runs: nothing is started."""
        if self._busy:
            return None
        self._busy = True
        decided = asyncio.get_running_loop().create_future()
        self._offered = (start, decided, description)
        self._wake.set()
        return decided

    async def run(self) -> None:
        """Until cancelled; raises the error of a work or a sweep that fails."""
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            self._wake.clear()
            self._busy = True
            try:
                offered, self._offered = self._offered, None
                if offered is not None:
                    work = await self._start(*offered)
                    if work is not None:
                        await work()
                await self._sweep()
            finally:
                self._busy = False

    @staticmethod
    async def _start(start: Start, decided: asyncio.Future[None], description: str) -> Job | None:
        try:
            return await start()
        except Exception:
            logger.exception("%s failed; the sweep retries its work if still waiting", description)
            return None
        finally:
            if not decided.done():
                decided.set_result(None)


class MessageConsumer:
    def __init__(self, *, name: str, handler: MessageHandler, jobs: JobLoop) -> None:
        self._name = name
        self._handler = handler
        self._jobs = jobs

    async def handle(self, message: IncomingMessage) -> None:
        try:
            envelope = Envelope.from_json(message.body)
        except ValidationError as error:
            logger.error(
                "%s: dropping a delivery that is not an envelope (message_id %s): %s",
                self._name,
                message.message_id,
                error.errors(include_input=False),
            )
            await self._ack(message, "a dropped delivery")
            return

        description = f"{self._name}: message {envelope.message_id} ({envelope.message_type})"
        decided = self._jobs.offer(lambda: self._handler(envelope), description)
        if decided is None:
            logger.info("%s skipped while a job runs; the sweep takes its work", description)
        else:
            await asyncio.shield(decided)
        await self._ack(message, description)

    async def _ack(self, message: IncomingMessage, description: str) -> None:
        try:
            await message.ack()
        except Exception:
            # The delivery comes back: it takes the next waiting work, or finds none.
            logger.exception("%s: the ack failed", description)


async def open_consumer_channel(connection: AbstractRobustConnection) -> AbstractRobustChannel:
    """A channel with the worker's prefetch (`PREFETCH_COUNT`)."""
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=PREFETCH_COUNT)
    return channel
