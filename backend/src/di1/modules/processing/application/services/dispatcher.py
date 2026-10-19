"""`ProcessingDispatcher`: hands the next run to the worker, one active run globally, and
resumes the run a worker restart interrupted (interfaces.md "Transaction boundaries" 3; plan §7;
OQ-5; user decisions of 2026-10-19: exactly one processing worker, a recovery cap).

Every call is one transaction under a row lock on the singleton ``calculation_state``, which is
always taken before a run's row (the worker never takes it), so the two never deadlock.

- `dispatch_next`, the dispatcher process's tick: while a run is active (DISPATCHED, RUNNING or
  CANCELLING) nothing is dispatched; otherwise the slot of an ended run is freed and the oldest
  QUEUED run by ``(created_at, id)`` becomes DISPATCHED and active, with its command written to
  the outbox in the same transaction (the relay publishes it).
- `recover_interrupted`, called once when the worker starts: there is one worker, so an active
  run at that moment was interrupted (a crash, a restart, or a command lost after the outbox
  publish). Its command is written again, and the new claim resumes it after ``progress_date``.
  Once it has been claimed more than ``max_recovery_attempts`` times after its first claim, it
  ends FAILED with ``RECOVERY_EXHAUSTED`` instead, its RUNNING dates restored, and the slot is
  freed for the next QUEUED run (configurable, default 3).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from di1.modules.processing.application.interfaces.run_store import RunRecord, RunStore
from di1.modules.processing.application.services.run_processor import end_run
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
        max_recovery_attempts: int = DEFAULT_MAX_RECOVERY_ATTEMPTS,
    ) -> None:
        if max_recovery_attempts < 0:
            raise ValueError("max_recovery_attempts cannot be negative")
        self._uow_factory = uow_factory
        self._store = store
        self._clock = clock
        self._max_recovery_attempts = max_recovery_attempts

    async def dispatch_next(self) -> UUID | None:
        """Dispatches the oldest queued run and returns its id; ``None`` when a run is active or
        the queue is empty."""
        async with self._uow_factory() as uow:
            now = self._clock.now()
            if await self._active_run(uow) is not None:
                return None
            dispatched = await self._dispatch_oldest_queued(now, uow)
            await uow.commit()
            return dispatched

    async def recover_interrupted(self) -> UUID | None:
        """At the worker's startup: re-sends the command of the run left active and returns its
        id, or, past the recovery cap, ends it FAILED (``RECOVERY_EXHAUSTED``) and dispatches
        the next queued run, whose id it returns. ``None`` when nothing was active."""
        async with self._uow_factory() as uow:
            now = self._clock.now()
            active = await self._active_run(uow)
            if active is None:
                await uow.commit()
                return None
            if active.attempt_count <= self._max_recovery_attempts:
                await self._send(
                    replace(active, request=replace(active.request, updated_at=now)), uow
                )
                await uow.commit()
                logger.warning(
                    "processing request %s interrupted (status %s): command sent again",
                    active.request.id,
                    active.request.status,
                )
                return active.request.id
            await self._exhaust(active, now, uow)
            await self._store.set_active_request_id(None, now, uow=uow)
            dispatched = await self._dispatch_oldest_queued(now, uow)
            await uow.commit()
            return dispatched

    async def _active_run(self, uow: UnitOfWork) -> RunRecord | None:
        """Locks ``calculation_state``, then the active run; frees the slot of an ended run (the
        worker leaves that to the dispatcher)."""
        active_id = await self._store.lock_active_request_id(uow=uow)
        if active_id is None:
            return None
        active = await self._store.get_run(active_id, uow=uow, for_update=True)
        if active is not None and active.request.status in ACTIVE:
            return active
        await self._store.set_active_request_id(None, self._clock.now(), uow=uow)
        return None

    async def _dispatch_oldest_queued(self, now: datetime, uow: UnitOfWork) -> UUID | None:
        queued = await self._store.lock_oldest_queued(uow=uow)
        if queued is None:
            # A cancel committed on the oldest row while we waited on its lock: PostgreSQL
            # re-checks that row and returns none, though others may still be queued.
            queued = await self._store.lock_oldest_queued(uow=uow)
        if queued is None:
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
            ),
            uow,
        )
        await self._store.set_active_request_id(queued.request.id, now, uow=uow)
        logger.info("processing request %s dispatched", queued.request.id)
        return queued.request.id

    async def _exhaust(self, run: RunRecord, now: datetime, uow: UnitOfWork) -> None:
        """Ends a run that keeps being interrupted: FAILED with RECOVERY_EXHAUSTED, its dates
        left RUNNING restored."""
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
