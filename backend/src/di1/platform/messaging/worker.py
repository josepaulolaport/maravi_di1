"""The seam between the worker processes (``di1.workers``) and the module that plugs into them.

Platform owns these types; Processing supplies the implementations and the composition root
(``composition.consumers``, integrator) wires them. The processes hold no business logic.

- The processing worker (``di1.workers.main``) builds its consumers once at startup with a
  `ConsumerFactory`: each `ConsumerRegistration` names the queue and the handler. The queue, the
  message type and the payload belong to the module.
- At startup, before it consumes, the worker awaits a `StartupHook` once: Processing's recovery
  of a run left RUNNING (OQ-45), then one sweep of the queued requests.
- A `SweepFactory` gives the sweep the worker's job loop runs after every job and every
  ``WORKER_SWEEP_INTERVAL_SECONDS`` (`di1.platform.messaging.consumer.JobLoop`), so work whose
  message was lost still runs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.platform.messaging.consumer import Job, MessageHandler
from di1.platform.messaging.topology import QueueSpec
from di1.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class WorkerResources:
    """What a process gives the factories: fresh Units of Work over its engine, and the clock
    (`di1.platform.clock.SystemClock` in production)."""

    uow_factory: Callable[[], SqlAlchemyUnitOfWork]
    clock: Clock


@dataclass(frozen=True, slots=True)
class ConsumerRegistration:
    queue: QueueSpec
    name: str
    """The consumer's name in the logs."""
    handler: MessageHandler


type ConsumerFactory = Callable[[WorkerResources], Sequence[ConsumerRegistration]]

type StartupHook = Callable[[WorkerResources], Awaitable[None]]
"""Work the worker awaits once at startup, before it consumes: Processing's recovery (a run
left RUNNING resumes after its ``progress_date``, OQ-45), then one sweep. There is one worker,
so nothing else runs meanwhile."""

type SweepFactory = Callable[[WorkerResources], Job]
