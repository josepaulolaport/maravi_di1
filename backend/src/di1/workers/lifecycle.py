"""What every worker process shares: the stop signals, stop-aware startup steps, a bounded
close of the broker connection, and the exit status on a fatal error.

SIGTERM or SIGINT sets a stop event. Startup steps that wait on the broker or the database run
under that event, so a dependency that hangs at startup does not keep SIGTERM waiting until
Docker's SIGKILL. A failure is logged through the configured logging and ends the process with
status 1.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable

from aio_pika.abc import AbstractRobustConnection

from di1.platform.config import get_logging_settings
from di1.platform.observability.logging_setup import configure_logging

logger = logging.getLogger(__name__)

CLOSE_TIMEOUT_SECONDS = 5.0


async def unless_stopped[T](
    step: Awaitable[T],
    stop: asyncio.Event,
    *,
    discard: Callable[[T], Awaitable[None]] | None = None,
) -> T | None:
    """Await ``step``, or cancel it and return `None` if ``stop`` is set first.

    If the caller is cancelled while ``step`` has just produced its result, nobody will use
    that result: ``discard`` releases it (a connection, which would otherwise keep its
    reconnect task running)."""
    running = asyncio.ensure_future(step)
    stopping = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({running, stopping}, return_when=asyncio.FIRST_COMPLETED)
    except BaseException:
        stopping.cancel()
        await _abandon(running, discard)
        raise
    stopping.cancel()
    if not running.done():
        await _abandon(running, discard)
        return None
    return running.result()


async def _abandon[T](
    running: asyncio.Future[T], discard: Callable[[T], Awaitable[None]] | None
) -> None:
    if not running.done():
        running.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await running
    if discard is not None and not running.cancelled() and running.exception() is None:
        await discard(running.result())


async def close_connection(connection: AbstractRobustConnection) -> None:
    """Close the connection, which also stops its reconnect task; a broker that does not
    answer the close does not hold the shutdown longer than `CLOSE_TIMEOUT_SECONDS`."""
    try:
        await asyncio.wait_for(connection.close(), timeout=CLOSE_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.warning("the broker did not answer the close in %s s", CLOSE_TIMEOUT_SECONDS)


async def until_stop_signal(run: Callable[[asyncio.Event], Awaitable[None]]) -> None:
    """Run ``run(stop)`` with ``stop`` set by SIGTERM or SIGINT."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signal_number, stop.set)
    await run(stop)


def run_process(
    name: str, run: Callable[[asyncio.Event], Awaitable[None]], log: logging.Logger
) -> None:
    """A worker process's ``main``: configure logging once, run until a stop signal, and exit
    with status 1, the failure logged through ``log``, if ``run`` fails."""
    configure_logging(get_logging_settings())
    try:
        asyncio.run(until_stop_signal(run))
    except Exception:
        log.exception("%s failed", name)
        raise SystemExit(1) from None
