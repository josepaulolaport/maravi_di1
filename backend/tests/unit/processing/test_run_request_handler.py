"""The doorbell handler: it checks the envelope and hands back the drain, to run after the
acknowledgement; the payload is ignored (OQ-46; interfaces.md "Transaction boundaries" 7)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from di1.modules.processing.presentation.messaging.run_request import RunRequestHandler
from di1.platform.messaging.consumer import PermanentMessageError
from di1.platform.messaging.envelope import Envelope
from tests.unit.processing.fakes import FakeUnitOfWork


@dataclass
class FakeProcessor:
    drained: int = 0

    async def drain(self) -> None:
        self.drained += 1


def envelope(
    payload: dict[str, Any], *, message_type: str = "processing.run_request", version: int = 1
) -> Envelope:
    return Envelope(
        message_id=uuid.uuid4(),
        message_type=message_type,
        schema_version=version,
        created_at=datetime(2026, 10, 19, tzinfo=UTC),
        payload=payload,
    )


@pytest.mark.parametrize(
    "payload", [{}, {"request_id": str(uuid.UUID(int=7))}, {"anything": "ignored"}]
)
async def test_the_drain_runs_only_after_the_handler_returns(payload: dict[str, Any]) -> None:
    processor = FakeProcessor()
    uow = FakeUnitOfWork()

    after_ack = await RunRequestHandler(processor)(envelope(payload), uow=uow)

    assert processor.drained == 0
    assert uow.commits == 0  # the consumer commits the inbox record
    assert after_ack is not None
    await after_ack()
    assert processor.drained == 1


@pytest.mark.parametrize(
    "bad",
    [
        envelope({}, message_type="other.command"),
        envelope({}, version=2),
    ],
)
async def test_a_message_that_is_not_a_doorbell_is_dead_lettered(bad: Envelope) -> None:
    processor = FakeProcessor()
    with pytest.raises(PermanentMessageError):
        await RunRequestHandler(processor)(bad, uow=FakeUnitOfWork())
    assert processor.drained == 0
