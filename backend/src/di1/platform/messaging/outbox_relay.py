"""The outbox relay: publishes committed ``platform.outbox_messages`` rows to the broker.

Each batch runs in one transaction. It locks the oldest unpublished rows (``FOR UPDATE SKIP
LOCKED``, so a second relay never takes the same rows), publishes them one by one and waits
for each broker confirm before marking the row published. Consequences:

- a crash after the publish and before the commit leaves the row unpublished, so the next
  relay sends it again: delivery is at least once, and consumers absorb the duplicate through
  the inbox (interfaces.md "Transaction boundaries" 7);
- a failed publish (no confirm, no route, broker down, a row that is not a valid envelope)
  increments ``publish_attempts`` and keeps the error in ``last_error``; the batch goes on.
  The broker carries no job order (PostgreSQL does: interfaces.md "Transaction boundaries" 3),
  so publication order is not kept, and a row that keeps failing never stalls the others;
- a failed row then pauses: it is left out of the batches for ``retry_base_delay_seconds``,
  doubled on each attempt up to ``retry_max_delay_seconds``. The pauses live in this process
  (no schema column), so a restarted relay retries the row at once.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy import BigInteger, Row, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY

from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.platform.messaging.envelope import Envelope
from di1.platform.messaging.publisher import PublishFailedError

logger = logging.getLogger(__name__)

LAST_ERROR_MAX_LENGTH = 2000

_MAX_BACKOFF_EXPONENT = 30

_SELECT_BATCH = text(
    "SELECT id, message_id, message_type, schema_version, payload, created_at, publish_attempts"
    " FROM platform.outbox_messages WHERE published_at IS NULL AND id <> ALL(:paused)"
    " ORDER BY id LIMIT :batch_size FOR UPDATE SKIP LOCKED"
).bindparams(bindparam("paused", type_=ARRAY(BigInteger)))
_MARK_PUBLISHED = text(
    "UPDATE platform.outbox_messages"
    " SET published_at = now(), publish_attempts = publish_attempts + 1, last_error = NULL"
    " WHERE id = :id"
)
_MARK_FAILED = text(
    "UPDATE platform.outbox_messages"
    " SET publish_attempts = publish_attempts + 1, last_error = :last_error WHERE id = :id"
)


class Publisher(Protocol):
    async def publish(self, envelope: Envelope) -> None: ...


class OutboxRelay:
    def __init__(
        self,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        publisher: Publisher,
        *,
        batch_size: int,
        retry_base_delay_seconds: float,
        retry_max_delay_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._batch_size = batch_size
        self._retry_base_delay = retry_base_delay_seconds
        self._retry_max_delay = retry_max_delay_seconds
        self._clock = clock
        self._paused_until: dict[int, float] = {}
        """Row id → monotonic time before which the row is not tried again."""

    async def relay_batch(self) -> int:
        """Publish up to ``batch_size`` rows; return how many were published and marked."""
        published = 0
        failed: dict[int, int] = {}
        async with self._uow_factory() as uow:
            rows = (
                await uow.session.execute(
                    _SELECT_BATCH, {"batch_size": self._batch_size, "paused": self._paused()}
                )
            ).all()
            for row in rows:
                failure = await self._publish(row)
                if failure is None:
                    await uow.session.execute(_MARK_PUBLISHED, {"id": row.id})
                    published += 1
                    continue
                logger.warning(
                    "outbox row %s (message %s) not published: %s",
                    row.id,
                    row.message_id,
                    failure,
                )
                await uow.session.execute(
                    _MARK_FAILED, {"id": row.id, "last_error": failure[:LAST_ERROR_MAX_LENGTH]}
                )
                failed[row.id] = row.publish_attempts + 1
            await uow.commit()
        now = self._clock()
        for row_id, attempts in failed.items():
            self._paused_until[row_id] = now + self._retry_delay(attempts)
        return published

    def _paused(self) -> list[int]:
        """The rows still pausing after a failure; forgets the pauses that are over."""
        now = self._clock()
        self._paused_until = {
            row_id: until for row_id, until in self._paused_until.items() if until > now
        }
        return list(self._paused_until)

    def _retry_delay(self, attempts: int) -> float:
        exponent = min(attempts - 1, _MAX_BACKOFF_EXPONENT)
        delay: float = self._retry_base_delay * 2**exponent
        return min(delay, self._retry_max_delay)

    async def _publish(self, row: Row[Any]) -> str | None:
        """Publish one row; return why it failed, or `None` once the broker confirmed it.

        Any failure is returned rather than raised, so the rows already confirmed in this batch
        are still marked: a row that is not a valid envelope, or an unexpected error, must not
        roll the batch back and make the relay resend those rows forever.
        """
        try:
            envelope = Envelope(
                message_id=row.message_id,
                message_type=row.message_type,
                schema_version=row.schema_version,
                created_at=row.created_at,
                payload=row.payload,
            )
        except ValidationError as error:
            return f"not a valid envelope: {error.errors(include_input=False)}"
        try:
            await self._publisher.publish(envelope)
        except PublishFailedError as error:
            return str(error)
        except Exception as error:
            logger.exception("unexpected error publishing outbox row %s", row.id)
            return f"{type(error).__name__}: {error}"
        return None

    async def run(self, stop: asyncio.Event, *, poll_interval_seconds: float) -> None:
        """Relay until ``stop`` is set. A full batch is followed at once by the next one; an
        empty, short or failed batch, or a database error, waits ``poll_interval_seconds``."""
        while not stop.is_set():
            try:
                published = await self.relay_batch()
            except Exception:
                logger.exception("outbox relay batch failed")
                published = 0
            if published < self._batch_size:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=poll_interval_seconds)
