"""Periodic deletion of old platform rows (inbox records, published outbox rows), run by the
outbox relay's poll loop, the platform's only periodic loop."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork

logger = logging.getLogger(__name__)


class Retention:
    """Runs ``delete`` at most once per ``interval_seconds``, the first time at once, each in
    its own Unit of Work. A process's periodic loop calls `run_if_due` on each turn."""

    def __init__(
        self,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        *,
        name: str,
        delete: Callable[[UnitOfWork], Awaitable[int]],
        interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._uow_factory = uow_factory
        self._name = name
        self._delete = delete
        self._interval = interval_seconds
        self._clock = clock
        self._next_run: float | None = None

    async def run_if_due(self) -> int | None:
        """Delete the old rows if the interval has passed; return how many, or `None` when it
        was not due or failed (logged: the next interval tries again)."""
        now = self._clock()
        if self._next_run is not None and now < self._next_run:
            return None
        self._next_run = now + self._interval
        try:
            async with self._uow_factory() as uow:
                deleted = await self._delete(uow)
                await uow.commit()
        except Exception:
            logger.exception("%s retention failed", self._name)
            return None
        if deleted:
            logger.info("%s retention deleted %d rows", self._name, deleted)
        return deleted
