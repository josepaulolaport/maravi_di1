"""The run message: one per request, naming it, so the worker starts that request.

Queueing a request saves it QUEUED and writes its run message in the same Unit of Work; the
relay publishes it once the request commits. PostgreSQL stays the source of truth for status and
order: the worker skips a message whose request is no longer QUEUED (cancelled, ended, already
taken by the sweep) or that arrives while a run is RUNNING, and its periodic sweep runs any
QUEUED request whose message was lost, so a lost message only delays its run.
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
