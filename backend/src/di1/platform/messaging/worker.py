"""The seam between the processing worker (``di1.workers.main``) and the module that plugs into it.

Platform owns these types; Processing supplies the implementations and the composition root
(``composition.consumers``, integrator) wires them. The process holds no business logic.

At startup the worker calls its `WorkerFactory` once with its `WorkerResources` and gets a
`WorkerPlugin`, so everything the module needs is built once and shared:

- ``consumers``: each `ConsumerRegistration` names a queue and its handler. The queue, the message
  type and the payload belong to the module;
- ``startup``: awaited once, before anything is consumed: Processing's recovery of a run left
  RUNNING (OQ-45), then one sweep of the queued requests. There is one worker, so nothing else
  runs meanwhile;
- ``sweep``: run by the worker's job loop after every job and every
  ``WORKER_SWEEP_INTERVAL_SECONDS`` (`di1.platform.messaging.consumer.JobLoop`), so work whose
  message was lost still runs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.platform.messaging.consumer import Job, MessageHandler
from di1.platform.messaging.topology import QueueSpec
from di1.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class WorkerResources:
    """What the process gives the factory: fresh Units of Work over its engine, and the clock
    (`di1.platform.clock.SystemClock` in production)."""

    uow_factory: Callable[[], SqlAlchemyUnitOfWork]
    clock: Clock


@dataclass(frozen=True, slots=True)
class ConsumerRegistration:
    queue: QueueSpec
    name: str
    """The consumer's name in the logs."""
    handler: MessageHandler


@dataclass(frozen=True, slots=True)
class WorkerPlugin:
    consumers: Sequence[ConsumerRegistration]
    startup: Job
    sweep: Job


type WorkerFactory = Callable[[WorkerResources], WorkerPlugin]
