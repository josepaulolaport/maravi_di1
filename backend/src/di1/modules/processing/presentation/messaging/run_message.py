"""The run message consumer handler: a ``processing.run`` message names one QUEUED request.

The handler checks the envelope and its payload, starts the request (QUEUED → RUNNING, committed
in its own Unit of Work) and hands back its run as work to go on after the acknowledgement
(interfaces.md "Transaction boundaries" 4, 7). A request that does not start (cancelled, ended,
already taken by the sweep, or while a run is RUNNING) hands back nothing: the message is
acknowledged and skipped, and the worker's sweep takes any request still QUEUED.
"""

from __future__ import annotations

from functools import partial
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from di1.modules.processing.application.interfaces.run_messages import RUN_MESSAGE_TYPE
from di1.platform.database.unit_of_work import UnitOfWork
from di1.platform.messaging.consumer import AfterAck, PermanentMessageError
from di1.platform.messaging.envelope import Envelope

SCHEMA_VERSION = 1


class RunPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID


class RunStarter(Protocol):
    """What the handler needs of `PortfolioRangeProcessor`."""

    async def start(self, request_id: UUID) -> bool: ...

    async def run(self, request_id: UUID) -> None: ...


class RunMessageHandler:
    def __init__(self, processor: RunStarter) -> None:
        self._processor = processor

    async def __call__(self, envelope: Envelope, *, uow: UnitOfWork) -> AfterAck | None:
        if envelope.message_type != RUN_MESSAGE_TYPE:
            raise PermanentMessageError(f"unexpected message type {envelope.message_type}")
        if envelope.schema_version != SCHEMA_VERSION:
            raise PermanentMessageError(f"unknown schema version {envelope.schema_version}")
        try:
            request_id = RunPayload.model_validate(envelope.payload).request_id
        except ValidationError as error:
            raise PermanentMessageError("invalid run message payload") from error
        if not await self._processor.start(request_id):
            return None
        return partial(self._processor.run, request_id)
