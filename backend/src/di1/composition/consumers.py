"""The worker processes' wiring (integrator; interfaces.md "DI composition", "Transaction
boundaries" 3 to 7; OQ-45, OQ-46). The only composition module the workers import.

- `build_processing_worker`: the processing worker's plugin, all over one range processor built
  once at startup:
  - its one consumer, on Processing's run message queue. On each message the handler takes the
    oldest QUEUED request, if any, and runs it after the ack (OQ-50 item 2);
  - its startup, run once before it consumes. Exactly one worker exists (OQ-45), so an
    interrupted run is resumed after its ``progress_date``, or a run with ``cancel_requested_at``
    set is ended CANCELLED (OQ-46), inline; then the queue is swept;
  - its periodic sweep, which runs the QUEUED requests oldest first, so a request whose message
    was lost still runs;
- `QUEUES`: the consumers' queues, which the outbox relay also declares at startup, so a message
  published before the worker starts is queued instead of refused.

Processing builds its own internals (``processing.dependencies``); the composition passes the
other modules' reader factories, so each date's readers are built on that date's session.
"""

from __future__ import annotations

from di1.modules.asset.dependencies import build_asset_reader
from di1.modules.ledger.dependencies import build_ledger_reader
from di1.modules.portfolio.dependencies import portfolio_reader, results_writer
from di1.modules.prices.dependencies import build_price_reader
from di1.modules.processing.dependencies import (
    RUN_MESSAGE_TYPE,
    make_range_processor,
    make_run_message_handler,
)
from di1.platform.messaging.topology import QueueSpec
from di1.platform.messaging.worker import ConsumerRegistration, WorkerPlugin, WorkerResources

RUN_QUEUE = QueueSpec(RUN_MESSAGE_TYPE, routing_keys=(RUN_MESSAGE_TYPE,))

QUEUES: tuple[QueueSpec, ...] = (RUN_QUEUE,)


def build_processing_worker(resources: WorkerResources) -> WorkerPlugin:
    processor = make_range_processor(
        uow_factory=resources.uow_factory,
        clock=resources.clock,
        ledger_reader=build_ledger_reader,
        price_reader=build_price_reader,
        asset_reader=build_asset_reader,
        portfolio_reader=portfolio_reader,
        writer=results_writer(),
    )
    return WorkerPlugin(
        consumers=(
            ConsumerRegistration(
                queue=RUN_QUEUE,
                name=RUN_MESSAGE_TYPE,
                handler=make_run_message_handler(processor),
            ),
        ),
        startup=processor.recover_at_startup,
        sweep=processor.sweep,
    )
