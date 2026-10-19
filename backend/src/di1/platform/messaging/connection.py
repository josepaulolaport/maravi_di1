"""The RabbitMQ connection.

A robust connection reconnects by itself after a broker restart or a network failure, and
restores its channels, the topology declared on them and their consumers. Deliveries that
were not acknowledged before the failure are redelivered by the broker, which is safe because
delivery is at least once and consumers are idempotent (interfaces.md "Transaction
boundaries" 7). The first connection is not retried: if it fails, `connect` raises and leaves
nothing running.
"""

from __future__ import annotations

import aio_pika
from aio_pika.abc import AbstractRobustConnection
from aio_pika.connection import make_url

from di1.platform.config import BrokerSettings


async def connect(settings: BrokerSettings, *, connection_name: str) -> AbstractRobustConnection:
    """Open a robust connection; ``connection_name`` identifies the process in the broker's
    management UI."""
    connection = aio_pika.RobustConnection(
        make_url(settings.rabbitmq_url.get_secret_value()),
        client_properties={"connection_name": connection_name},
    )
    try:
        await connection.connect()
    except BaseException:
        # The robust connection starts its reconnect loop with the first attempt; if that
        # attempt fails or is cancelled, the loop must stop too, or the process cannot exit.
        await connection.close()
        raise
    return connection
