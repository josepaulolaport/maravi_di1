"""The seam between the worker processes (``di1.workers``) and the module that plugs into them.

Platform owns these types; Processing supplies the implementations and the composition root
(``composition.consumers``, integrator) wires them. The processes hold no business logic.

- The processing worker (``di1.workers.main``) builds its consumers once at startup with a
  `ConsumerFactory`: each `ConsumerRegistration` names the queue, the inbox key and the
  handler. The queue, the message type and the payload belong to the module.
- The dispatcher (``di1.workers.dispatcher``) builds a `DispatchTick` once with a
  `DispatchTickFactory` and calls it in a loop: one tick selects the oldest queued job, sets
  it DISPATCHED and writes the outbox command in one transaction (interfaces.md "Transaction
  boundaries" 3). It returns what it dispatched (``ProcessingDispatcher.dispatch_next``: the
  request id), or `None` when nothing was queued; after a dispatch the loop ticks again at
  once.
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
left RUNNING resumes after its ``progress_date``). There is one worker, so nothing else runs
meanwhile."""

type DispatchTick = Callable[[], Awaitable[object | None]]
"""One dispatch attempt: what it dispatched, or `None` when there was nothing to dispatch."""

type DispatchTickFactory = Callable[[WorkerResources], DispatchTick]
