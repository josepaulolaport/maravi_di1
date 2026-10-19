"""The consumer base: idempotent handling, acknowledged only after the state change commits.

interfaces.md "Transaction boundaries" 7. For each delivery:

1. the body is parsed as an `Envelope`; a body that is not one can never succeed, so it is
   rejected to the dead-letter queue;
2. a Unit of Work opens; the delivery is recorded in ``platform.inbox_messages`` for this
   consumer; the handler runs only for the first delivery of a ``message_id``. The handler
   receives the UoW and may commit it itself (a service called as ``*, uow``); whatever it left
   uncommitted, the inbox record included, is committed after it returns;
3. only then is the delivery acknowledged. If the process dies before the ack, the broker
   redelivers and the inbox turns the redelivery into a no-op;
4. a handler may return work to run after the ack (`AfterAck`): the processing run, whose
   start is the durable state change of step 2 and which then commits date by date in Units of
   Work of its own (plan §7). The ack does not wait for a range that may take longer than the
   broker's consumer timeout. After a crash, the run is recovered when the worker starts again
   (its ``on_startup`` hook resumes after ``progress_date``; one worker, OQ-45), not by a
   redelivery. A failure there is logged, and it stops the runner (`AfterAckRunner.failed`):
   the message is already acknowledged, and work that fails after its ack has left state only
   a restart repairs (a run that could not record its end stays RUNNING, and no later run
   starts while it does). The worker then stops with status 1, Docker restarts it, and its
   startup recovery resumes the run.

The work after the ack runs in an `AfterAckRunner`, one at a time, in a task the process owns,
not in the broker's delivery task: a channel that closes (a broker restart, a missed heartbeat)
does not cancel a run that no longer depends on it. Deliveries are not serialised behind a run:
a command that arrives meanwhile (a duplicate the relay resent) is recorded and acknowledged
at once, and its run, if any, waits its turn in the runner. One active job at a time is the
database's guarantee, not the consumer's. If the ack itself fails after the commit, the work
still runs: the redelivery is an inbox duplicate with no run of its own.

Failures: a `PermanentMessageError` from the handler dead-letters the delivery at once; any
other exception rolls back and, after a pause, returns it to the queue, where the broker
retries it up to the queue's delivery limit (`di1.platform.messaging.topology`). The pause
doubles with each redelivery (``x-delivery-count``), from ``rabbitmq_retry_base_delay_seconds``
up to ``rabbitmq_retry_max_delay_seconds``, so a short outage does not use up the limit. The
delivery stays unacknowledged meanwhile; with a prefetch of 1 the consumer takes nothing else.

The handler holds no business logic of the consumer's: it parses the payload and calls the
module's application service.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractQueue,
    AbstractRobustChannel,
    AbstractRobustConnection,
)
from pydantic import ValidationError

from di1.platform.config import BrokerSettings
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from di1.platform.messaging.envelope import Envelope
from di1.platform.messaging.inbox import CONSUMER_NAME_MAX_LENGTH, record_delivery

logger = logging.getLogger(__name__)

_MAX_BACKOFF_EXPONENT = 30


class PermanentMessageError(Exception):
    """The message can never be handled (an unknown schema version, for instance)."""


type AfterAck = Callable[[], Awaitable[None]]
"""Work a handler hands back to run once its delivery is acknowledged.

