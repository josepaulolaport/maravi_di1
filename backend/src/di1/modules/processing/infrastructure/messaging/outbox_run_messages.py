"""`RunMessages` over the platform outbox: the relay publishes each one once its request
commits."""

from __future__ import annotations

from uuid import UUID

from di1.modules.processing.application.interfaces.run_messages import RUN_MESSAGE_TYPE
from di1.platform.database.unit_of_work import UnitOfWork
from di1.platform.messaging.outbox import add_outbox_message


class OutboxRunMessages:
    """Satisfies `RunMessages`."""

    async def publish(self, request_id: UUID, *, uow: UnitOfWork) -> None:
        await add_outbox_message(
            uow, message_type=RUN_MESSAGE_TYPE, payload={"request_id": str(request_id)}
        )
