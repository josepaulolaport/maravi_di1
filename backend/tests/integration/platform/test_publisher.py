"""A publish returns only once the broker has confirmed it; anything else is a failed publish.

interfaces.md "Transaction boundaries" 3 (the relay publishes with confirms); plan §5 H
(publisher confirms).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import aio_pika
import pytest
from aio_pika.abc import AbstractRobustConnection
from pydantic import SecretStr

from di1.platform.messaging.envelope import Envelope
from di1.platform.messaging.publisher import (
    BrokerUnavailableError,
    MessagePublisher,
    PublishFailedError,
)
from di1.platform.messaging.topology import Topology, declare_queue
from tests.integration.platform.conftest import queue_spec
from tests.integration.platform.support import PUBLISH_TIMEOUT_SECONDS


def _envelope(message_type: str = "test.command") -> Envelope:
    return Envelope(
        message_id=uuid.uuid4(),
        message_type=message_type,
        schema_version=3,
        created_at=datetime(2026, 10, 18, 15, 30, tzinfo=UTC),
        payload={"value": "1.25"},
    )


async def test_a_published_message_is_persistent_and_carries_the_envelope(
    broker: AbstractRobustConnection, broker_url: SecretStr, topology: Topology
) -> None:
    channel = await broker.channel()
    queue = await declare_queue(channel, topology, queue_spec(topology, "test.command"))
    publisher = await MessagePublisher.create(
        broker, topology, confirm_timeout_seconds=PUBLISH_TIMEOUT_SECONDS
    )
    envelope = _envelope()

    await publisher.publish(envelope)

    message = await queue.get(timeout=5)
    assert message is not None
    await message.ack()
    assert Envelope.from_json(message.body) == envelope
    assert json.loads(message.body)["payload"] == {"value": "1.25"}
    assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    assert message.message_id == str(envelope.message_id)
    assert message.type == "test.command"
    assert message.content_type == "application/json"
    assert message.routing_key == "test.command"


async def test_a_message_no_queue_accepts_is_a_failed_publish(
    broker: AbstractRobustConnection, broker_url: SecretStr, topology: Topology
) -> None:
    """An unroutable message would be dropped silently; the relay must keep it and retry."""
    publisher = await MessagePublisher.create(
        broker, topology, confirm_timeout_seconds=PUBLISH_TIMEOUT_SECONDS
    )

    with pytest.raises(PublishFailedError, match="NO_ROUTE") as raised:
        await publisher.publish(_envelope("nobody.listens"))
    assert not isinstance(raised.value, BrokerUnavailableError)  # this message only


async def test_a_closed_channel_is_an_unavailable_broker(
    broker: AbstractRobustConnection, broker_url: SecretStr, topology: Topology
) -> None:
    publisher = await MessagePublisher.create(
        broker, topology, confirm_timeout_seconds=PUBLISH_TIMEOUT_SECONDS
    )
    await publisher.close()

    with pytest.raises(BrokerUnavailableError):  # every later message would fail the same way
        await publisher.publish(_envelope())
