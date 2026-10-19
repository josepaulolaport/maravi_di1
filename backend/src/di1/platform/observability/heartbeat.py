"""A heartbeat file, touched by a worker process while its loop runs, so that a container
health check (`di1.workers.healthcheck`) can tell a live process from a hung one without
talking to it: Compose runs the check in the container, and the file's age is the answer.

What a fresh file proves is stated by each process: the processing worker beats from a task of
its event loop (the loop is responsive), the outbox relay after each turn of its poll loop (the
loop is progressing). Writing the file is best effort: a failure is logged, never raised, so a
full disk cannot stop the work it only reports on.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class Heartbeat:
    def __init__(self, path: Path) -> None:
        self.path = path

    def beat(self) -> None:
        try:
            self.path.touch()
        except OSError:
            logger.warning("the heartbeat file could not be written: %s", self.path, exc_info=True)

    def clear(self) -> None:
        """Remove the file, so that a file left by a previous process reads as no heartbeat."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            logger.warning("the heartbeat file could not be removed: %s", self.path, exc_info=True)


def is_fresh(path: Path, *, max_age_seconds: float, now: float | None = None) -> bool:
    """Whether ``path`` was touched within ``max_age_seconds``; a missing file is not fresh."""
    try:
        touched = path.stat().st_mtime
    except OSError:
        return False
    return (time.time() if now is None else now) - touched <= max_age_seconds


async def beat_until_stopped(
    heartbeat: Heartbeat, stop: asyncio.Event, *, interval_seconds: float
) -> None:
    """Beat at once, then every ``interval_seconds`` until ``stop`` is set."""
    while not stop.is_set():
        heartbeat.beat()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
