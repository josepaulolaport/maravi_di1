"""Processing's plain factories (interfaces.md "DI composition"). The composition root wires the
other modules' collaborators in: the HTTP router takes `build_processing_service`, Portfolio's
read models `build_date_status_reader`, and the worker `build_range_processor` (its
``recover_at_startup`` is the startup hook, its ``sweep`` the periodic sweep) and
`build_run_message_handler` on the `RUN_MESSAGE_TYPE` queue."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import AssetReader
from di1.modules.ledger.public import LedgerReader
from di1.modules.portfolio.public import PortfolioReader, PortfolioResultsWriter
from di1.modules.prices.public import PriceReader
from di1.modules.processing.application.ports import (
    RUN_MESSAGE_TYPE as RUN_MESSAGE_TYPE,  # re-exported for the composition
)
from di1.modules.processing.application.ports import ChainPorts, RunPorts
from di1.modules.processing.application.services.chain_history import LedgerChainHistory
from di1.modules.processing.application.services.date_status_reader import (
    RunAwareDateStatusReader,
)
from di1.modules.processing.application.services.processing import ProcessingService
from di1.modules.processing.application.services.run_processor import (
    PortfolioRangeProcessor as PortfolioRangeProcessor,  # re-exported for the composition
)
from di1.modules.processing.application.services.run_processor import UnitOfWorkFactory
from di1.modules.processing.infrastructure.messaging.outbox_run_messages import (
    OutboxRunMessages,
)
from di1.modules.processing.infrastructure.persistence.repositories import (
    SqlDateStatusRepository,
    SqlIssueRepository,
    SqlRequestRepository,
    savepoint,
)
from di1.modules.processing.presentation.messaging.run_message import RunMessageHandler
from di1.modules.processing.public import DateStatusReader
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock


def build_processing_service(
    uow: UnitOfWork, *, assets: AssetReader, ledger: LedgerReader, clock: Clock
) -> ProcessingService:
    """The service on the request's Unit of Work: its writes commit that same transaction.
    ``assets`` and ``ledger`` should read through ``uow.session`` too."""
    session = uow.session
    return ProcessingService(
        uow,
        requests=SqlRequestRepository(session),
        date_statuses=SqlDateStatusRepository(session, clock),
        issues=SqlIssueRepository(session, clock),
        chain_history=LedgerChainHistory(ledger),
        run_messages=OutboxRunMessages(uow),
        assets=assets,
        clock=clock,
    )


def build_date_status_reader(session: AsyncSession, clock: Clock) -> DateStatusReader:
    """Each date's chain statuses on ``session`` for Portfolio's read models (OQ-23, OQ-31),
    "Processando" derived for the active run (OQ-50 item 4)."""
    return RunAwareDateStatusReader(
        SqlDateStatusRepository(session, clock), SqlRequestRepository(session)
    )


def build_range_processor(
    *,
    uow_factory: UnitOfWorkFactory,
    clock: Clock,
    ledger_reader: Callable[[AsyncSession], LedgerReader],
    price_reader: Callable[[AsyncSession], PriceReader],
    asset_reader: Callable[[AsyncSession], AssetReader],
    portfolio_reader: Callable[[AsyncSession], PortfolioReader],
    results_writer: Callable[[AsyncSession], PortfolioResultsWriter],
) -> PortfolioRangeProcessor:
    """The worker's processor. Each ``*_reader`` and ``results_writer`` is the other module's
    factory on a session: every step's ports are built on that step's session, so a date reads
    the facts of the transaction it publishes in."""

    def ports_for(uow: UnitOfWork) -> RunPorts:
        session = uow.session
        ledger = ledger_reader(session)
        return RunPorts(
            requests=SqlRequestRepository(session),
            date_statuses=SqlDateStatusRepository(session, clock),
            issues=SqlIssueRepository(session, clock),
            history=LedgerChainHistory(ledger),
            chains=ChainPorts(
                ledger=ledger,
                prices=price_reader(session),
                assets=asset_reader(session),
                portfolio=portfolio_reader(session),
                writer=results_writer(session),
            ),
            savepoint=lambda: savepoint(session),
        )

    return PortfolioRangeProcessor(uow_factory=uow_factory, ports_for=ports_for, clock=clock)


def build_run_message_handler(processor: PortfolioRangeProcessor) -> RunMessageHandler:
    """The consumer handler of the `RUN_MESSAGE_TYPE` queue: each message takes the oldest QUEUED
    request, if any (OQ-50 item 2)."""
    return RunMessageHandler(processor)
