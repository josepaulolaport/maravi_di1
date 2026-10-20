"""`unless_stopped`: a step that hangs does not hold a stop, and what it does once cancelled
(staff review small items: the one stop-aware helper of the worker processes)."""

from __future__ import annotations

import asyncio
import logging

import pytest

from di1.workers import lifecycle
from di1.workers.lifecycle import unless_stopped


async def test_a_finished_step_returns_its_result() -> None:
    async def step() -> int:
        return 7

    assert await unless_stopped(step(), asyncio.Event()) == 7


async def test_a_failing_step_raises_its_error() -> None:
    async def step() -> None:
        raise RuntimeError("the step failed")

    with pytest.raises(RuntimeError, match="the step failed"):
        await unless_stopped(step(), asyncio.Event())


async def test_a_stop_cancels_the_step_and_returns_none() -> None:
    stop = asyncio.Event()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def step() -> int:
        try:
            entered.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return 1

    running = asyncio.create_task(unless_stopped(step(), stop))
    await entered.wait()
    stop.set()

    assert await running is None
    assert cancelled.is_set()


async def test_a_step_failing_on_its_cancellation_is_logged_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stop = asyncio.Event()
    entered = asyncio.Event()

    async def step() -> None:
        try:
            entered.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise RuntimeError("cleanup failed") from None

    running = asyncio.create_task(unless_stopped(step(), stop))
    await entered.wait()
    stop.set()

    with caplog.at_level(logging.WARNING, logger=lifecycle.__name__):
        await running
    assert running.result() is None
    assert "a step failed while it was stopped" in caplog.text
    assert "cleanup failed" in caplog.text


async def test_a_result_produced_while_stopping_is_discarded() -> None:
    """The step finished as the stop came: nobody uses its result, so ``discard`` releases it."""
    stop = asyncio.Event()
    entered = asyncio.Event()
    discarded: list[str] = []

    async def step() -> str:
        try:
            entered.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return "connection"
        return "never"

    async def discard(value: str | None) -> None:
        discarded.append(str(value))

    running = asyncio.create_task(unless_stopped(step(), stop, discard=discard))
    await entered.wait()
    stop.set()

    assert await running is None
    assert discarded == ["connection"]
