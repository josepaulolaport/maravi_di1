"""The ``processing.run_request`` consumer handler: parse the command, claim the run, and hand
the dates back to run after the acknowledgement (interfaces.md "Transaction boundaries" 4, 7).

The claim is the durable state change: it commits in the consumer's Unit of Work with the inbox
record, the delivery is then acknowledged, and only then does the returned callable process the
dates, each in its own Unit of Work. A long range therefore never holds a delivery; a run
interrupted by a crash is resumed when the worker starts again (``recover_interrupted``), not by
redelivery.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from di1.modules.processing.application.services.dispatcher import RUN_REQUEST_MESSAGE_TYPE
from di1.modules.processing.application.services.run_processor import Claim
from di1.platform.database.unit_of_work import UnitOfWork
from di1.platform.messaging.consumer import AfterAck, PermanentMessageError
from di1.platform.messaging.envelope import Envelope

CONSUMER_NAME = "processing.run_request"
SCHEMA_VERSION = 1


class RunRequestPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID


class RangeProcessor(Protocol):
    """What the handler needs of `PortfolioRangeProcessor`."""

    async def claim(self, request_id: UUID, *, uow: UnitOfWork) -> Claim | None: ...

    async def run(self, request_id: UUID) -> None: ...


class RunRequestHandler:
    def __init__(self, processor: RangeProcessor) -> None:
        self._processor = processor

    async def __call__(self, envelope: Envelope, *, uow: UnitOfWork) -> AfterAck | None:
        if envelope.message_type != RUN_REQUEST_MESSAGE_TYPE:
            raise PermanentMessageError(f"unexpected message type {envelope.message_type}")
        if envelope.schema_version != SCHEMA_VERSION:
            raise PermanentMessageError(f"unknown schema version {envelope.schema_version}")
        try:
            payload = RunRequestPayload.model_validate(envelope.payload)
        except ValidationError as error:
            raise PermanentMessageError("invalid run request payload") from error
        claim = await self._processor.claim(payload.request_id, uow=uow)
        if claim is None:
            return None

        async def run_dates() -> None:
            await self._processor.run(claim.request_id)

        return run_dates
