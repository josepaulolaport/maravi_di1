"""Processing's plain factories (interfaces.md "DI composition"). The composition root wires
the other modules' collaborators in: the HTTP router takes `make_processing_service`, and the
worker takes `make_range_processor` (its ``recover_at_startup`` is the startup hook, its
``sweep`` the periodic sweep) and `make_run_message_handler` on the `RUN_MESSAGE_TYPE` queue.
Nothing outside Processing needs its internals."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import AssetReader
from di1.modules.ledger.public import LedgerReader
from di1.modules.portfolio.public import PortfolioReader, PortfolioResultsWriter
from di1.modules.prices.public import PriceReader
from di1.modules.processing.application.interfaces.run_messages import (
    RUN_MESSAGE_TYPE as RUN_MESSAGE_TYPE,  # re-exported for the composition
)
from di1.modules.processing.application.services.chain_history import ChainHistory
from di1.modules.processing.application.services.processing import ProcessingService
from di1.modules.processing.application.services.run_chains import DayReaders
from di1.modules.processing.application.services.run_processor import (
    PortfolioRangeProcessor as PortfolioRangeProcessor,  # re-exported for the composition
)
from di1.modules.processing.infrastructure.messaging.outbox_run_messages import (
    OutboxRunMessages,
)
from di1.modules.processing.infrastructure.persistence.repositories import (
    SqlDateStatusRepository,
    SqlIssueRepository,
    SqlRequestRepository,
)
from di1.modules.processing.infrastructure.persistence.run_store import SqlRunStore
from di1.modules.processing.presentation.messaging.run_message import RunMessageHandler
from di1.modules.processing.public import DateStatusReader
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from di1.shared.clock import Clock


def make_processing_service(
    *, assets: AssetReader, ledger: LedgerReader, clock: Clock
) -> ProcessingService:
    return ProcessingService(
        requests=SqlRequestRepository(),
        date_statuses=SqlDateStatusRepository(),
        issues=SqlIssueRepository(),
        chain_history=ChainHistory(ledger),
        assets=assets,
        clock=clock,
        run_messages=OutboxRunMessages(),
    )


def make_date_status_reader() -> DateStatusReader:
    """Each date's chain statuses for Portfolio's read models (OQ-23, OQ-31)."""
    return SqlDateStatusRepository()


def make_range_processor(
    *,
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    clock: Clock,
    ledger_reader: Callable[[AsyncSession], LedgerReader],
    price_reader: Callable[[AsyncSession], PriceReader],
    asset_reader: Callable[[AsyncSession], AssetReader],
    portfolio_reader: Callable[[AsyncSession], PortfolioReader],
    writer: PortfolioResultsWriter,
) -> PortfolioRangeProcessor:
    """The worker's processor. Each ``*_reader`` is the other module's ``dependencies`` factory
    on a session: every date's readers are built on that date's session, so a run reads the
    facts of the transaction it publishes in. ``recover_at_startup`` is the worker's startup
    hook; ``sweep`` is the periodic sweep."""

    def readers_for(uow: UnitOfWork) -> DayReaders:
        session = uow.session
        return DayReaders(
            ledger=ledger_reader(session),
            prices=price_reader(session),
            assets=asset_reader(session),
            portfolio=portfolio_reader(session),
        )

    return PortfolioRangeProcessor(
        uow_factory=uow_factory,
        store=SqlRunStore(clock),
        date_statuses=SqlDateStatusRepository(),
        readers_for=readers_for,
        writer=writer,
        clock=clock,
    )


def make_run_message_handler(processor: PortfolioRangeProcessor) -> RunMessageHandler:
    """The consumer handler of the `RUN_MESSAGE_TYPE` queue: each message takes the oldest QUEUED
    request, if any (OQ-50 item 2)."""
    return RunMessageHandler(processor)
