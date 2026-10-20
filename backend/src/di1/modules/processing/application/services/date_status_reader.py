"""`DateStatusReader` (processing/public.py): each date's chain statuses as the screens show them.

No date is stored RUNNING (OQ-50 item 4): a date keeps its old status until the run commits its
new one. A read shows "Processando" (``RUNNING``) for the chains of the active run on its current
date, ``progress_date + 1`` (``start_date`` before its first commit), and on an ALL run only for
a chain still alive: the one that failed first (``failed_chain``) has stopped (OQ-36). The other
columns of that date (its processing times) stay as stored.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date, timedelta

from di1.modules.processing.application.interfaces.repositories import (
    DateStatusRepository,
    ProcessingChain,
    RequestRepository,
)
from di1.modules.processing.public import (
    ChainStatus,
    DateStatus,
    ProcessingRequest,
    ProcessingScope,
)
from di1.platform.database.unit_of_work import UnitOfWork


def with_active_run(
    statuses: Mapping[date, DateStatus],
    run: ProcessingRequest | None,
    start_date: date,
    end_date: date,
) -> dict[date, DateStatus]:
    """``statuses`` of [start_date, end_date] with the active ``run``'s current date shown
    RUNNING for its live chains."""
    shown = dict(statuses)
    if run is None:
        return shown
    day = run.start_date if run.progress_date is None else run.progress_date + timedelta(days=1)
    if day > run.end_date or not start_date <= day <= end_date:
        return shown  # past its last date the run is only recording its end
    chains = (
        (ProcessingChain.POSITIONS, ProcessingChain.CASH)
        if run.scope is ProcessingScope.ALL
        else (ProcessingChain(run.scope.value),)
    )
    status = shown.get(day, DateStatus(day, None, None, None, None))
    for chain in chains:
        if run.failed_chain is not None and chain.value == run.failed_chain.value:
            continue
        if chain is ProcessingChain.CASH:
            status = replace(status, cash=ChainStatus.RUNNING)
        else:
            status = replace(status, portfolio=ChainStatus.RUNNING)
    shown[day] = status
    return shown


class RunAwareDateStatusReader:
    """`DateStatusReader`: the stored statuses plus "Processando" for the active run."""

    def __init__(self, date_statuses: DateStatusRepository, requests: RequestRepository) -> None:
        self._date_statuses = date_statuses
        self._requests = requests

    async def get_date_statuses(
        self, start_date: date, end_date: date, *, uow: UnitOfWork
    ) -> Mapping[date, DateStatus]:
        statuses = await self._date_statuses.get_date_statuses(start_date, end_date, uow=uow)
        run = await self._requests.get_running(uow=uow)
        return with_active_run(statuses, run, start_date, end_date)
