"""The doorbell consumer handler (OQ-46): a ``processing.run_request`` message only says "there is
work". The handler checks the envelope and returns the drain as work to run after the
acknowledgement; the drain takes the QUEUED requests oldest first, each in its own Units of Work
(interfaces.md "Transaction boundaries" 4, 7). It reads nothing from the payload, so a duplicate,
late or empty doorbell is harmless: with nothing queued the drain does nothing.
"""

from __future__ import annotations

from typing import Protocol

from di1.modules.processing.application.interfaces.doorbell import DOORBELL_MESSAGE_TYPE
from di1.platform.database.unit_of_work import UnitOfWork
from di1.platform.messaging.consumer import AfterAck, PermanentMessageError
from di1.platform.messaging.envelope import Envelope

CONSUMER_NAME = "processing.run_request"
SCHEMA_VERSION = 1


class QueueDrainer(Protocol):
    """What the handler needs of `PortfolioRangeProcessor`."""

    async def drain(self) -> None: ...


class RunRequestHandler:
    def __init__(self, processor: QueueDrainer) -> None:
        self._processor = processor

    async def __call__(self, envelope: Envelope, *, uow: UnitOfWork) -> AfterAck | None:
        if envelope.message_type != DOORBELL_MESSAGE_TYPE:
            raise PermanentMessageError(f"unexpected message type {envelope.message_type}")
        if envelope.schema_version != SCHEMA_VERSION:
            raise PermanentMessageError(f"unknown schema version {envelope.schema_version}")
        return self._processor.drain
