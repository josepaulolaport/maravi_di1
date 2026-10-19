"""`PortfolioRangeProcessor`: the worker's run of one request, one date per transaction
(interfaces.md "Processing" and "Transaction boundaries" 4 to 6; OQ-5, OQ-11, OQ-23, OQ-31, OQ-36,
OQ-37, OQ-38, OQ-40).

The steps, each its own Unit of Work and each fenced by the claim token and the lease under a
row lock on the run's ``requests`` row (a fenced-out worker raises `LeaseLostError` and writes
nothing):

1. **claim** (in the message's Unit of Work): a new claim token, a 60 s lease, RUNNING; a run
   cancelled before it ever started ends CANCELLED here, processing no date;
2. per date D, in calendar order, from ``start_date`` or the day after ``progress_date``:
   a. a short transaction checks the cancel flag (a cancel ends the run CANCELLED between
      dates), renews the lease and sets D's live chains RUNNING, keeping ``*_previous``;
   b. D's transaction locks the ``date_status`` rows of D−1 and D, and runs each live chain in
      its own SAVEPOINT, positions first: the predecessor rule, the calculators, the writer. A
      chain that fails rolls back to its savepoint and gets FAILED on D; the other chain still
      commits (OQ-36, OQ-40). The date's statuses, issues and ``progress_date`` commit with it;
   c. a failure outside every savepoint (a lock timeout, say) rolls back all of D; a short
      transaction then sets D FAILED for every live chain and ends the run FAILED;
3. the end: COMPLETED, COMPLETED_WITH_ISSUES or FAILED; any date of the range still RUNNING is
   restored from ``*_previous`` (OQ-26).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from uuid import UUID

from di1.modules.ledger.public import EntryType
from di1.modules.portfolio.public import PortfolioResultsWriter
from di1.modules.processing.application.interfaces.repositories import (
    DateStatusRepository,
    ProcessingChain,
)
from di1.modules.processing.application.interfaces.run_store import (
    DateStatusRow,
    NewIssue,
    RunRecord,
    RunStore,
)
from di1.modules.processing.application.services.run_chains import (
    DayReaders,
    ReadersFactory,
    process_cash_day,
    process_positions_day,
)
from di1.modules.processing.public import (
    ChainStatus,
    ProcessingScope,
    ProcessingStatus,
)
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from di1.shared.clock import Clock

logger = logging.getLogger(__name__)

ONE_DAY = timedelta(days=1)
DEFAULT_LEASE_SECONDS = 60
"""OQ-5 item 5: the lease is 60 s, renewed per processed date."""

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
"""The run's error for a technical failure at a date. The docs name no code for it (spec gap
raised with lane X; isolated here)."""
TECHNICAL_ERROR_MESSAGE = "Erro técnico ao processar a data."


class LeaseLostError(Exception):
    """The run's claim token or lease no longer belongs to this worker: it is fenced out and
    writes nothing; the dispatcher re-dispatches and a new claim recovers the run (OQ-40)."""


@dataclass(frozen=True, slots=True)
class Claim:
    request_id: UUID
    token: UUID


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
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> None:
        self._uow_factory = uow_factory
        self._store = store
        self._date_statuses = date_statuses
        self._readers_for = readers_for
        self._writer = writer
        self._clock = clock
        self._lease = timedelta(seconds=lease_seconds)

    # --- 1. claim --------------------------------------------------------------------------

    async def claim(self, request_id: UUID, *, uow: UnitOfWork) -> Claim | None:
        """Claims the dispatched run in ``uow`` and commits it. ``None`` when there is nothing
        to run: an unknown or finished run, one held by a live claim (a stale or duplicate
        command), or one cancelled before it started, which ends CANCELLED here."""
        run = await self._store.get_run(request_id, uow=uow, for_update=True)
        now = self._clock.now()
        if (
            run is None
            or run.request.status in FINISHED
            or run.request.status is (ProcessingStatus.QUEUED)
        ):
            logger.info("processing request %s: nothing to claim", request_id)
            await uow.commit()
            return None
        if run.claim_token is not None and self._lease_valid(run, now):
            logger.info("processing request %s: already claimed, command ignored", request_id)
            await uow.commit()
            return None
        if run.request.status is ProcessingStatus.CANCELLING and run.request.started_at is None:
            await self._finish(run, ProcessingStatus.CANCELLED, now, uow=uow)
            await uow.commit()
            logger.info("processing request %s cancelled before it started", request_id)
            return None
        token = uuid.uuid4()
        request = run.request
        claimed = RunRecord(
            request=replace(
                request,
                status=(
                    ProcessingStatus.CANCELLING
                    if request.status is ProcessingStatus.CANCELLING
                    else ProcessingStatus.RUNNING
                ),
                started_at=request.started_at or now,
                updated_at=now,
            ),
            claim_token=token,
            lease_expires_at=now + self._lease,
            attempt_count=run.attempt_count + 1,
        )
        await self._store.save_run(claimed, uow=uow)
        await uow.commit()
        logger.info("processing request %s claimed (attempt %s)", request_id, claimed.attempt_count)
        return Claim(request_id, token)

    # --- 2. the dates ----------------------------------------------------------------------

    async def run(self, request_id: UUID, token: UUID) -> None:
        """Processes the claimed run to its end. A lost lease stops it silently."""
        try:
            await self._run(request_id, token)
        except LeaseLostError:
            logger.warning("processing request %s: lease lost, this worker stops", request_id)
        except Exception:
            # Even recording the failure failed: the run keeps its lease until it expires, then
            # the dispatcher re-dispatches it and a new claim resumes after progress_date.
            logger.exception("processing request %s: the worker stopped", request_id)

    async def _run(self, request_id: UUID, token: UUID) -> None:
        run, alive = await self._start(request_id, token)
        request = run.request
        first = (
            request.start_date if request.progress_date is None else request.progress_date + ONE_DAY
        )
        day = first
        while day <= request.end_date:
            if not await self._begin_day(request_id, token, day, alive):
                return  # cancelled
            try:
                alive = await self._process_day(request_id, token, day, alive)
            except LeaseLostError:
                raise
            except Exception:
                logger.exception(
                    "processing request %s: %s failed outside its chains", request_id, day
                )
                await self._fail_day(request_id, token, day, alive)
                return
            if not alive:
                return  # the run ended FAILED in the date's transaction
            day += ONE_DAY
        await self._complete(request_id, token)

    async def _start(
        self, request_id: UUID, token: UUID
    ) -> tuple[RunRecord, tuple[ProcessingChain, ...]]:
        """The run and its live chains: on recovery of an ALL run, a chain with a FAILED date
        in [start_date, progress_date] stays stopped (OQ-36 item 9)."""
        async with self._uow_factory() as uow:
            run = await self._fence(request_id, token, uow)
            request = run.request
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
            return run, chains

    async def _begin_day(
        self, request_id: UUID, token: UUID, day: date, alive: tuple[ProcessingChain, ...]
    ) -> bool:
        """Step 2a; ``False`` when a cancel was requested: the run then ends CANCELLED."""
        async with self._uow_factory() as uow:
            run = await self._fence(request_id, token, uow)
            now = self._clock.now()
            if run.request.cancel_requested_at is not None:
                await self._finish(run, ProcessingStatus.CANCELLED, now, uow=uow)
                await uow.commit()
                logger.info("processing request %s cancelled before %s", request_id, day)
                return False
            rows = await self._store.lock_date_statuses(day, day, uow=uow)
            row = rows.get(day, DateStatusRow(day=day))
            for chain in alive:
                row = row.running(chain)
            await self._store.save_date_status(row, uow=uow)
            await self._store.save_run(replace(run, lease_expires_at=now + self._lease), uow=uow)
            await uow.commit()
            return True

    async def _process_day(
        self, request_id: UUID, token: UUID, day: date, alive: tuple[ProcessingChain, ...]
    ) -> tuple[ProcessingChain, ...]:
        """Step 2b; returns the chains still alive after D."""
        async with self._uow_factory() as uow:
            run = await self._fence(request_id, token, uow)
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
                        zero_state = await self._predecessor(chain, previous, day, readers, uow)
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

            request = run.request
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
            run = replace(run, request=replace(request, updated_at=now))
            survivors = tuple(c for c in alive if c in outcomes)
            if survivors:
                await self._store.save_run(
                    replace(run, lease_expires_at=now + self._lease), uow=uow
                )
            else:
                await self._finish(run, ProcessingStatus.FAILED, now, uow=uow)
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
        self, request_id: UUID, token: UUID, day: date, alive: tuple[ProcessingChain, ...]
    ) -> None:
        """Step 2c: D FAILED for every live chain, and the run FAILED (OQ-40 item 1)."""
        async with self._uow_factory() as uow:
            run = await self._fence(request_id, token, uow)
            now = self._clock.now()
            rows = await self._store.lock_date_statuses(day, day, uow=uow)
            row = rows.get(day, DateStatusRow(day=day))
            for chain in alive:
                row = row.settled(chain, ChainStatus.FAILED, None)
            await self._store.save_date_status(row, uow=uow)
            request = run.request
            if request.failed_date is None:
                request = replace(
                    request,
                    error_code=TECHNICAL_ERROR_CODE,
                    error_message=TECHNICAL_ERROR_MESSAGE,
                    failed_date=day,
                    failed_chain=None,
                )
            await self._finish(replace(run, request=request), ProcessingStatus.FAILED, now, uow=uow)
            await uow.commit()

    async def _complete(self, request_id: UUID, token: UUID) -> None:
        """The run reached its end date: COMPLETED_WITH_ISSUES when a date it wrote has issues
        or, on ALL, a chain failed; COMPLETED otherwise (OQ-36)."""
        async with self._uow_factory() as uow:
            run = await self._fence(request_id, token, uow)
            request = run.request
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
            await self._finish(run, status, self._clock.now(), uow=uow)
            await uow.commit()
            logger.info("processing request %s ended %s", request_id, status)

    # --- helpers ---------------------------------------------------------------------------

    async def _finish(
        self, run: RunRecord, status: ProcessingStatus, now: datetime, *, uow: UnitOfWork
    ) -> None:
        """Ends the run: every date of its range still RUNNING is restored from ``*_previous``
        (a row left with no status is deleted, OQ-26). The worker never locks
        ``calculation_state``: the dispatcher locks it before the run's row, so the worker, which
        locks the run's row first, leaves freeing the slot to the dispatcher's next tick."""
        request = run.request
        for row in await self._store.running_dates(request.start_date, request.end_date, uow=uow):
            await self._store.save_date_status(row.restored(), uow=uow)
        finished = RunRecord(
            request=replace(request, status=status, finished_at=now, updated_at=now),
            claim_token=run.claim_token,
            lease_expires_at=None,
            attempt_count=run.attempt_count,
        )
        await self._store.save_run(finished, uow=uow)

    async def _fence(self, request_id: UUID, token: UUID, uow: UnitOfWork) -> RunRecord:
        run = await self._store.get_run(request_id, uow=uow, for_update=True)
        if (
            run is None
            or run.claim_token != token
            or run.request.status in FINISHED
            or not self._lease_valid(run, self._clock.now())
        ):
            raise LeaseLostError(str(request_id))
        return run

    @staticmethod
    def _lease_valid(run: RunRecord, now: datetime) -> bool:
        return run.lease_expires_at is not None and run.lease_expires_at > now

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
        day: date,
        readers: DayReaders,
        uow: UnitOfWork,
    ) -> bool | None:
        """The predecessor rule (OQ-31 item 4, OQ-37 item 4, OQ-40 item 5): ``False`` to start
        from the published D−1, ``True`` from the zero state, ``None`` when D must fail. Ledger
        is asked only when the chain has no status on any date before D."""
        status = previous.status(chain)
        if status in PROCESSED_STATUSES:
            return False
        if status is not None:  # FAILED or RUNNING
            return None
        if await self._date_statuses.has_status_before(chain, day, uow=uow):
            return None  # a gap: every day must be processed
        entry_type = EntryType.TRADE if chain is ProcessingChain.POSITIONS else None
        if await readers.ledger.has_entries_on_or_before(day - ONE_DAY, entry_type=entry_type):
            return None
        return True
