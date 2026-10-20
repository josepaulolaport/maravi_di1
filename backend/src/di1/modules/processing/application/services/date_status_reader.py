"""`DateStatusReader` (processing/public.py): each date's chain statuses as the screens show them.

No date is stored RUNNING (OQ-50 item 4): a date keeps its old status until the run commits its
new one. A read shows "Processando" (``RUNNING``) for the chains of the active run on its current
date, ``progress_date + 1`` (``start_date`` before its first commit), and on an ALL run only for
a chain still alive: the one that failed first (``failed_chain``) has stopped (OQ-36). The other
columns of that date (its processing times) stay as stored.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from di1.modules.processing.application.ports import DateStatusRepository, RequestRepository
from di1.modules.processing.domain.date_status import DateStatus, with_active_run


class RunAwareDateStatusReader:
    """`DateStatusReader`: the stored statuses plus "Processando" for the active run."""

    def __init__(self, date_statuses: DateStatusRepository, requests: RequestRepository) -> None:
        self._date_statuses = date_statuses
        self._requests = requests

    async def get_date_statuses(
        self, start_date: date, end_date: date
    ) -> Mapping[date, DateStatus]:
        statuses = await self._date_statuses.get_range(start_date, end_date)
        run = await self._requests.get_running()
        return with_active_run(
            statuses,
            current_date=None if run is None else run.current_date,
            live_chains=() if run is None else run.live_chains,
            start_date=start_date,
            end_date=end_date,
        )
