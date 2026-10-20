"""`RunMessages` over the platform outbox: the relay publishes each one once its request
commits."""

from __future__ import annotations

from uuid import UUID

from di1.modules.processing.application.ports import RUN_MESSAGE_TYPE
from di1.platform.database.unit_of_work import UnitOfWork
from di1.platform.messaging.outbox import add_outbox_message


class OutboxRunMessages:
    """Implements `RunMessages` in ``uow``'s transaction."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def publish(self, request_id: UUID) -> None:
        await add_outbox_message(
            self._uow, message_type=RUN_MESSAGE_TYPE, payload={"request_id": str(request_id)}
        )
