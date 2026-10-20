"""The run message: one per queued request, saying that work is waiting.

Queueing a request saves it QUEUED and writes its run message in the same Unit of Work; the
relay publishes it once the request commits. PostgreSQL stays the source of truth for status and
order: on any run message the worker takes the oldest QUEUED request by ``(created_at, id)``, so
the message's ``request_id`` serves the logs only, and its periodic sweep does the same, so a
lost message only delays a run (OQ-50 item 2).
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from di1.platform.database.unit_of_work import UnitOfWork

RUN_MESSAGE_TYPE = "processing.run"
"""The message type; also the worker's queue name and its routing key."""


class RunMessages(Protocol):
    async def publish(self, request_id: UUID, *, uow: UnitOfWork) -> None:
        """Writes ``request_id``'s run message in ``uow``'s transaction (the caller commits)."""
        ...
