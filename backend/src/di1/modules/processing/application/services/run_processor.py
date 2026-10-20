"""`PortfolioRangeProcessor`: the worker's run of one request, one date per transaction
(interfaces.md "Processing", "Recovery at worker start" and "Transaction boundaries" 4 to 6;
OQ-11, OQ-23, OQ-26, OQ-31, OQ-36, OQ-37, OQ-38, OQ-40, OQ-44, OQ-45).

The system runs exactly one processing worker (OQ-45), which handles one run at a time: there is
no lease, claim token, fencing, recovery cap, dispatcher or active slot (OQ-46). Queueing a
request publishes one run message; on any run message the worker takes the oldest QUEUED request
by ``(created_at, id)`` (`take_next`) and runs it, and a periodic sweep (`sweep`) does the same
until none is left, so a request whose message was lost still runs, only later (OQ-50 item 2).
Each step is its own Unit of Work under a row lock on the run's ``requests`` row, with its
ports built on that Unit of Work (`RunPorts`):

1. **take** (`take_next`, on a run message or in `sweep`): under the queue's advisory lock and
   only while no run is RUNNING, the oldest QUEUED request is locked and set RUNNING with
   ``started_at``; with nothing QUEUED it is a no-op;
2. per date D, in calendar order, from ``start_date`` or the day after ``progress_date``:
   a. a short transaction checks the cancel flag: a cancel ends the run CANCELLED between
      dates;
   b. D's transaction locks the ``date_status`` rows of D−1 and D, and runs each live chain in
      its own SAVEPOINT, positions first: the predecessor rule, the calculators, the writer. A
      chain that fails rolls back to its savepoint and gets FAILED on D; the other chain still
      commits (OQ-36, OQ-40). The date's statuses, issues and ``progress_date`` commit with it;
   c. a failure outside every savepoint (a lock timeout, say) rolls back all of D; a short
      transaction then sets D FAILED for every live chain and ends the run FAILED;
3. the end: COMPLETED, COMPLETED_WITH_ISSUES or FAILED.

No date is ever written RUNNING (OQ-50 item 4): each date goes from its old status straight to
its new one in its own transaction (2b or 2c), so a run that stops leaves every date as it was or
as it committed it, and nothing is restored. A read shows "Processando" for the active run's
current date (`application.services.date_status_reader`).

**A step that cannot be recorded.** A run left RUNNING blocks the queue: no later run is
taken while it is. An error in D's transaction outside every chain's savepoint always takes
step 2c, whatever its kind (a lock timeout there fails D). Any other error of the run's steps
(2a, 2c, 3, and the run's start) is handled by its kind
(`di1.platform.database.errors.is_transient`):

- a transient database error (a dropped connection, a timeout) may clear. The end of a run
  (step 3) and the failure of a date (step 2c) are retried after short pauses
  (``end_retry_delays``); if they still fail, or another step fails that way, the error
  escapes `run`: the worker process stops with status 1 and restarts
  (`di1.platform.messaging.consumer.AfterAckRunner`), and recovery at its start finishes the
  run. A step that committed before its error finds the run ended on the retry and writes
  nothing (`RunEndedError`);
- any other error (a bug, a CHECK violation) would recur on every retry and every restart, a
  crash loop with the queue blocked behind the run. It is not retried: the run ends FAILED
  with ``PROCESSING_ERROR`` in a fresh short transaction (`_abort`), the dates it committed
  kept, and the worker goes on with the queue. Only if that write
  fails too does the error escape for a restart.

A known limit: a bug that breaks that FAILED end too also breaks recovery at the worker start,
which nothing catches, so it would still loop on restarts; so would a non-transient error
classified transient (`is_transient` lists its limits).

**Recovery at worker start** (`recover_at_startup`, before the worker consumes): the run left
RUNNING was interrupted. A run with a cancel request ends CANCELLED before any date; any other is
run to its end, after ``progress_date`` (from ``start_date`` when NULL). Then the queue is
swept.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import date, datetime
from functools import partial
from uuid import UUID

from di1.modules.processing.application.ports import RunPorts
from di1.modules.processing.application.services.predecessor import read_predecessor
from di1.modules.processing.application.services.run_chains import (
    process_cash_day,
    process_positions_day,
)
from di1.modules.processing.domain.date_status import Chain, ChainStatus, DateStatus
from di1.modules.processing.domain.issues import IssueRecord
from di1.modules.processing.domain.predecessor import PredecessorState
from di1.modules.processing.domain.runs import (
    PREDECESSOR_MESSAGE,
    TECHNICAL_ERROR_MESSAGE,
    ProcessingErrorCode,
    ProcessingRequest,
    ProcessingStatus,
)
from di1.platform.database.errors import is_transient
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.calendar import ONE_DAY
from di1.shared.clock import Clock

logger = logging.getLogger(__name__)

END_RETRY_DELAYS = (0.5, 2.0, 5.0)
"""Pauses, in seconds, before each retry of a run's end or of a date's failure."""

UnitOfWorkFactory = Callable[[], AbstractAsyncContextManager[UnitOfWork]]
PortsFactory = Callable[[UnitOfWork], RunPorts]


class RunEndedError(Exception):
    """The run is no longer running: the worker stops without writing."""


@dataclass(frozen=True, slots=True)
class ChainFailure:
    chain: Chain
    code: ProcessingErrorCode
    message: str


def first_failure(failures: list[ChainFailure]) -> ChainFailure:
    """The failure the run keeps: positions when both chains fail on the same date (OQ-36 item
    5: POSITIONS_PREDECESSOR_MISSING, or the positions chain's error)."""
    for failure in failures:
        if failure.chain is Chain.POSITIONS:
            return failure
    return failures[0]


def ended(request: ProcessingRequest, status: ProcessingStatus, now: datetime) -> ProcessingRequest:
    """The run ended with ``status``; its dates keep what they committed (OQ-50 item 4)."""
    return replace(request, status=status, finished_at=now, updated_at=now)


class PortfolioRangeProcessor:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        ports_for: PortsFactory,
        clock: Clock,
        end_retry_delays: Sequence[float] = END_RETRY_DELAYS,
    ) -> None:
        self._uow_factory = uow_factory
        self._ports_for = ports_for
        self._clock = clock
        self._end_retry_delays = tuple(end_retry_delays)

    # --- 1. take a queued request -------------------------------------------------------

    async def sweep(self) -> None:
        """Runs the QUEUED requests one after the other, oldest ``(created_at, id)`` first, until
        none is left: the worker's periodic sweep, so a request whose run message was lost still
        runs. With nothing queued, or while a run is RUNNING, it does nothing."""
        while (request_id := await self.take_next()) is not None:
            await self.run(request_id)

    async def take_next(self) -> UUID | None:
        """Locks the oldest QUEUED request and sets it RUNNING, in one transaction. ``None`` only
        when none is queued (a cancel and a take on the same row: whichever commits first wins),
        or while a run is still RUNNING: one stopped by an error it could not record waits for
        the worker's next start, so two runs never overlap. The queue lock makes the check and
        the take one atomic step, even for two concurrent takes."""
        async with self._uow_factory() as uow:
            requests = self._ports_for(uow).requests
            await requests.lock_queue()
            if await requests.lock_running():
                await uow.commit()
                return None
            while (queued := await requests.lock_oldest_queued()) is None:
                # Defensive: a cancel may commit on the oldest row while we wait on its lock.
                # With this query's plan PostgreSQL then moves on to the next row; should a plan
                # ever return no row instead, select again until a row is locked or none is
                # queued at all. No test can force that case on this query.
                if not await requests.has_queued():
                    await uow.commit()
                    return None
            now = self._clock.now()
            await requests.save(
                replace(queued, status=ProcessingStatus.RUNNING, started_at=now, updated_at=now)
            )
            await uow.commit()
            logger.info("processing request %s started", queued.id)
            return queued.id

    # --- recovery at worker start (OQ-45) -------------------------------------------------

    async def recover_at_startup(self) -> None:
        """Called once when the worker starts, before it consumes: the run left RUNNING was
        interrupted. A run with a cancel request ends CANCELLED before any date; any other is run
        to its end here, after ``progress_date``. Then the queue is swept, so a request whose run
        message was lost runs too. Idempotent: a second call finds nothing to recover or run."""
        async with self._uow_factory() as uow:
            requests = self._ports_for(uow).requests
            now = self._clock.now()
            to_resume: list[UUID] = []
            for request in await requests.lock_running():
                if request.cancel_requested_at is not None:
                    await requests.save(ended(request, ProcessingStatus.CANCELLED, now))
                    logger.info("processing request %s cancelled at worker start", request.id)
                    continue
                await requests.save(replace(request, updated_at=now))
                to_resume.append(request.id)
            await uow.commit()
        for request_id in to_resume:
            logger.warning("processing request %s resumed at worker start", request_id)
            await self.run(request_id)
        await self.sweep()

    # --- 2. the dates ----------------------------------------------------------------------

    async def run(self, request_id: UUID) -> None:
        """Processes the claimed run to its end. A transient error that escapes left the run
        RUNNING: the worker must restart, and recovery at its start resumes the run after
        ``progress_date``. Any other error ends the run FAILED (`_abort`)."""
        try:
            await self._run(request_id)
        except RunEndedError:
            logger.info("processing request %s has already ended", request_id)
        except Exception as error:
            if is_transient(error):
                logger.exception(
                    "processing request %s left RUNNING: the worker must restart to resume it",
                    request_id,
                )
                raise
            logger.exception(
                "processing request %s: unexpected error; ending it FAILED", request_id
            )
            await self._abort(request_id, error)

    async def _abort(self, request_id: UUID, error: Exception) -> None:
        """Ends the run FAILED after a non-transient error, in a fresh short transaction: the
        dates it committed keep their statuses, and a first failure already recorded (an ALL
        run's chain, OQ-36) is kept; otherwise the run's error is ``PROCESSING_ERROR`` with no
        ``failed_date``, since no date failed. If this write fails too, ``error`` escapes and the
        worker restarts."""
        try:
            async with self._uow_factory() as uow:
                ports = self._ports_for(uow)
                request = await self._lock_run(ports, request_id)
                if request.error_code is None:
                    request = replace(
                        request,
                        error_code=ProcessingErrorCode.PROCESSING_ERROR,
                        error_message=TECHNICAL_ERROR_MESSAGE,
                    )
                await ports.requests.save(
                    ended(request, ProcessingStatus.FAILED, self._clock.now())
                )
                await uow.commit()
        except RunEndedError:
            return
        except Exception:
            logger.exception(
                "processing request %s left RUNNING: ending it FAILED failed too", request_id
            )
            raise error from None
        logger.warning("processing request %s ended FAILED (PROCESSING_ERROR)", request_id)

    async def _run(self, request_id: UUID) -> None:
        request = await self._start(request_id)
        alive = request.live_chains
        day = request.next_date
        while day <= request.end_date:
            if await self._cancelled(request_id, day):
                return
            try:
                alive = await self._process_day(request_id, day, alive)
            except RunEndedError:
                raise
            except Exception:
                logger.exception(
                    "processing request %s: %s failed outside its chains", request_id, day
                )
                await self._retrying(
                    partial(self._fail_day, request_id, day, alive), request_id, "the failed date"
                )
                return
            if not alive:
                return  # the run ended FAILED in the date's transaction
            day += ONE_DAY
        await self._retrying(partial(self._complete, request_id), request_id, "the end")

    async def _retrying(
        self, step: Callable[[], Awaitable[None]], request_id: UUID, what: str
    ) -> None:
        """Runs ``step``, its own Unit of Work, again after each pause of
        ``end_retry_delays`` while it fails with a transient error; the last failure, or the
        first non-transient one, is raised. A step that committed before its error finds the
        run ended on the retry (`RunEndedError`)."""
        for delay in self._end_retry_delays:
            try:
                await step()
                return
            except RunEndedError:
                raise
            except Exception as error:
                if not is_transient(error):
                    raise
                logger.warning(
                    "processing request %s: recording %s failed; retrying in %s s",
                    request_id,
                    what,
                    delay,
                    exc_info=True,
                )
            await asyncio.sleep(delay)
        await step()

    async def _start(self, request_id: UUID) -> ProcessingRequest:
        """The run as stored. When an ALL run resumes, the chain that failed first stays
        stopped (`ProcessingRequest.live_chains`, OQ-36 item 9)."""
        async with self._uow_factory() as uow:
            return await self._lock_run(self._ports_for(uow), request_id)

    async def _cancelled(self, request_id: UUID, day: date) -> bool:
        """Step 2a: ``True`` when a cancel was requested; the run then ends CANCELLED."""
        async with self._uow_factory() as uow:
            ports = self._ports_for(uow)
            request = await self._lock_run(ports, request_id)
            if request.cancel_requested_at is None:
                return False
            await ports.requests.save(ended(request, ProcessingStatus.CANCELLED, self._clock.now()))
            await uow.commit()
            logger.info("processing request %s cancelled before %s", request_id, day)
            return True

    async def _process_day(
        self, request_id: UUID, day: date, alive: tuple[Chain, ...]
    ) -> tuple[Chain, ...]:
        """Step 2b; returns the chains still alive after D."""
        async with self._uow_factory() as uow:
            ports = self._ports_for(uow)
            request = await self._lock_run(ports, request_id)
            rows = await ports.date_statuses.lock_range(day - ONE_DAY, day)
            previous = rows.get(day - ONE_DAY, DateStatus(day - ONE_DAY))

            outcomes: dict[Chain, ChainStatus] = {}
            failures: list[ChainFailure] = []
            issues: list[IssueRecord] = []
            for chain in alive:
                try:
                    async with ports.savepoint():
                        state = await read_predecessor(
                            chain,
                            previous.date,
                            previous.status(chain),
                            date_statuses=ports.date_statuses,
                            history=ports.history,
                        )
                        if not state.allows_run:
                            failures.append(
                                ChainFailure(
                                    chain,
                                    ProcessingErrorCode.predecessor_missing(chain),
                                    PREDECESSOR_MESSAGE,
                                )
                            )
                            continue
                        zero_state = state is PredecessorState.ZERO_STATE
                        if chain is Chain.CASH:
                            await process_cash_day(day, zero_state=zero_state, ports=ports.chains)
                            outcomes[chain] = ChainStatus.PROCESSED
                        else:
                            issues = await process_positions_day(
                                day, zero_state=zero_state, ports=ports.chains
                            )
                            outcomes[chain] = (
                                ChainStatus.PROCESSED_WITH_ISSUES
                                if issues
                                else ChainStatus.PROCESSED
                            )
                except Exception:
                    logger.exception(
                        "processing request %s: chain %s failed on %s", request_id, chain, day
                    )
                    failures.append(
                        ChainFailure(
                            chain, ProcessingErrorCode.PROCESSING_ERROR, TECHNICAL_ERROR_MESSAGE
                        )
                    )

            now = self._clock.now()
            status = rows.get(day, DateStatus(day))
            for chain, outcome in outcomes.items():
                status = status.settled(chain, outcome, now)
            for failure in failures:
                status = status.settled(failure.chain, ChainStatus.FAILED, None)
            await ports.date_statuses.save(status)
            if Chain.POSITIONS in outcomes:
                await ports.issues.replace_for_date(request_id, day, issues)

            if outcomes:
                request = replace(request, progress_date=day)
            if failures and request.failed_date is None:
                kept = first_failure(failures)
                request = replace(
                    request,
                    error_code=kept.code,
                    error_message=kept.message,
                    failed_date=day,
                    failed_chain=kept.chain,
                )
            request = replace(request, updated_at=now)
            survivors = tuple(c for c in alive if c in outcomes)
            await ports.requests.save(
                request if survivors else ended(request, ProcessingStatus.FAILED, now)
            )
            await uow.commit()
            if failures:
                logger.warning(
                    "processing request %s: %s failed on %s",
                    request_id,
                    ", ".join(f.chain for f in failures),
                    day,
                )
            return survivors

    async def _fail_day(self, request_id: UUID, day: date, alive: tuple[Chain, ...]) -> None:
        """Step 2c: D FAILED for every live chain, and the run FAILED (OQ-40 item 1)."""
        async with self._uow_factory() as uow:
            ports = self._ports_for(uow)
            request = await self._lock_run(ports, request_id)
            status = (await ports.date_statuses.lock_range(day, day)).get(day, DateStatus(day))
            for chain in alive:
                status = status.settled(chain, ChainStatus.FAILED, None)
            await ports.date_statuses.save(status)
            if request.failed_date is None:
                request = replace(
                    request,
                    error_code=ProcessingErrorCode.PROCESSING_ERROR,
                    error_message=TECHNICAL_ERROR_MESSAGE,
                    failed_date=day,
                    failed_chain=None,
                )
            await ports.requests.save(ended(request, ProcessingStatus.FAILED, self._clock.now()))
            await uow.commit()

    async def _complete(self, request_id: UUID) -> None:
        """The run reached its end date: COMPLETED_WITH_ISSUES when a date it wrote has issues
        or, on ALL, a chain failed; COMPLETED otherwise (OQ-36). A cancel that arrived during the
        last date does not change that: there was nothing left to skip (OQ-23 item 6, OQ-50
        item 6)."""
        async with self._uow_factory() as uow:
            ports = self._ports_for(uow)
            request = await self._lock_run(ports, request_id)
            with_issues = request.failed_date is not None
            if not with_issues and Chain.POSITIONS in request.scope.chains:
                rows = await ports.date_statuses.get_range(request.start_date, request.end_date)
                with_issues = any(
                    row.portfolio is ChainStatus.PROCESSED_WITH_ISSUES for row in rows.values()
                )
            status = (
                ProcessingStatus.COMPLETED_WITH_ISSUES
                if with_issues
                else ProcessingStatus.COMPLETED
            )
            await ports.requests.save(ended(request, status, self._clock.now()))
            await uow.commit()
            logger.info("processing request %s ended %s", request_id, status)

    # --- helpers ---------------------------------------------------------------------------

    @staticmethod
    async def _lock_run(ports: RunPorts, request_id: UUID) -> ProcessingRequest:
        """The run, row-locked for the step; `RunEndedError` once it has ended."""
        request = await ports.requests.get(request_id, for_update=True)
        if request is None or request.status.is_finished:
            raise RunEndedError(str(request_id))
        return request
