"""`PortfolioRangeProcessor`: the worker's run of one request, one date per transaction
(interfaces.md "Processing", "Recovery at worker start" and "Transaction boundaries" 4 to 6;
OQ-11, OQ-23, OQ-26, OQ-31, OQ-36, OQ-37, OQ-38, OQ-40, OQ-44, OQ-45).

The system runs exactly one processing worker (OQ-45), which handles one run at a time: there is
no lease, claim token, fencing, recovery cap, dispatcher or active slot (OQ-46). Queueing a request
rings a doorbell, a message that names no request. On each doorbell, and at its start after
recovery, the worker drains the queue: it takes the oldest QUEUED request by
``(created_at, id)`` and runs it, until none is left. Each step is its own Unit of Work under a
row lock on the run's ``requests`` row:

1. **take** (`drain`): only while no run is RUNNING, the oldest QUEUED request is locked and set
   RUNNING with ``started_at``; a doorbell with nothing QUEUED is a no-op;
2. per date D, in calendar order, from ``start_date`` or the day after ``progress_date``:
   a. a short transaction checks the cancel flag (a cancel ends the run CANCELLED between
      dates) and sets D's live chains RUNNING, keeping ``*_previous``;
   b. D's transaction locks the ``date_status`` rows of D−1 and D, and runs each live chain in
      its own SAVEPOINT, positions first: the predecessor rule, the calculators, the writer. A
      chain that fails rolls back to its savepoint and gets FAILED on D; the other chain still
      commits (OQ-36, OQ-40). The date's statuses, issues and ``progress_date`` commit with it;
   c. a failure outside every savepoint (a lock timeout, say) rolls back all of D; a short
      transaction then sets D FAILED for every live chain and ends the run FAILED;
3. the end: COMPLETED, COMPLETED_WITH_ISSUES or FAILED; any date of the range still RUNNING is
   restored from ``*_previous`` (OQ-26).

**A step that cannot be recorded.** The end of a run (step 3) and the failure of a date
(step 2c) are retried after short pauses (``end_retry_delays``), since a database blip there
would leave the run RUNNING, and no later run is taken while it is. If they still fail, or any
other step outside a date's chains fails, the error escapes `run`: the worker process stops
with status 1 and restarts (`di1.platform.messaging.consumer.AfterAckRunner`), and recovery at
its start finishes the run.

**Recovery at worker start** (`recover_at_startup`, before the worker consumes): the run left
RUNNING (or DISPATCHED/CANCELLING, from before OQ-46) was interrupted. Its dates left RUNNING
are restored from ``*_previous`` (a row left empty is deleted); a run being cancelled (a cancel
request recorded, or CANCELLING) then ends CANCELLED before any date, any other is run to its end,
after ``progress_date`` (from ``start_date`` when NULL). Then the queue is drained.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import partial
from uuid import UUID

from di1.modules.portfolio.public import PortfolioResultsWriter
from di1.modules.processing.application.interfaces.repositories import (
    DateStatusRepository,
    ProcessingChain,
)
from di1.modules.processing.application.interfaces.run_store import (
    DateStatusRow,
    NewIssue,
    RunStore,
)
from di1.modules.processing.application.services.chain_history import LedgerChainHistory
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

PROCESSED_STATUSES = frozenset({ChainStatus.PROCESSED, ChainStatus.PROCESSED_WITH_ISSUES})
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


async def restore_running_dates(
    store: RunStore, request: ProcessingRequest, *, uow: UnitOfWork
) -> None:
    """Every date of the run's range still RUNNING goes back to its ``*_previous`` status; a
    row left with no status is deleted (OQ-26)."""
    for row in await store.running_dates(request.start_date, request.end_date, uow=uow):
        await store.save_date_status(row.restored(), uow=uow)


async def end_run(
    store: RunStore,
    request: ProcessingRequest,
    status: ProcessingStatus,
    now: datetime,
    *,
    uow: UnitOfWork,
) -> None:
    """Ends the run, restoring its dates left RUNNING (OQ-26)."""
    await restore_running_dates(store, request, uow=uow)
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

    # --- 1. take the queued requests, oldest first (OQ-46) ---------------------------------

    async def drain(self) -> None:
        """Runs the QUEUED requests one after the other, oldest ``(created_at, id)`` first, until
        none is left. What a doorbell triggers; a doorbell with nothing queued does nothing."""
        while (request_id := await self.take_next()) is not None:
            await self.run(request_id)

    async def take_next(self) -> UUID | None:
        """Locks the oldest QUEUED request and sets it RUNNING, in one transaction. ``None`` only
        when none is queued (a cancel and a take on the same row: whichever commits first wins),
        or while a run is still RUNNING: one stopped by an error it could not record waits for
        the worker's next start, so two runs never overlap."""
        async with self._uow_factory() as uow:
            if await self._store.lock_active_runs(uow=uow):
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
        """Called once when the worker starts, before it consumes: the run left RUNNING (or
        DISPATCHED/CANCELLING, from before OQ-46) was interrupted. Its dates left RUNNING are
        restored; a run being cancelled (a cancel request recorded, or CANCELLING) ends CANCELLED
        before any date; any other is run to its end here, after ``progress_date``. Then the
        queue is drained, so a request whose doorbell was lost runs too. Idempotent: a second
        call finds nothing to recover or run."""
        async with self._uow_factory() as uow:
            interrupted = await self._store.lock_active_runs(uow=uow)
            now = self._clock.now()
            to_resume: list[UUID] = []
            for request in interrupted:
                if (
                    request.status is ProcessingStatus.CANCELLING
                    or request.cancel_requested_at is not None
                ):
                    await end_run(self._store, request, ProcessingStatus.CANCELLED, now, uow=uow)
                    logger.info("processing request %s cancelled at worker start", request.id)
                    continue
                await restore_running_dates(self._store, request, uow=uow)
                await self._store.save_run(
                    replace(
                        request,
                        status=ProcessingStatus.RUNNING,
                        started_at=request.started_at or now,
                        updated_at=now,
                    ),
                    uow=uow,
                )
                to_resume.append(request.id)
            await uow.commit()
        for request_id in to_resume:
            logger.warning("processing request %s resumed at worker start", request_id)
            await self.run(request_id)
        await self.drain()

    # --- 2. the dates ----------------------------------------------------------------------

    async def run(self, request_id: UUID) -> None:
        """Processes the claimed run to its end. An error that escapes left the run RUNNING
        (even recording its end failed): the worker must restart, and recovery at its start
        resumes the run after ``progress_date``."""
        try:
            await self._run(request_id)
        except RunEndedError:
            logger.info("processing request %s has already ended", request_id)
        except Exception:
            logger.exception(
                "processing request %s left RUNNING: the worker must restart to resume it",
                request_id,
            )
            raise

    async def _run(self, request_id: UUID) -> None:
        request, alive = await self._start(request_id)
        day = (
            request.start_date if request.progress_date is None else request.progress_date + ONE_DAY
        )
        while day <= request.end_date:
            if not await self._begin_day(request_id, day, alive):
                return  # cancelled
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
        ``end_retry_delays`` while it fails; the last failure is raised. A step that committed
        before its error finds the run ended on the retry (`RunEndedError`)."""
        for delay in self._end_retry_delays:
            try:
                await step()
                return
            except RunEndedError:
                raise
            except Exception:
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

    async def _begin_day(
        self, request_id: UUID, day: date, alive: tuple[ProcessingChain, ...]
    ) -> bool:
        """Step 2a; ``False`` when a cancel was requested: the run then ends CANCELLED."""
        async with self._uow_factory() as uow:
            request = await self._lock_run(request_id, uow)
            if request.cancel_requested_at is not None:
                await end_run(
                    self._store, request, ProcessingStatus.CANCELLED, self._clock.now(), uow=uow
                )
                await uow.commit()
                logger.info("processing request %s cancelled before %s", request_id, day)
                return False
            rows = await self._store.lock_date_statuses(day, day, uow=uow)
            row = rows.get(day, DateStatusRow(day=day))
            for chain in alive:
                row = row.running(chain)
            await self._store.save_date_status(row, uow=uow)
            await uow.commit()
            return True

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
            issues: list[NewIssue] = []
            for chain in alive:
                other_processed = self._other_chain_processed(chain, alive, outcomes, current)
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
                                other_chain_processed=other_processed,
                            )
                            outcomes[chain] = ChainStatus.PROCESSED
                        else:
                            issues = await process_positions_day(
                                day,
                                zero_state=zero_state,
                                readers=readers,
                                writer=self._writer,
                                uow=uow,
                                other_chain_processed=other_processed,
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

    @staticmethod
    def _other_chain_processed(
        chain: ProcessingChain,
        alive: tuple[ProcessingChain, ...],
        outcomes: Mapping[ProcessingChain, ChainStatus],
        current: DateStatusRow,
    ) -> bool:
        """OQ-38, OQ-40 item 2: on ALL the positions call passes ``False`` and the cash call the
        positions outcome; otherwise the other chain's status on D, whichever run wrote it."""
        other = ProcessingChain.POSITIONS if chain is ProcessingChain.CASH else ProcessingChain.CASH
        if other in alive:
            return other in outcomes
        return current.status(other) in PROCESSED_STATUSES

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
            history=LedgerChainHistory(readers.ledger),
            uow=uow,
        )
        if not allows_run(state):
            return None
        return state is PredecessorState.ZERO_STATE
