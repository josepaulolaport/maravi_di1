"""The consumer's retry pause and its name bound.

interfaces.md "Transaction boundaries" 7 (retries for transient failures only); schema.sql
``platform.inbox_messages.consumer_name VARCHAR(128)``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import cast

import pytest
from aio_pika.abc import AbstractIncomingMessage
from pydantic import SecretStr

from di1.platform.config import BrokerSettings
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from di1.platform.messaging.consumer import AfterAck, AfterAckRunner, MessageConsumer
from di1.platform.messaging.envelope import Envelope

SETTINGS = BrokerSettings(
    rabbitmq_url=SecretStr("amqp://unused/"),
    rabbitmq_retry_base_delay_seconds=0.5,
    rabbitmq_retry_max_delay_seconds=3,
)


async def _handler(envelope: Envelope, *, uow: UnitOfWork) -> None:
    raise AssertionError("not called")


def _unused_uow() -> SqlAlchemyUnitOfWork:
    raise AssertionError("not called")


def _consumer(name: str = "worker") -> MessageConsumer:
    return MessageConsumer(
        consumer_name=name, handler=_handler, uow_factory=_unused_uow, settings=SETTINGS
    )


@dataclass
class _Delivery:
    headers: dict[str, object] = field(default_factory=dict)


def _delay(headers: dict[str, object]) -> float:
    return _consumer().retry_delay(cast(AbstractIncomingMessage, _Delivery(headers)))


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, 0.5),
        ({"x-delivery-count": 0}, 0.5),
        ({"x-delivery-count": 1}, 1.0),
        ({"x-delivery-count": 2}, 2.0),
        ({"x-delivery-count": 3}, 3.0),
        ({"x-delivery-count": 10_000}, 3.0),
        ({"x-delivery-count": -1}, 0.5),
        ({"x-delivery-count": "2"}, 0.5),
    ],
)
def test_the_retry_pause_doubles_per_redelivery_up_to_the_maximum(
    headers: dict[str, object], expected: float
) -> None:
    assert _delay(headers) == expected


@pytest.mark.parametrize("name", ["", "x" * 129])
def test_the_consumer_name_must_fit_the_inbox_column(name: str) -> None:
    with pytest.raises(ValueError, match="1 to 128"):
        _consumer(name)


def test_a_name_of_128_characters_is_accepted() -> None:
    _consumer("x" * 128)


async def test_work_submitted_after_the_runner_stopped_never_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A delivery that outlived the worker's shutdown commits its claim late: its run must not
    start while the connection and the engine close. The lease recovers it."""
    runner = AfterAckRunner()
    ran: list[str] = []

    async def work() -> None:
        ran.append("ran")

    await runner.stop()
    runner.submit(work, "late work")
    await asyncio.sleep(0.05)
    await runner.wait_idle()

    assert ran == []
    assert "late work dropped: the worker is stopping" in caplog.text


async def test_the_runner_runs_its_work_in_order() -> None:
    runner = AfterAckRunner()
    ran: list[int] = []

    def work(n: int) -> AfterAck:
        async def run() -> None:
            await asyncio.sleep(0.01 * (3 - n))
            ran.append(n)

        return run

    for n in range(3):
        runner.submit(work(n), f"work {n}")
    await asyncio.wait_for(runner.wait_idle(), timeout=5)

    assert ran == [0, 1, 2]
