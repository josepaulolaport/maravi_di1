"""`ProcessingDispatcher`: hands the next run to the worker, one active run globally
(interfaces.md "Transaction boundaries" 3; plan §7; OQ-5).

One call is one transaction under a row lock on the singleton ``calculation_state``:

- while a run is active (DISPATCHED, RUNNING or CANCELLING) and its lease holds, nothing is
  dispatched;
- an active run whose lease expired (a crashed worker, or a command never claimed) is
  re-dispatched: its claim token is cleared, which fences out the old worker, and a new command
  is written, so a new claim resumes it after ``progress_date``; once it has been claimed more
  than ``max_recovery_attempts`` times after its first claim, it is not re-dispatched but ends
  FAILED with ``RECOVERY_EXHAUSTED``, its RUNNING dates restored, and the slot goes to the next
  QUEUED run (user decision, 2026-10-19: configurable, default 3);
- otherwise the slot of an ended run is freed and the oldest QUEUED run by
  ``(created_at, id)`` becomes DISPATCHED and active.

The command is written to the outbox in the same transaction; the relay publishes it. A
dispatched command carries a lease too, so a command that is never claimed is sent again.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

from di1.modules.processing.application.interfaces.run_store import RunRecord, RunStore
from di1.modules.processing.application.services.run_processor import (
    DEFAULT_LEASE_SECONDS,
    end_run,
)
from di1.modules.processing.public import ProcessingStatus
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from di1.platform.messaging.outbox import add_outbox_message
from di1.shared.clock import Clock

logger = logging.getLogger(__name__)

RUN_REQUEST_MESSAGE_TYPE = "processing.run_request"
"""The dispatch command; payload ``{"request_id": "<uuid>"}``, schema version 1."""

DEFAULT_MAX_RECOVERY_ATTEMPTS = 3
"""Re-claims allowed after a run's first claim (user decision, 2026-10-19)."""
RECOVERY_EXHAUSTED_CODE = "RECOVERY_EXHAUSTED"
RECOVERY_EXHAUSTED_MESSAGE = "Processamento interrompido após repetidas falhas de recuperação."

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
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        max_recovery_attempts: int = DEFAULT_MAX_RECOVERY_ATTEMPTS,
    ) -> None:
        if max_recovery_attempts < 0:
            raise ValueError("max_recovery_attempts cannot be negative")
        self._uow_factory = uow_factory
        self._store = store
        self._clock = clock
        self._lease = timedelta(seconds=lease_seconds)
        self._max_recovery_attempts = max_recovery_attempts

    async def dispatch_next(self) -> UUID | None:
        """Dispatches or re-dispatches one run and returns its id; ``None`` when nothing was
        sent (a run holds its lease, or the queue is empty)."""
        async with self._uow_factory() as uow:
            now = self._clock.now()
            active_id = await self._store.lock_active_request_id(uow=uow)
            if active_id is not None:
                active = await self._store.get_run(active_id, uow=uow, for_update=True)
                if active is not None and active.request.status in ACTIVE:
                    if active.lease_expires_at is not None and active.lease_expires_at > now:
                        return None
                    if active.attempt_count > self._max_recovery_attempts:
                        await self._exhaust(active, now, uow)
                    else:
                        await self._send(
                            replace(
                                active,
                                request=replace(active.request, updated_at=now),
                                claim_token=None,
                                lease_expires_at=now + self._lease,
                            ),
                            uow,
                        )
                        await uow.commit()
                        logger.warning(
                            "processing request %s re-dispatched (lease expired)", active_id
                        )
                        return active_id
                # The active run has ended (the worker leaves the slot to us): free it.
                await self._store.set_active_request_id(None, now, uow=uow)

            queued = await self._store.lock_oldest_queued(uow=uow)
            if queued is None:
                # A cancel committed on the oldest row while we waited on its lock: PostgreSQL
                # re-checks that row and returns none, though others may still be queued.
                queued = await self._store.lock_oldest_queued(uow=uow)
            if queued is None:
                await uow.commit()
                return None
            await self._send(
                replace(
                    queued,
                    request=replace(
                        queued.request,
                        status=ProcessingStatus.DISPATCHED,
                        dispatched_at=now,
                        updated_at=now,
                    ),
                    claim_token=None,
                    lease_expires_at=now + self._lease,
                ),
                uow,
            )
            await self._store.set_active_request_id(queued.request.id, now, uow=uow)
            await uow.commit()
            logger.info("processing request %s dispatched", queued.request.id)
            return queued.request.id

    async def _exhaust(self, run: RunRecord, now: datetime, uow: UnitOfWork) -> None:
        """Ends a run that kept losing its lease: FAILED with RECOVERY_EXHAUSTED, its dates left
        RUNNING restored; the caller frees the slot in the same transaction."""
        failed = replace(
            run,
            request=replace(
                run.request,
                error_code=RECOVERY_EXHAUSTED_CODE,
                error_message=RECOVERY_EXHAUSTED_MESSAGE,
            ),
        )
        await end_run(self._store, failed, ProcessingStatus.FAILED, now, uow=uow)
        logger.error(
            "processing request %s ended FAILED after %s claims (recovery exhausted)",
            run.request.id,
            run.attempt_count,
        )

    async def _send(self, run: RunRecord, uow: UnitOfWork) -> None:
        await self._store.save_run(run, uow=uow)
        await add_outbox_message(
            uow,
            message_type=RUN_REQUEST_MESSAGE_TYPE,
            payload={"request_id": str(run.request.id)},
        )
