"""The RabbitMQ connection.

A robust connection reconnects by itself after a broker restart or a network failure, and
restores its channels, the topology declared on them and their consumers. Deliveries that
were not acknowledged before the failure are redelivered by the broker, which is safe because
delivery is at least once and consumers are idempotent (interfaces.md "Transaction
boundaries" 7).
"""

from __future__ import annotations

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from di1.platform.config import BrokerSettings


async def connect(settings: BrokerSettings, *, connection_name: str) -> AbstractRobustConnection:
    """Open a robust connection; ``connection_name`` identifies the process in the broker's
    management UI."""
    return await aio_pika.connect_robust(
        settings.rabbitmq_url.get_secret_value(),
        client_properties={"connection_name": connection_name},
    )
