"""The outbox relay process (plan §1 ``workers/outbox_relay.py``)::

    python -m di1.workers.outbox_relay

It reads ``DATABASE_URL``, ``RABBITMQ_URL`` and the optional broker, relay and ``LOG_LEVEL``
settings (`di1.platform.config`), configures logging once, declares the consumer queues it is
given, then publishes committed ``platform.outbox_messages`` rows until SIGTERM or SIGINT
(`di1.platform.messaging.outbox_relay`). Everything is built with plain factories, not FastAPI
dependencies (interfaces.md "DI composition").

Declaring the queues at startup, and not only in the workers that consume them, means a
command published before its worker has started is queued instead of refused (NO_ROUTE).
The queues come from the composition root; until it lists them (``composition.consumers``,
integrator), `main` declares none and each worker declares its own queue as it starts. Every
process that declares a queue must share the same ``RABBITMQ_*`` settings: a queue declared
again with another delivery limit is refused by the broker (PRECONDITION_FAILED).

SIGTERM or SIGINT stops it at any time, even while the broker has not answered yet. A failure
is logged through the configured logging and ends the process with status 1.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from aio_pika.abc import AbstractRobustConnection

from di1.platform.config import (
    BrokerSettings,
    Settings,
    get_broker_settings,
    get_settings,
)
from di1.platform.database.engine import create_engine
from di1.platform.database.session import create_session_factory
from di1.platform.database.unit_of_work import unit_of_work_factory
from di1.platform.messaging.connection import connect
from di1.platform.messaging.outbox_relay import OutboxRelay
from di1.platform.messaging.publisher import MessagePublisher
from di1.platform.messaging.topology import QueueSpec, Topology, declare_queue
from di1.workers.lifecycle import close_connection, run_process, unless_stopped

logger = logging.getLogger(__name__)

CONNECTION_NAME = "di1-outbox-relay"


async def run_outbox_relay(
    settings: Settings,
    broker_settings: BrokerSettings,
    *,
    queues: Sequence[QueueSpec],
    stop: asyncio.Event,
    topology: Topology | None = None,
) -> None:
    """Relay until ``stop`` is set, then close the broker connection and the engine."""
    topology = topology if topology is not None else Topology()
    engine = create_engine(settings)
    try:
        connection = await unless_stopped(
            connect(broker_settings, connection_name=CONNECTION_NAME),
            stop,
            discard=close_connection,
        )
        if connection is None:
            logger.info("outbox relay stopped before the broker answered")
            return
        try:
            publisher = await unless_stopped(
                _prepare(connection, topology, queues, broker_settings), stop
            )
            if publisher is None:
                logger.info("outbox relay stopped before the broker answered")
                return
            relay = OutboxRelay(
                unit_of_work_factory(create_session_factory(engine)),
                publisher,
                batch_size=broker_settings.outbox_relay_batch_size,
                retry_base_delay_seconds=broker_settings.outbox_relay_retry_base_delay_seconds,
                retry_max_delay_seconds=broker_settings.outbox_relay_retry_max_delay_seconds,
            )
            logger.info("outbox relay started (%d queues declared)", len(queues))
            await relay.run(
                stop, poll_interval_seconds=broker_settings.outbox_relay_poll_interval_seconds
            )
        finally:
            await close_connection(connection)
    finally:
        await engine.dispose()
    logger.info("outbox relay stopped")


async def _prepare(
    connection: AbstractRobustConnection,
    topology: Topology,
    queues: Sequence[QueueSpec],
    broker_settings: BrokerSettings,
) -> MessagePublisher:
    """Declare the queues and open the publisher's channel. aio-pika waits for these answers
    without a timeout, so the caller runs this under the stop. A channel left open by a stop
    is closed with the connection."""
    if queues:
        channel = await connection.channel()
        for spec in queues:
            await declare_queue(channel, topology, spec, settings=broker_settings)
        await channel.close()
    return await MessagePublisher.create(connection, topology, settings=broker_settings)


def main() -> None:
    run_process(
        "outbox relay",
        lambda stop: run_outbox_relay(get_settings(), get_broker_settings(), queues=(), stop=stop),
        logger,
    )


if __name__ == "__main__":
    main()
