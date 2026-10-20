"""The worker processes' wiring (integrator; interfaces.md "DI composition", "Transaction
boundaries" 3 to 7; OQ-45, OQ-46). The only composition module the workers import.

- `consumers`: the processing worker's one consumer, on Processing's doorbell queue. The message
  only says there is work (OQ-46): after it is acked the handler drains the oldest QUEUED
  requests;
- `processing_startup`: run once by the worker before it consumes. Exactly one worker exists
  (OQ-45), so an interrupted run is resumed after its ``progress_date``, or a run with
  ``cancel_requested_at`` set is ended CANCELLED (OQ-46), inline; then the queue is drained;
- `QUEUES`: the consumers' queues, which the outbox relay also declares at startup, so a doorbell
  published before the worker starts is queued instead of refused.

Processing builds its own internals (``processing.dependencies``); the composition passes the
other modules' reader factories, so each date's readers are built on that date's session.
"""

from __future__ import annotations

from collections.abc import Awaitable, Sequence

from di1.modules.asset.dependencies import build_asset_reader
from di1.modules.ledger.dependencies import build_ledger_reader
from di1.modules.portfolio.dependencies import portfolio_reader, results_writer
from di1.modules.prices.dependencies import build_price_reader
from di1.modules.processing.dependencies import (
    DOORBELL_CONSUMER_NAME,
    DOORBELL_QUEUE_NAME,
    DOORBELL_ROUTING_KEY,
    PortfolioRangeProcessor,
    make_doorbell_handler,
    make_range_processor,
)
from di1.platform.messaging.topology import QueueSpec
from di1.platform.messaging.worker import ConsumerRegistration, WorkerResources

DOORBELL_QUEUE = QueueSpec(DOORBELL_QUEUE_NAME, routing_keys=(DOORBELL_ROUTING_KEY,))

QUEUES: tuple[QueueSpec, ...] = (DOORBELL_QUEUE,)


def _processor(resources: WorkerResources) -> PortfolioRangeProcessor:
    return make_range_processor(
        uow_factory=resources.uow_factory,
        clock=resources.clock,
        ledger_reader=build_ledger_reader,
        price_reader=build_price_reader,
        asset_reader=build_asset_reader,
        portfolio_reader=portfolio_reader,
        writer=results_writer(),
    )


def consumers(resources: WorkerResources) -> Sequence[ConsumerRegistration]:
    return (
        ConsumerRegistration(
            queue=DOORBELL_QUEUE,
            consumer_name=DOORBELL_CONSUMER_NAME,
            handler=make_doorbell_handler(_processor(resources)),
        ),
    )


def processing_startup(resources: WorkerResources) -> Awaitable[None]:
    return _processor(resources).recover_at_startup()