What such work must guarantee, since the consumer cannot (interfaces.md "Transaction
boundaries" 4 and 6):

- it may start long after its start committed, behind another run: it re-reads the run's
  state when it begins and ends without writing if the run is no longer its to carry on
  (finished or cancelled meanwhile);
- it bounds every wait (statement and lock timeouts): a run that hangs holds every later run
  of the process behind it.
"""


class AfterAckFailedError(Exception):
    """Work after an ack failed; the worker stops so that its startup recovery repairs the
    state the work left (``__cause__`` is the work's error)."""


class MessageHandler(Protocol):
    async def __call__(self, envelope: Envelope, *, uow: UnitOfWork) -> AfterAck | None: ...


class AfterAckRunner:
    """Runs the work handed back after acks, one at a time and in order, in a task of its own.

    A process shares one runner among its consumers, so it runs one job at a time. `stop`
    cancels the work in progress and drops the waiting work, and any submitted after it: each
    run's start is committed, so the worker recovers it when it starts again (OQ-45).

    A work that fails stops the runner the same way: its error is kept in `failure`, `failed`
    is set, and the waiting and later work is dropped. The worker waits on `failed` and stops
    with an error, since the work is expected to handle every failure it can recover from."""

    def __init__(self) -> None:
        self._waiting: asyncio.Queue[tuple[AfterAck, str]] = asyncio.Queue()
        self._running: asyncio.Task[None] | None = None
        self._stopped = False
        self.failed = asyncio.Event()
        self.failure: Exception | None = None

    def submit(self, work: AfterAck, description: str) -> None:
        """Queue ``work``; a failure is logged with ``description``."""
        if self._stopped:
            logger.warning(
                "%s dropped: the worker is stopping; it is recovered when the worker starts",
                description,
            )
            return
        self._waiting.put_nowait((work, description))
        if self._running is None or self._running.done():
            self._running = asyncio.create_task(self._run_waiting())

    async def _run_waiting(self) -> None:
        while not self._stopped and not self._waiting.empty():
            work, description = self._waiting.get_nowait()
            try:
                await work()
            except Exception as error:
                logger.exception("%s failed; the worker stops", description)
                self.failure = error
                self._stopped = True
                self._drop_waiting()
                self.failed.set()

    async def wait_idle(self) -> None:
        """Return once no work is running or waiting."""
        while self._running is not None and not self._running.done():
            await asyncio.wait({self._running})

    async def stop(self, *, timeout_seconds: float = 5.0) -> None:
        """Drop the waiting work and cancel the work in progress, waiting for it at most
        ``timeout_seconds``. Work submitted afterwards is dropped."""
        self._stopped = True
        self._drop_waiting()
        running, self._running = self._running, None
        if running is None or running.done():
            return
        running.cancel()
        _, pending = await asyncio.wait({running}, timeout=timeout_seconds)
        if pending:
            logger.warning("the work after the ack did not stop in %s s", timeout_seconds)

    def _drop_waiting(self) -> None:
        dropped = self._waiting.qsize()
        while not self._waiting.empty():
            self._waiting.get_nowait()
        if dropped:
            logger.warning(
                "%d waiting runs dropped; they are recovered when the worker starts", dropped
            )


class MessageConsumer:
    def __init__(
        self,
        *,
        consumer_name: str,
        handler: MessageHandler,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        settings: BrokerSettings,
        after_ack: AfterAckRunner | None = None,
    ) -> None:
        """``after_ack`` runs the work handlers hand back; the worker shares one among its
        consumers. Without one, the consumer has a runner of its own."""
        if not 0 < len(consumer_name) <= CONSUMER_NAME_MAX_LENGTH:
            raise ValueError(f"consumer_name must have 1 to {CONSUMER_NAME_MAX_LENGTH} characters")
        self._consumer_name = consumer_name
        self._handler = handler
        self._uow_factory = uow_factory
        self._retry_base_delay = settings.rabbitmq_retry_base_delay_seconds
        self._retry_max_delay = settings.rabbitmq_retry_max_delay_seconds
        self._after_ack = after_ack if after_ack is not None else AfterAckRunner()

    async def start(self, queue: AbstractQueue) -> str:
        """Consume ``queue`` with manual acknowledgements; return the consumer tag."""
        return await queue.consume(self.handle, no_ack=False)

    async def handle(self, message: AbstractIncomingMessage) -> None:
        try:
            envelope = Envelope.from_json(message.body)
        except ValidationError as error:
            logger.error(
                "%s: rejecting a delivery that is not an envelope (message_id %s): %s",
                self._consumer_name,
                message.message_id,
                error.errors(include_input=False),
            )
            await message.reject(requeue=False)
            return

        try:
            after_ack = await self._process(envelope)
        except PermanentMessageError:
            logger.exception(
                "%s: message %s (%s) dead-lettered",
                self._consumer_name,
                envelope.message_id,
                envelope.message_type,
            )
            await message.reject(requeue=False)
            return
        except Exception:
            logger.exception(
                "%s: message %s (%s) failed; returned to the queue",
                self._consumer_name,
                envelope.message_id,
                envelope.message_type,
            )
            await asyncio.sleep(self.retry_delay(message))
            await message.nack(requeue=True)
            return
        try:
            await message.ack()
        except Exception:
            logger.exception(
                "%s: the ack of message %s (%s) failed after its commit",
                self._consumer_name,
                envelope.message_id,
                envelope.message_type,
            )
        if after_ack is not None:
            self._after_ack.submit(
                after_ack,
                f"{self._consumer_name}: the work after the ack of message"
                f" {envelope.message_id} ({envelope.message_type})",
            )

    def retry_delay(self, message: AbstractIncomingMessage) -> float:
        """The pause before a failed delivery returns to the queue."""
        count = message.headers.get("x-delivery-count")
        redeliveries: int = count if isinstance(count, int) and count > 0 else 0
        delay: float = self._retry_base_delay * 2 ** min(redeliveries, _MAX_BACKOFF_EXPONENT)
        return min(delay, self._retry_max_delay)

    async def _process(self, envelope: Envelope) -> AfterAck | None:
        after_ack: AfterAck | None = None
        async with self._uow_factory() as uow:
            first = await record_delivery(
                uow, consumer_name=self._consumer_name, message_id=envelope.message_id
            )
            if first:
                after_ack = await self._handler(envelope, uow=uow)
            else:
                logger.info(
                    "%s: duplicate delivery of message %s ignored",
                    self._consumer_name,
                    envelope.message_id,
                )
            if not uow.committed:
                await uow.commit()
        return after_ack


async def open_consumer_channel(
    connection: AbstractRobustConnection, settings: BrokerSettings
) -> AbstractRobustChannel:
    """A channel with the configured prefetch (unacknowledged deliveries per consumer)."""
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=settings.rabbitmq_prefetch_count)
    return channel
