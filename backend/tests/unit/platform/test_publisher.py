"""Every way the broker can fail to confirm a publish is a `PublishFailedError`, so the relay
keeps the outbox row (interfaces.md "Transaction boundaries" 3). The broker paths (no route, a
closed channel) are in the integration tests; these are the ones a live broker cannot be made
to produce on demand.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from aio_pika.abc import AbstractExchange, AbstractRobustChannel
from aio_pika.exceptions import DeliveryError
from pamqp.commands import Basic

from di1.platform.messaging.envelope import Envelope
from di1.platform.messaging.publisher import MessagePublisher, PublishFailedError

ENVELOPE = Envelope(
    message_id=uuid.uuid4(),
    message_type="test.command",
    schema_version=1,
    created_at=datetime(2026, 10, 18, 15, 30, tzinfo=UTC),
    payload={},
)


class _Exchange:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def publish(self, *args: Any, **kwargs: Any) -> None:
        raise self._error


def _publisher(error: BaseException) -> MessagePublisher:
    return MessagePublisher(
        cast(AbstractRobustChannel, None), cast(AbstractExchange, _Exchange(error)), timeout=1
    )


@pytest.mark.parametrize(
    ("error", "described"),
    [
        (DeliveryError(None, Basic.Nack(delivery_tag=1)), "DeliveryError"),
        (TimeoutError(), "TimeoutError"),
        (ConnectionResetError("reset"), "ConnectionResetError"),
    ],
)
async def test_a_nack_a_timeout_or_a_lost_connection_is_a_failed_publish(
    error: BaseException, described: str
) -> None:
    with pytest.raises(PublishFailedError, match=described) as raised:
        await _publisher(error).publish(ENVELOPE)

    assert raised.value.__cause__ is error


async def test_an_unexpected_error_is_not_disguised_as_a_failed_publish() -> None:
    with pytest.raises(ZeroDivisionError):
        await _publisher(ZeroDivisionError()).publish(ENVELOPE)
