"""The dispatcher's loop, with a fake tick (no database, no broker).

interfaces.md "Transaction boundaries" 3 (the dispatch) and 7 ("Relay and dispatcher recover
after crashes"); plan §7. The tick is Processing's; the loop only paces it and survives its
failures.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from di1.workers.dispatcher import dispatch_until_stopped


@dataclass
class _Tick:
    """Answers from ``results`` in turn (an exception is raised), then `None` (nothing queued)
    for ever."""

    results: list[str | Exception] = field(default_factory=list)
    calls: int = 0
    called: asyncio.Event = field(default_factory=asyncio.Event)
    enough_calls: int = 1
    called_enough: asyncio.Event = field(default_factory=asyncio.Event)

    async def __call__(self) -> str | None:
        self.calls += 1
        self.called.set()
        if self.calls >= self.enough_calls:
            self.called_enough.set()
        if not self.results:
            return None
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


async def _run_until(tick: _Tick, calls: int, *, interval: float) -> asyncio.Task[None]:
    stop = asyncio.Event()
    running = asyncio.create_task(
        dispatch_until_stopped(tick, stop, poll_interval_seconds=interval)
    )
    tick.enough_calls = calls
    await asyncio.wait_for(tick.called_enough.wait(), timeout=5)
    stop.set()
    await asyncio.wait_for(running, timeout=2)
    return running


async def test_a_tick_that_dispatched_is_followed_by_the_next_one_at_once() -> None:
    """Three queued jobs: three dispatches in a row, no pause between them."""
    tick = _Tick(["job-1", "job-2", "job-3"])
    loop = asyncio.get_running_loop()
    started = loop.time()

    await _run_until(tick, 4, interval=60)

    assert loop.time() - started < 1


async def test_a_tick_that_dispatched_nothing_waits_the_poll_interval() -> None:
    tick = _Tick()
    loop = asyncio.get_running_loop()
    started = loop.time()

    await _run_until(tick, 3, interval=0.2)

    assert loop.time() - started >= 0.4


async def test_a_failing_tick_is_logged_and_the_loop_goes_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A database restart must not end the dispatcher: the next tick retries."""
    tick = _Tick([RuntimeError("database restarting"), "job-1"])

    await _run_until(tick, 3, interval=0.01)

    assert "dispatch tick failed" in caplog.text
    assert "database restarting" in caplog.text


async def test_a_stop_during_the_pause_ends_the_loop_at_once() -> None:
    tick = _Tick()
    stop = asyncio.Event()
    running = asyncio.create_task(dispatch_until_stopped(tick, stop, poll_interval_seconds=60))
    await asyncio.wait_for(tick.called.wait(), timeout=2)

    stop.set()

    await asyncio.wait_for(running, timeout=1)
    assert tick.calls == 1


async def test_a_stop_during_a_tick_that_hangs_cancels_it() -> None:
    """A tick waiting on a lock must not keep SIGTERM waiting; its transaction rolls back, and
    the dispatch it was making is redone by the next dispatcher (one transaction, atomic)."""
    cancelled = asyncio.Event()
    entered = asyncio.Event()

    async def hanging_tick() -> str:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "job-1"

    stop = asyncio.Event()
    running = asyncio.create_task(
        dispatch_until_stopped(hanging_tick, stop, poll_interval_seconds=60)
    )
    await asyncio.wait_for(entered.wait(), timeout=2)

    stop.set()

    await asyncio.wait_for(running, timeout=1)
    assert cancelled.is_set()


async def test_a_stop_set_before_the_first_tick_ticks_no_more() -> None:
    tick = _Tick()
    stop = asyncio.Event()
    stop.set()

    await asyncio.wait_for(dispatch_until_stopped(tick, stop, poll_interval_seconds=60), 1)

    assert tick.calls == 0
