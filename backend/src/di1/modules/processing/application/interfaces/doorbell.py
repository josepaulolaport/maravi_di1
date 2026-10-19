"""The doorbell: a message that only says "there is work" (OQ-46).

Queueing a request saves it QUEUED and rings the doorbell in the same Unit of Work. The worker,
on any doorbell and at its start, takes the oldest QUEUED request itself; the message names no
request, so a lost, duplicate or late doorbell changes nothing the next one does not fix.
"""

from __future__ import annotations

from typing import Protocol

from di1.platform.database.unit_of_work import UnitOfWork

DOORBELL_MESSAGE_TYPE = "processing.run_request"
"""The message type and queue name, kept from Wave 4 so the wiring is unchanged; the payload is
empty and any content is ignored."""


class Doorbell(Protocol):
    async def ring(self, *, uow: UnitOfWork) -> None:
        """Writes the doorbell in ``uow``'s transaction (the caller commits)."""
        ...
