"""The run message consumer handler: one ``processing.run`` message per queued request.

The handler checks the envelope and its payload, then takes the **oldest** QUEUED request by
``(created_at, id)`` (QUEUED → RUNNING, committed in its own Unit of Work) and hands back its
run, which the worker's job loop runs next (interfaces.md "Transaction boundaries" 4, 7); the
message is acknowledged once the take is decided. The message's ``request_id`` is for the logs
only: the relay does not guarantee publication order, so a message never runs its own request
ahead of an older one, and FIFO is unchanged (OQ-50 item 2). With nothing QUEUED, or while a run
is RUNNING, the handler hands back nothing and the message is skipped; a duplicate is harmless
the same way. A message that is not a run message raises `InvalidRunMessageError`, which the
consumer logs before dropping the message.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from di1.modules.processing.application.interfaces.run_messages import RUN_MESSAGE_TYPE
from di1.platform.messaging.consumer import Job
from di1.platform.messaging.envelope import Envelope

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class InvalidRunMessageError(ValueError):
    """The message is not a run message; the consumer logs it and drops it."""


class RunPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID


class RunTaker(Protocol):
    """What the handler needs of `PortfolioRangeProcessor`."""

    async def take_next(self) -> UUID | None: ...

    async def run(self, request_id: UUID) -> None: ...


class RunMessageHandler:
    def __init__(self, processor: RunTaker) -> None:
        self._processor = processor

    async def __call__(self, envelope: Envelope) -> Job | None:
        if envelope.message_type != RUN_MESSAGE_TYPE:
            raise InvalidRunMessageError(f"unexpected message type {envelope.message_type}")
        if envelope.schema_version != SCHEMA_VERSION:
            raise InvalidRunMessageError(f"unknown schema version {envelope.schema_version}")
        try:
            request_id = RunPayload.model_validate(envelope.payload).request_id
        except ValidationError as error:
            raise InvalidRunMessageError("invalid run message payload") from error
        taken = await self._processor.take_next()
        if taken is None:
            logger.info("run message for %s: nothing to take", request_id)
            return None
        logger.info("run message for %s: took request %s", request_id, taken)
        return partial(self._processor.run, taken)
