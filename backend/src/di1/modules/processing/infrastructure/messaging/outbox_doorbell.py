"""`Doorbell` over the platform outbox: the relay publishes it once the request commits."""

from __future__ import annotations

from di1.modules.processing.application.interfaces.doorbell import DOORBELL_MESSAGE_TYPE
from di1.platform.database.unit_of_work import UnitOfWork
from di1.platform.messaging.outbox import add_outbox_message


class OutboxDoorbell:
    """Satisfies `Doorbell`."""

    async def ring(self, *, uow: UnitOfWork) -> None:
        await add_outbox_message(uow, message_type=DOORBELL_MESSAGE_TYPE, payload={})
