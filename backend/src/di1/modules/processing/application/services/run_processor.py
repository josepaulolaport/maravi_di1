"""`PortfolioRangeProcessor`: the worker's run of one request, one date per transaction
(interfaces.md "Processing", "Recovery at worker start" and "Transaction boundaries" 4 to 6;
OQ-11, OQ-23, OQ-26, OQ-31, OQ-36, OQ-37, OQ-38, OQ-40, OQ-44, OQ-45).

The system runs exactly one processing worker (OQ-45), which handles one run at a time: there is
no lease, claim token, fencing, recovery cap, dispatcher or active slot (OQ-46). Queueing a
request publishes one run message; on any run message the worker takes the oldest QUEUED request
by ``(created_at, id)`` (`take_next`) and runs it, and a periodic sweep (`sweep`) does the same
until none is left, so a request whose message was lost still runs, only later (OQ-50 item 2).
Each step is its own Unit of Work under a row lock on the run's ``requests`` row:

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
(2a, 2c, 3, and the run's start) is handled by its kind (`RunStore.is_transient`):

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
swept. DISPATCHED and CANCELLING are never written (OQ-46), so no row holds them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import partial
from uuid import UUID

from di1.modules.portfolio.public import PortfolioResultsWriter
from di1.modules.processing.application.interfaces.repositories import (
    DateStatusRepository,
    IssueRecord,
    ProcessingChain,
)
from di1.modules.processing.application.interfaces.run_store import (
    DateStatusRow,
    RunStore,
)
from di1.modules.processing.application.services.chain_history import ChainHistory
from di1.modules.processing.application.services.predecessor import read_predecessor
from di1.modules.processing.application.services.run_chains import (
    DayReaders,
    ReadersFactory,
    process_cash_day,
    process_positions_day,
)
from di1.modules.processing.domain.predecessor import PredecessorState, allows_run
from di1.modules.processing.public import (
    ChainStatus,
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
)
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from di1.shared.clock import Clock

logger = logging.getLogger(__name__)

ONE_DAY = timedelta(days=1)

FINISHED = frozenset(
    {
        ProcessingStatus.COMPLETED,
        ProcessingStatus.COMPLETED_WITH_ISSUES,
        ProcessingStatus.CANCELLED,
        ProcessingStatus.FAILED,
    }
)
CHAIN_ORDER = (ProcessingChain.POSITIONS, ProcessingChain.CASH)
"""On ALL, positions first, then cash (integrator choice, portfolio/public.py)."""

PREDECESSOR_MESSAGE = "Dia anterior não processado"
PREDECESSOR_CODES = {
    ProcessingChain.CASH: "CASH_PREDECESSOR_MISSING",
    ProcessingChain.POSITIONS: "POSITIONS_PREDECESSOR_MISSING",
}
TECHNICAL_ERROR_CODE = "PROCESSING_ERROR"
"""The run's error for a technical failure on a date (OQ-44)."""
TECHNICAL_ERROR_MESSAGE = "Erro técnico ao processar a data."
END_RETRY_DELAYS = (0.5, 2.0, 5.0)
"""Pauses, in seconds, before each retry of a run's end or of a date's failure."""


class RunEndedError(Exception):
    """The run is no longer running: the worker stops without writing."""


@dataclass(frozen=True, slots=True)
class ChainFailure:
    chain: ProcessingChain
    code: str
    message: str


def scope_chains(scope: ProcessingScope) -> tuple[ProcessingChain, ...]:
    if scope is ProcessingScope.ALL:
        return CHAIN_ORDER
    return (ProcessingChain(scope.value),)


def first_failure(failures: list[ChainFailure]) -> ChainFailure:
    """The failure the run keeps: positions when both chains fail on the same date (OQ-36 item
    5: POSITIONS_PREDECESSOR_MISSING, or the positions chain's error)."""
    for failure in failures:
        if failure.chain is ProcessingChain.POSITIONS:
            return failure
    return failures[0]


async def end_run(
    store: RunStore,
    request: ProcessingRequest,
    status: ProcessingStatus,
    now: datetime,
    *,
    uow: UnitOfWork,
) -> None:
    """Ends the run; its dates keep what they committed (OQ-50 item 4)."""
    await store.save_run(replace(request, status=status, finished_at=now, updated_at=now), uow=uow)


