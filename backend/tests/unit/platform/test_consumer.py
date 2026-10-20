"""The consumer and the worker's job loop, without a broker: one job at a time, the message acked
once its start is decided, a message arriving during a job acked at once and skipped, and the
sweep after every job and on every interval."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from di1.platform.messaging.consumer import Job, JobLoop, MessageConsumer, MessageHandler
from di1.platform.messaging.envelope import Envelope
from tests.support.waits import eventually

LONG = 3600.0
"""A sweep interval no test reaches: the sweep then runs only after a job."""


def make_envelope() -> Envelope:
    return Envelope(
        message_id=uuid.uuid4(),
        message_type="test.command",
        schema_version=1,
        created_at=datetime(2026, 10, 19, tzinfo=UTC),
        payload={},
    )


@dataclass
class FakeMessage:
    body: bytes
    message_id: str | None = None
    acks: int = 0
    events: list[str] | None = None

    async def ack(self) -> None:
        self.acks += 1
        if self.events is not None:
            self.events.append("ack")


@dataclass
class Recorder:
    events: list[str] = field(default_factory=list)
    hold: asyncio.Event | None = None

    async def sweep(self) -> None:
        self.events.append("sweep")

    def handler(self, *, start: bool = True, fail: bool = False) -> MessageHandler:
        async def handle(envelope: Envelope) -> Job | None:
            self.events.append("start")
            if fail:
                raise RuntimeError("the database is down")
            if not start:
                return None

            async def work() -> None:
                if self.hold is not None:
                    await self.hold.wait()
                self.events.append("work")

            return work

        return handle


def serving(loop: JobLoop) -> asyncio.Task[None]:
    """The loop waits on its own event, so an offer made before it first runs is kept."""
    return asyncio.create_task(loop.run())


async def stop(task: asyncio.Task[None]) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_the_message_is_acked_once_its_start_ran_and_the_job_then_a_sweep_run() -> None:
    recorder = Recorder()
    loop = JobLoop(sweep=recorder.sweep, sweep_interval_seconds=LONG)
    task = serving(loop)
    message = FakeMessage(make_envelope().to_json(), events=recorder.events)

    await MessageConsumer(name="test", handler=recorder.handler(), jobs=loop).handle(message)
    await eventually(lambda: "sweep" in recorder.events)

    assert [e for e in recorder.events if e != "ack"] == ["start", "work", "sweep"]
    assert recorder.events.count("ack") == 1
    await stop(task)


async def test_a_message_whose_request_does_not_start_is_acked_and_the_sweep_runs() -> None:
    recorder = Recorder()
    loop = JobLoop(sweep=recorder.sweep, sweep_interval_seconds=LONG)
    task = serving(loop)
    message = FakeMessage(make_envelope().to_json(), events=recorder.events)

    await MessageConsumer(name="test", handler=recorder.handler(start=False), jobs=loop).handle(
        message
    )
    await eventually(lambda: "sweep" in recorder.events)

    assert [e for e in recorder.events if e != "ack"] == ["start", "sweep"]
    assert recorder.events.count("ack") == 1
    await stop(task)


async def test_a_message_during_a_job_is_acked_at_once_and_skipped() -> None:
    """Its request stays QUEUED; the sweep after the running job takes it. Nothing waits
    unacknowledged behind a long run (RabbitMQ's consumer timeout)."""
    recorder = Recorder(hold=asyncio.Event())
    loop = JobLoop(sweep=recorder.sweep, sweep_interval_seconds=LONG)
    task = serving(loop)
    consumer = MessageConsumer(name="test", handler=recorder.handler(), jobs=loop)
    await consumer.handle(FakeMessage(make_envelope().to_json()))
    await eventually(lambda: recorder.events == ["start"])
    second = FakeMessage(make_envelope().to_json())

    await consumer.handle(second)

    assert second.acks == 1
    assert recorder.events == ["start"]  # the second message started nothing
    assert recorder.hold is not None
    recorder.hold.set()
    await eventually(lambda: recorder.events == ["start", "work", "sweep"])
    await stop(task)


async def test_a_failing_start_is_logged_the_message_acked_and_the_sweep_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The message is only a hint: the sweep retries whatever is still QUEUED."""
    recorder = Recorder()
    loop = JobLoop(sweep=recorder.sweep, sweep_interval_seconds=LONG)
    task = serving(loop)
    message = FakeMessage(make_envelope().to_json())

    await MessageConsumer(name="test", handler=recorder.handler(fail=True), jobs=loop).handle(
        message
    )
    await eventually(lambda: recorder.events == ["start", "sweep"])

    assert message.acks == 1
    assert "the database is down" in caplog.text
    assert not task.done()
    await stop(task)


async def test_a_body_that_is_not_an_envelope_is_acked_and_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = Recorder()
    loop = JobLoop(sweep=recorder.sweep, sweep_interval_seconds=LONG)
    message = FakeMessage(b"not json", message_id="m-1")

    await MessageConsumer(name="test", handler=recorder.handler(), jobs=loop).handle(message)

    assert message.acks == 1
    assert recorder.events == []
    assert "m-1" in caplog.text


async def test_the_sweep_runs_on_every_interval() -> None:
    recorder = Recorder()
    loop = JobLoop(sweep=recorder.sweep, sweep_interval_seconds=0.01)
    task = serving(loop)

    await eventually(lambda: recorder.events.count("sweep") >= 3)

    await stop(task)


@pytest.mark.parametrize("where", ["work", "sweep"])
async def test_a_failing_job_or_sweep_ends_the_loop_with_its_error(where: str) -> None:
    """A run that could not record its end stays RUNNING and blocks every later run: the
    worker stops with an error, and its startup recovery repairs the run (OQ-45)."""

    async def sweep() -> None:
        if where == "sweep":
            raise RuntimeError("the sweep failed")

    async def handle(envelope: Envelope) -> Job | None:
        async def work() -> None:
            if where == "work":
                raise RuntimeError("the run failed")

        return work

    loop = JobLoop(sweep=sweep, sweep_interval_seconds=LONG)
    task = serving(loop)

    await MessageConsumer(name="test", handler=handle, jobs=loop).handle(
        FakeMessage(make_envelope().to_json())
    )

    with pytest.raises(RuntimeError, match=f"the {'run' if where == 'work' else 'sweep'} failed"):
        await asyncio.wait_for(task, timeout=5)


async def test_a_cancelled_delivery_leaves_the_message_unacked_and_the_job_runs() -> None:
    """A stop or a closed channel cancels the delivery while its start is decided: the message
    is not acked (the broker delivers it again, and it is then skipped), and the start the loop
    began still commits and its job runs."""
    entered, release = asyncio.Event(), asyncio.Event()
    recorder = Recorder()

    async def handle(envelope: Envelope) -> Job | None:
        entered.set()
        await release.wait()
        recorder.events.append("start")

        async def work() -> None:
            recorder.events.append("work")

        return work

    loop = JobLoop(sweep=recorder.sweep, sweep_interval_seconds=LONG)
    task = serving(loop)
    message = FakeMessage(make_envelope().to_json())
    delivery = asyncio.create_task(
        MessageConsumer(name="test", handler=handle, jobs=loop).handle(message)
    )
    await asyncio.wait_for(entered.wait(), timeout=5)  # the start is being decided

    delivery.cancel()
    with pytest.raises(asyncio.CancelledError):
        await delivery
    release.set()

    await eventually(lambda: recorder.events == ["start", "work", "sweep"])
    assert message.acks == 0
    await stop(task)
