"""The run message handler: on any run message it takes the oldest QUEUED request and hands back
its run, to go on after the acknowledgement; the message's request_id is for the logs only
(OQ-50 item 2). With nothing QUEUED, or while a run is RUNNING, it starts nothing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from di1.modules.processing.presentation.messaging.run_message import (
    InvalidRunMessageError,
    RunMessageHandler,
)
from di1.platform.messaging.envelope import Envelope

REQUEST_ID = UUID(int=7)


OLDEST = UUID(int=1)


@dataclass
class FakeProcessor:
    queued: list[UUID] = field(default_factory=lambda: [OLDEST])
    takes: int = 0
    ran: list[UUID] = field(default_factory=list)

    async def take_next(self) -> UUID | None:
        self.takes += 1
        return self.queued.pop(0) if self.queued else None

    async def run(self, request_id: UUID) -> None:
        self.ran.append(request_id)


def envelope(
    payload: dict[str, Any], *, message_type: str = "processing.run", version: int = 1
) -> Envelope:
    return Envelope(
        message_id=uuid.uuid4(),
        message_type=message_type,
        schema_version=version,
        created_at=datetime(2026, 10, 19, tzinfo=UTC),
        payload=payload,
    )


async def test_the_oldest_queued_request_is_taken_and_runs_after_the_handler_returns() -> None:
    processor = FakeProcessor()

    after_ack = await RunMessageHandler(processor)(envelope({"request_id": str(REQUEST_ID)}))

    assert processor.takes == 1
    assert processor.ran == []
    assert after_ack is not None
    await after_ack()
    assert processor.ran == [OLDEST]  # not the message's REQUEST_ID


async def test_nothing_taken_hands_back_no_run() -> None:
    processor = FakeProcessor(queued=[])  # nothing QUEUED, or a run is RUNNING

    after_ack = await RunMessageHandler(processor)(envelope({"request_id": str(REQUEST_ID)}))

    assert after_ack is None
    assert processor.takes == 1
    assert processor.ran == []


@pytest.mark.parametrize(
    "bad",
    [
        envelope({"request_id": str(REQUEST_ID)}, message_type="processing.run_request"),
        envelope({"request_id": str(REQUEST_ID)}, version=2),
        envelope({}),
        envelope({"request_id": "not-a-uuid"}),
        envelope({"request_id": str(REQUEST_ID), "extra": 1}),
    ],
)
async def test_a_message_that_is_not_a_run_message_is_refused(bad: Envelope) -> None:
    processor = FakeProcessor()

    with pytest.raises(InvalidRunMessageError):
        await RunMessageHandler(processor)(bad)

    assert processor.takes == 0
