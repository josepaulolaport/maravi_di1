"""The dispatcher process (plan §1 ``workers/dispatcher.py``)::

    python -m di1.workers.dispatcher

It reads ``DATABASE_URL``, ``DISPATCHER_POLL_INTERVAL_SECONDS`` (default 1.0) and ``LOG_LEVEL``
(`di1.platform.config`), configures logging once, checks that PostgreSQL answers, then calls
Processing's dispatch tick (`di1.platform.messaging.worker.DispatchTick`) until SIGTERM or
SIGINT. A tick that dispatched a job is followed by the next one at once; otherwise the loop
waits the poll interval. A failing tick is logged and the loop goes on, so a database restart
does not end the process. Everything is built with plain factories, not FastAPI dependencies
(interfaces.md "DI composition").

Database only: a tick writes the dispatch command to ``platform.outbox_messages`` in the same
transaction as the job's DISPATCHED status, and the outbox relay publishes it (interfaces.md
"Transaction boundaries" 3). A stop cancels a tick in progress: the dispatch is one
transaction, so either all of it commits or none (the job then stays QUEUED for the next tick).
Startup checks that PostgreSQL answers within 5 s, so a database that is wrong or hangs ends
the process with status 1.

The tick comes from the composition root; until it provides one (``composition.consumers``,
integrator), `main` uses a placeholder that dispatches nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from di1.platform.clock import SystemClock
from di1.platform.config import (
    DispatcherSettings,
    Settings,
    get_dispatcher_settings,
    get_settings,
)
from di1.platform.database.engine import check_connection, create_engine
from di1.platform.database.session import create_session_factory
from di1.platform.database.unit_of_work import unit_of_work_factory
from di1.platform.messaging.worker import DispatchTick, DispatchTickFactory, WorkerResources
from di1.shared.clock import Clock
from di1.workers.lifecycle import run_process, unless_stopped

logger = logging.getLogger(__name__)


async def run_dispatcher(
    settings: Settings,
    dispatcher_settings: DispatcherSettings,
    *,
    tick_factory: DispatchTickFactory,
    stop: asyncio.Event,
    clock: Clock | None = None,
) -> None:
    """Dispatch until ``stop`` is set, then dispose of the engine."""
    engine = create_engine(settings)
    try:
        resources = WorkerResources(
            uow_factory=unit_of_work_factory(create_session_factory(engine)),
            clock=clock if clock is not None else SystemClock(),
        )
        tick = tick_factory(resources)
        await unless_stopped(check_connection(engine), stop)
        if stop.is_set():
            logger.info("dispatcher stopped before the database answered")
            return
        logger.info(
            "dispatcher started (poll interval %s s)",
            dispatcher_settings.dispatcher_poll_interval_seconds,
        )
        await dispatch_until_stopped(
            tick,
            stop,
            poll_interval_seconds=dispatcher_settings.dispatcher_poll_interval_seconds,
        )
    finally:
        await engine.dispose()
    logger.info("dispatcher stopped")


async def dispatch_until_stopped(
    tick: DispatchTick, stop: asyncio.Event, *, poll_interval_seconds: float
) -> None:
    """Call ``tick`` until ``stop`` is set: again at once after a dispatch, otherwise after
    ``poll_interval_seconds``. A failing tick is logged and followed by the pause."""
    while not stop.is_set():
        dispatched = False
        try:
            dispatched = await unless_stopped(tick(), stop) is not None
        except Exception:
            logger.exception("dispatch tick failed; retrying in %s s", poll_interval_seconds)
        if not dispatched:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=poll_interval_seconds)


def _no_dispatch(resources: WorkerResources) -> DispatchTick:
    """Until Processing's tick is wired: dispatches nothing."""
    logger.warning("no dispatch tick is configured: queued jobs are not dispatched")

    async def tick() -> None:
        return None

    return tick


def main() -> None:
    run_process(
        "dispatcher",
        lambda stop: run_dispatcher(
            get_settings(), get_dispatcher_settings(), tick_factory=_no_dispatch, stop=stop
        ),
        logger,
    )


if __name__ == "__main__":
    main()
