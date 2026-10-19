"""The consumer base: idempotent handling, acknowledged only after the state change commits.

interfaces.md "Transaction boundaries" 7. For each delivery:

1. the body is parsed as an `Envelope`; a body that is not one can never succeed, so it is
   rejected to the dead-letter queue;
2. a Unit of Work opens; the delivery is recorded in ``platform.inbox_messages`` for this
   consumer; the handler runs only for the first delivery of a ``message_id``. The handler
   receives the UoW and may commit it itself (a service called as ``*, uow``); whatever it left
   uncommitted, the inbox record included, is committed after it returns;
3. only then is the delivery acknowledged. If the process dies before the ack, the broker
   redelivers and the inbox turns the redelivery into a no-op.

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
from collections.abc import Callable
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


class MessageHandler(Protocol):
    async def __call__(self, envelope: Envelope, *, uow: UnitOfWork) -> None: ...


class MessageConsumer:
    def __init__(
        self,
        *,
        consumer_name: str,
        handler: MessageHandler,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        settings: BrokerSettings,
    ) -> None:
        if not 0 < len(consumer_name) <= CONSUMER_NAME_MAX_LENGTH:
            raise ValueError(f"consumer_name must have 1 to {CONSUMER_NAME_MAX_LENGTH} characters")
        self._consumer_name = consumer_name
        self._handler = handler
        self._uow_factory = uow_factory
        self._retry_base_delay = settings.rabbitmq_retry_base_delay_seconds
        self._retry_max_delay = settings.rabbitmq_retry_max_delay_seconds

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
            await self._process(envelope)
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
        await message.ack()

    def retry_delay(self, message: AbstractIncomingMessage) -> float:
        """The pause before a failed delivery returns to the queue."""
        count = message.headers.get("x-delivery-count")
        redeliveries: int = count if isinstance(count, int) and count > 0 else 0
        delay: float = self._retry_base_delay * 2 ** min(redeliveries, _MAX_BACKOFF_EXPONENT)
        return min(delay, self._retry_max_delay)

    async def _process(self, envelope: Envelope) -> None:
        async with self._uow_factory() as uow:
            first = await record_delivery(
                uow, consumer_name=self._consumer_name, message_id=envelope.message_id
            )
            if first:
                await self._handler(envelope, uow=uow)
            else:
                logger.info(
                    "%s: duplicate delivery of message %s ignored",
                    self._consumer_name,
                    envelope.message_id,
                )
            if not uow.committed:
                await uow.commit()


async def open_consumer_channel(
    connection: AbstractRobustConnection, settings: BrokerSettings
) -> AbstractRobustChannel:
    """A channel with the configured prefetch (unacknowledged deliveries per consumer)."""
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=settings.rabbitmq_prefetch_count)
    return channel
