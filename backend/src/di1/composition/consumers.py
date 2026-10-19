"""The worker processes' wiring (integrator; interfaces.md "DI composition", "Transaction
boundaries" 3 to 7; OQ-45). The only composition module the workers import.

- `consumers`: the processing worker's one consumer, ``processing.run_request``, whose handler
  claims the dispatched run and runs its dates through `PortfolioRangeProcessor`;
- `processing_startup`: run once by the worker before it consumes. Exactly one worker exists
  (OQ-45), so an interrupted run is resumed after its ``progress_date``, or a CANCELLING one is
  ended CANCELLED, inline;
- `dispatch_tick`: the dispatcher's tick, `ProcessingDispatcher.dispatch_next`;
- `QUEUES`: the consumers' queues, which the outbox relay also declares at startup, so a command
  published before the worker starts is queued instead of refused.

Each date's readers are built on that date's session, so a run reads the facts of the
transaction it publishes in.
"""

from __future__ import annotations

from collections.abc import Awaitable, Sequence

from di1.modules.asset.dependencies import asset_reader
from di1.modules.ledger.dependencies import ledger_reader
from di1.modules.portfolio.dependencies import portfolio_reader, results_writer
from di1.modules.prices.dependencies import price_reader
from di1.modules.processing.application.services.dispatcher import (
    RUN_REQUEST_MESSAGE_TYPE,
    ProcessingDispatcher,
)
from di1.modules.processing.application.services.run_chains import DayReaders
from di1.modules.processing.application.services.run_processor import PortfolioRangeProcessor
from di1.modules.processing.infrastructure.persistence.repositories import SqlDateStatusRepository
from di1.modules.processing.infrastructure.persistence.run_store import SqlRunStore
from di1.modules.processing.presentation.messaging.run_request import (
    CONSUMER_NAME,
    RunRequestHandler,
)
from di1.platform.database.unit_of_work import UnitOfWork
from di1.platform.messaging.topology import QueueSpec
from di1.platform.messaging.worker import (
    ConsumerRegistration,
    DispatchTick,
    WorkerResources,
)

RUN_REQUEST_QUEUE = QueueSpec("processing.run_request", routing_keys=(RUN_REQUEST_MESSAGE_TYPE,))

QUEUES: tuple[QueueSpec, ...] = (RUN_REQUEST_QUEUE,)


def _day_readers(uow: UnitOfWork) -> DayReaders:
    session = uow.session
    return DayReaders(
        ledger=ledger_reader(session),
        prices=price_reader(session),
        assets=asset_reader(session),
        portfolio=portfolio_reader(session),
    )


def _processor(resources: WorkerResources) -> PortfolioRangeProcessor:
    return PortfolioRangeProcessor(
        uow_factory=resources.uow_factory,
        store=SqlRunStore(resources.clock),
        date_statuses=SqlDateStatusRepository(),
        readers_for=_day_readers,
        writer=results_writer(),
        clock=resources.clock,
    )


def consumers(resources: WorkerResources) -> Sequence[ConsumerRegistration]:
    return (
        ConsumerRegistration(
            queue=RUN_REQUEST_QUEUE,
            consumer_name=CONSUMER_NAME,
            handler=RunRequestHandler(_processor(resources)),
        ),
    )


def processing_startup(resources: WorkerResources) -> Awaitable[None]:
    return _processor(resources).recover_at_startup()


def dispatch_tick(resources: WorkerResources) -> DispatchTick:
    dispatcher = ProcessingDispatcher(
        uow_factory=resources.uow_factory,
        store=SqlRunStore(resources.clock),
        clock=resources.clock,
    )
    return dispatcher.dispatch_next
