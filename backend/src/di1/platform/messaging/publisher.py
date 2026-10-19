"""The publisher: a publish returns only after the broker has confirmed the message.

The channel uses publisher confirms (interfaces.md "Transaction boundaries" 3), and every
message is mandatory and persistent: a message no queue accepts, a negative confirm, a timeout
or a lost channel all raise `PublishFailedError`, so the outbox relay keeps the row and retries
instead of losing the command. A failure that is not this message's (a timeout, a closed
channel or connection) is a `BrokerUnavailableError`: every later message would fail the same
way, so the relay stops its batch.
"""

from __future__ import annotations

import aio_pika
from aio_pika.abc import AbstractExchange, AbstractRobustChannel, AbstractRobustConnection
from aio_pika.exceptions import AMQPError, ChannelInvalidStateError, DeliveryError

from di1.platform.config import BrokerSettings
from di1.platform.messaging.envelope import CONTENT_TYPE, Envelope
from di1.platform.messaging.topology import Topology, declare_exchanges


class PublishFailedError(Exception):
    """The broker did not confirm the message; it may or may not have been delivered."""


class BrokerUnavailableError(PublishFailedError):
    """The broker could not be reached or did not answer, whatever the message."""


class MessagePublisher:
    def __init__(
        self, channel: AbstractRobustChannel, exchange: AbstractExchange, *, timeout: float
    ) -> None:
        self._channel = channel
        self._exchange = exchange
        self._timeout = timeout

    @classmethod
    async def create(
        cls,
        connection: AbstractRobustConnection,
        topology: Topology,
        *,
        settings: BrokerSettings,
    ) -> MessagePublisher:
        channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
        exchange = await declare_exchanges(channel, topology)
        return cls(channel, exchange, timeout=settings.rabbitmq_publish_timeout_seconds)

    async def publish(self, envelope: Envelope) -> None:
        message = aio_pika.Message(
            envelope.to_json(),
            content_type=CONTENT_TYPE,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(envelope.message_id),
            type=envelope.message_type,
            timestamp=envelope.created_at,
            headers={"schema_version": envelope.schema_version},
        )
        try:
            await self._exchange.publish(
                message, routing_key=envelope.message_type, mandatory=True, timeout=self._timeout
            )
        except DeliveryError as error:  # a negative confirm or a return: this message only
            raise PublishFailedError(_describe(error)) from error
        except (TimeoutError, AMQPError, ChannelInvalidStateError, ConnectionError) as error:
            raise BrokerUnavailableError(_describe(error)) from error

    async def close(self) -> None:
        await self._channel.close()


def _describe(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"
