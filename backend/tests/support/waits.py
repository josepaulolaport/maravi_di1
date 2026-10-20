"""Waiting on state instead of on time: a test that needs another task, the broker or the database
to reach a point polls for that point, with a deadline, and never sleeps a guessed interval."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def eventually(
    condition: Callable[[], bool | Awaitable[bool]], within: float = 10.0, every: float = 0.01
) -> None:
    """Returns once ``condition`` holds, checked every ``every`` seconds; fails after ``within``
    seconds. For state that lives in another task, the broker or the database, with no event to
    await."""
    async with asyncio.timeout(within):
        while True:
            result = condition()
            if await result if inspect.isawaitable(result) else result:
                return
            await asyncio.sleep(every)


async def wait_for_a_lock_waiter(engine: AsyncEngine, count: int = 1) -> None:
    """Returns once ``count`` other sessions of the engine's database wait on a lock (a write
    queued behind another transaction's row lock); fails after 5 seconds."""

    async def waiting() -> bool:
        async with engine.connect() as connection:
            waiters = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
        return int(waiters or 0) >= count

    await eventually(waiting, within=5)
