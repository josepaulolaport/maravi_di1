"""The ``processing.run_request`` handler: it parses the command and claims, and runs the dates
only after the acknowledgement (interfaces.md "Transaction boundaries" 7)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from di1.modules.processing.application.services.run_processor import Claim
from di1.modules.processing.presentation.messaging.run_request import RunRequestHandler
from di1.platform.database.unit_of_work import UnitOfWork
from di1.platform.messaging.consumer import PermanentMessageError
from di1.platform.messaging.envelope import Envelope
from tests.unit.processing.fakes import FakeUnitOfWork

REQUEST_ID = UUID(int=7)
TOKEN = UUID(int=8)


@dataclass
class FakeProcessor:
    claimable: bool = True
    claimed: list[UUID] = field(default_factory=list)
    ran: list[tuple[UUID, UUID]] = field(default_factory=list)

    async def claim(self, request_id: UUID, *, uow: UnitOfWork) -> Claim | None:
        self.claimed.append(request_id)
        return Claim(request_id, TOKEN) if self.claimable else None

    async def run(self, request_id: UUID, token: UUID) -> None:
        self.ran.append((request_id, token))


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


async def test_the_claim_happens_in_the_handler_and_the_dates_after_it_returns() -> None:
    processor = FakeProcessor()
    handler = RunRequestHandler(processor)

    after_ack = await handler(envelope({"request_id": str(REQUEST_ID)}), uow=FakeUnitOfWork())

    assert processor.claimed == [REQUEST_ID]
    assert processor.ran == []
    assert after_ack is not None
    await after_ack()
    assert processor.ran == [(REQUEST_ID, TOKEN)]


async def test_nothing_to_run_when_the_claim_is_refused() -> None:
    handler = RunRequestHandler(FakeProcessor(claimable=False))

    assert await handler(envelope({"request_id": str(REQUEST_ID)}), uow=FakeUnitOfWork()) is None


@pytest.mark.parametrize(
    "bad",
    [
        envelope({"request_id": "not-a-uuid"}),
        envelope({}),
        envelope({"request_id": str(REQUEST_ID), "extra": 1}),
        envelope({"request_id": str(REQUEST_ID)}, message_type="other.command"),
        envelope({"request_id": str(REQUEST_ID)}, version=2),
    ],
)
async def test_a_command_that_can_never_succeed_is_dead_lettered(bad: Envelope) -> None:
    processor = FakeProcessor()
    with pytest.raises(PermanentMessageError):
        await RunRequestHandler(processor)(bad, uow=FakeUnitOfWork())
    assert processor.claimed == []