class PortfolioRangeProcessor:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        store: RunStore,
        date_statuses: DateStatusRepository,
        readers_for: ReadersFactory,
        writer: PortfolioResultsWriter,
        clock: Clock,
        end_retry_delays: Sequence[float] = END_RETRY_DELAYS,
    ) -> None:
        self._uow_factory = uow_factory
        self._store = store
        self._date_statuses = date_statuses
        self._readers_for = readers_for
        self._writer = writer
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
            await self._store.lock_the_queue(uow=uow)
            if await self._store.lock_running_runs(uow=uow):
                await uow.commit()
                return None
            while (queued := await self._store.lock_oldest_queued(uow=uow)) is None:
                # Defensive: a cancel may commit on the oldest row while we wait on its lock.
                # With this query's plan PostgreSQL then moves on to the next row; should a plan
                # ever return no row instead, select again until a row is locked or none is
                # queued at all. No test can force that case on this query.
                if not await self._store.has_queued(uow=uow):
                    await uow.commit()
                    return None
            now = self._clock.now()
            await self._store.save_run(
                replace(queued, status=ProcessingStatus.RUNNING, started_at=now, updated_at=now),
                uow=uow,
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
            interrupted = await self._store.lock_running_runs(uow=uow)
            now = self._clock.now()
            to_resume: list[UUID] = []
            for request in interrupted:
                if request.cancel_requested_at is not None:
                    await end_run(self._store, request, ProcessingStatus.CANCELLED, now, uow=uow)
                    logger.info("processing request %s cancelled at worker start", request.id)
                    continue
                await self._store.save_run(replace(request, updated_at=now), uow=uow)
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
            if self._store.is_transient(error):
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
        dates it committed keep their statuses, and
        a first failure already recorded (an ALL run's chain, OQ-36) is kept; otherwise the
        run's error is ``PROCESSING_ERROR`` with no ``failed_date``, since no date failed. If
        this write fails too, ``error`` escapes and the worker restarts."""
        try:
            async with self._uow_factory() as uow:
                request = await self._lock_run(request_id, uow)
                if request.error_code is None:
                    request = replace(
                        request,
                        error_code=TECHNICAL_ERROR_CODE,
                        error_message=TECHNICAL_ERROR_MESSAGE,
                    )
                await end_run(
                    self._store, request, ProcessingStatus.FAILED, self._clock.now(), uow=uow
                )
                await uow.commit()
        except RunEndedError:
            return
        except Exception:
            logger.exception(
                "processing request %s left RUNNING: ending it FAILED failed too", request_id
            )
            raise error from None
        logger.warning("processing request %s ended FAILED (%s)", request_id, TECHNICAL_ERROR_CODE)

    async def _run(self, request_id: UUID) -> None:
        request, alive = await self._start(request_id)
        day = (
            request.start_date if request.progress_date is None else request.progress_date + ONE_DAY
        )
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
                if not self._store.is_transient(error):
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

    async def _start(
        self, request_id: UUID
    ) -> tuple[ProcessingRequest, tuple[ProcessingChain, ...]]:
        """The run and its live chains: when an ALL run resumes, a chain with a FAILED date in
        [start_date, progress_date] stays stopped (OQ-36 item 9)."""
        async with self._uow_factory() as uow:
            request = await self._lock_run(request_id, uow)
            chains = scope_chains(request.scope)
            if request.progress_date is not None and len(chains) > 1:
                rows = await self._date_statuses.get_date_statuses(
                    request.start_date, request.progress_date, uow=uow
                )
                failed = {
                    chain
                    for row in rows.values()
                    for chain in chains
                    if (row.cash if chain is ProcessingChain.CASH else row.portfolio)
                    is ChainStatus.FAILED
                }
                chains = tuple(c for c in chains if c not in failed)
            return request, chains

    async def _cancelled(self, request_id: UUID, day: date) -> bool:
        """Step 2a: ``True`` when a cancel was requested; the run then ends CANCELLED."""
        async with self._uow_factory() as uow:
            request = await self._lock_run(request_id, uow)
            if request.cancel_requested_at is not None:
                await end_run(
                    self._store, request, ProcessingStatus.CANCELLED, self._clock.now(), uow=uow
                )
                await uow.commit()
                logger.info("processing request %s cancelled before %s", request_id, day)
                return True
            return False

    async def _process_day(
        self, request_id: UUID, day: date, alive: tuple[ProcessingChain, ...]
    ) -> tuple[ProcessingChain, ...]:
        """Step 2b; returns the chains still alive after D."""
        async with self._uow_factory() as uow:
            request = await self._lock_run(request_id, uow)
            rows = await self._store.lock_date_statuses(day - ONE_DAY, day, uow=uow)
            previous = rows.get(day - ONE_DAY, DateStatusRow(day=day - ONE_DAY))
            current = rows.get(day, DateStatusRow(day=day))
            readers = self._readers_for(uow)

            outcomes: dict[ProcessingChain, ChainStatus] = {}
            failures: list[ChainFailure] = []
            issues: list[IssueRecord] = []
            for chain in alive:
                try:
                    async with self._store.savepoint(uow=uow):
                        zero_state = await self._predecessor(chain, previous, readers, uow)
                        if zero_state is None:
                            failures.append(
                                ChainFailure(chain, PREDECESSOR_CODES[chain], PREDECESSOR_MESSAGE)
                            )
                            continue
                        if chain is ProcessingChain.CASH:
                            await process_cash_day(
                                day,
                                zero_state=zero_state,
                                readers=readers,
                                writer=self._writer,
                                uow=uow,
                            )
                            outcomes[chain] = ChainStatus.PROCESSED
                        else:
                            issues = await process_positions_day(
                                day,
                                zero_state=zero_state,
                                readers=readers,
                                writer=self._writer,
                                uow=uow,
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
                        ChainFailure(chain, TECHNICAL_ERROR_CODE, TECHNICAL_ERROR_MESSAGE)
                    )

            now = self._clock.now()
            row = current
            for chain, status in outcomes.items():
                row = row.settled(chain, status, now)
            for failure in failures:
                row = row.settled(failure.chain, ChainStatus.FAILED, None)
            await self._store.save_date_status(row, uow=uow)
            if ProcessingChain.POSITIONS in outcomes:
                await self._store.replace_issues(request_id, day, issues, uow=uow)

            if outcomes:
                request = replace(request, progress_date=day)
            if failures and request.failed_date is None:
                kept = first_failure(failures)
                request = replace(
                    request,
                    error_code=kept.code,
                    error_message=kept.message,
                    failed_date=day,
                    failed_chain=ProcessingScope(kept.chain.value),
                )
            request = replace(request, updated_at=now)
            survivors = tuple(c for c in alive if c in outcomes)
            if survivors:
                await self._store.save_run(request, uow=uow)
            else:
                await end_run(self._store, request, ProcessingStatus.FAILED, now, uow=uow)
            await uow.commit()
            if failures:
                logger.warning(
                    "processing request %s: %s failed on %s",
                    request_id,
                    ", ".join(f.chain for f in failures),
                    day,
                )
            return survivors

    async def _fail_day(
        self, request_id: UUID, day: date, alive: tuple[ProcessingChain, ...]
    ) -> None:
        """Step 2c: D FAILED for every live chain, and the run FAILED (OQ-40 item 1)."""
        async with self._uow_factory() as uow:
            request = await self._lock_run(request_id, uow)
            rows = await self._store.lock_date_statuses(day, day, uow=uow)
            row = rows.get(day, DateStatusRow(day=day))
            for chain in alive:
                row = row.settled(chain, ChainStatus.FAILED, None)
            await self._store.save_date_status(row, uow=uow)
            if request.failed_date is None:
                request = replace(
                    request,
                    error_code=TECHNICAL_ERROR_CODE,
                    error_message=TECHNICAL_ERROR_MESSAGE,
                    failed_date=day,
                    failed_chain=None,
                )
            await end_run(self._store, request, ProcessingStatus.FAILED, self._clock.now(), uow=uow)
            await uow.commit()

    async def _complete(self, request_id: UUID) -> None:
        """The run reached its end date: COMPLETED_WITH_ISSUES when a date it wrote has issues
        or, on ALL, a chain failed; COMPLETED otherwise (OQ-36)."""
        async with self._uow_factory() as uow:
            request = await self._lock_run(request_id, uow)
            with_issues = request.failed_date is not None
            if not with_issues and ProcessingChain.POSITIONS in scope_chains(request.scope):
                rows = await self._date_statuses.get_date_statuses(
                    request.start_date, request.end_date, uow=uow
                )
                with_issues = any(
                    row.portfolio is ChainStatus.PROCESSED_WITH_ISSUES for row in rows.values()
                )
            status = (
                ProcessingStatus.COMPLETED_WITH_ISSUES
                if with_issues
                else ProcessingStatus.COMPLETED
            )
            await end_run(self._store, request, status, self._clock.now(), uow=uow)
            await uow.commit()
            logger.info("processing request %s ended %s", request_id, status)

    # --- helpers ---------------------------------------------------------------------------

    async def _lock_run(self, request_id: UUID, uow: UnitOfWork) -> ProcessingRequest:
        """The run, row-locked for the step; `RunEndedError` once it has ended."""
        request = await self._store.get_run(request_id, uow=uow, for_update=True)
        if request is None or request.status in FINISHED:
            raise RunEndedError(str(request_id))
        return request

    async def _predecessor(
        self,
        chain: ProcessingChain,
        previous: DateStatusRow,
        readers: DayReaders,
        uow: UnitOfWork,
    ) -> bool | None:
        """The predecessor rule (`domain.predecessor`, the preview's too): ``False`` to start
        from the published D−1, ``True`` from the zero state, ``None`` when D must fail."""
        state = await read_predecessor(
            chain,
            previous.day,
            previous.status(chain),
            date_statuses=self._date_statuses,
            history=ChainHistory(readers.ledger),
            uow=uow,
        )
        if not allows_run(state):
            return None
        return state is PredecessorState.ZERO_STATE
