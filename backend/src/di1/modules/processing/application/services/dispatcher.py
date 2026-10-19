"""`ProcessingDispatcher`: hands the next run to the worker, one active run globally
(interfaces.md "Transaction boundaries" 3; plan §7; OQ-5, OQ-45).

`dispatch_next` is the dispatcher process's tick, one transaction. Lock order: it locks the
singleton ``calculation_state``, reads the active run **without** locking it, then locks only QUEUED
rows. A run's end takes the run's row, then its dates, then ``calculation_state`` (it frees the
slot with its end status, OQ-45); since the dispatcher never waits on a run's row while holding
``calculation_state``, the two never form a lock cycle:

- while the active run is DISPATCHED, RUNNING or CANCELLING, nothing is dispatched (there is one
  worker; a run it was processing when it stopped is resumed at its next start, not here);
- otherwise (a run's end has freed the slot; a slot still left on an ended run, from data older
  than that rule, is freed here) the oldest QUEUED run by ``(created_at, id)``
  becomes DISPATCHED and active, with its command written to the outbox in the same transaction
  (the relay publishes it).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from uuid import UUID

from di1.modules.processing.application.interfaces.run_store import RunStore
from di1.modules.processing.public import ProcessingStatus
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.platform.messaging.outbox import add_outbox_message
from di1.shared.clock import Clock

logger = logging.getLogger(__name__)

RUN_REQUEST_MESSAGE_TYPE = "processing.run_request"
"""The dispatch command; payload ``{"request_id": "<uuid>"}``, schema version 1."""

ACTIVE = frozenset(
    {ProcessingStatus.DISPATCHED, ProcessingStatus.RUNNING, ProcessingStatus.CANCELLING}
)


class ProcessingDispatcher:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        store: RunStore,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._store = store
        self._clock = clock

    async def dispatch_next(self) -> UUID | None:
        """Dispatches the oldest queued run and returns its id; ``None`` when a run is active or
        the queue is empty."""
        async with self._uow_factory() as uow:
            now = self._clock.now()
            active_id = await self._store.lock_active_request_id(uow=uow)
            if active_id is not None:
                # A plain read: locking the run's row here would wait on a run's end, which
                # holds that row and waits for calculation_state (a deadlock).
                active = await self._store.get_run(active_id, uow=uow)
                if active is not None and active.status in ACTIVE:
                    return None
                # A run's end frees the slot itself; this frees one still left on an ended run.
                await self._store.set_active_request_id(None, now, uow=uow)

            queued = await self._store.lock_oldest_queued(uow=uow)
            if queued is None:
                # A cancel committed on the oldest row while we waited on its lock: PostgreSQL
                # re-checks that row and returns none, though others may still be queued.
                queued = await self._store.lock_oldest_queued(uow=uow)
            if queued is None:
                await uow.commit()
                return None
            await self._store.save_run(
                replace(
                    queued, status=ProcessingStatus.DISPATCHED, dispatched_at=now, updated_at=now
                ),
                uow=uow,
            )
            await add_outbox_message(
                uow,
                message_type=RUN_REQUEST_MESSAGE_TYPE,
                payload={"request_id": str(queued.id)},
            )
            await self._store.set_active_request_id(queued.id, now, uow=uow)
            await uow.commit()
            logger.info("processing request %s dispatched", queued.id)
            return queued.id
