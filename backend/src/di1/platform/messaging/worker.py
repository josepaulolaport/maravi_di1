"""The seam between the worker processes (``di1.workers``) and the module that plugs into them.

Platform owns these types; Processing supplies the implementations and the composition root
(``composition.consumers``, integrator) wires them. The processes hold no business logic.

- The processing worker (``di1.workers.main``) builds its consumers once at startup with a
  `ConsumerFactory`: each `ConsumerRegistration` names the queue, the inbox key and the
  handler. The queue, the message type and the payload belong to the module.
- At startup, before it consumes, the worker awaits a `StartupHook` once: Processing's
  recovery of a run left RUNNING (OQ-45), then the drain of the queued requests (OQ-46).
  There is no dispatcher process: the worker drains again on each doorbell command.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.platform.messaging.consumer import MessageHandler
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
    consumer_name: str
    """The inbox key (``platform.inbox_messages.consumer_name``)."""
    handler: MessageHandler


type ConsumerFactory = Callable[[WorkerResources], Sequence[ConsumerRegistration]]

type StartupHook = Callable[[WorkerResources], Awaitable[None]]
"""Work the worker awaits once at startup, before it consumes: Processing's recovery (a run
left RUNNING resumes after its ``progress_date``, OQ-45), then the drain of the queued requests
(OQ-46). There is one worker, so nothing else runs meanwhile."""
