"""SQL over ``processing.requests``."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Insert, Select, Update, insert, select, tuple_, update

from di1.modules.processing.infrastructure.persistence.models import RequestModel

COLUMNS = (
    RequestModel.id,
    RequestModel.scope,
    RequestModel.start_date,
    RequestModel.end_date,
    RequestModel.status,
    RequestModel.created_at,
    RequestModel.dispatched_at,
    RequestModel.started_at,
    RequestModel.finished_at,
    RequestModel.cancel_requested_at,
    RequestModel.progress_date,
    RequestModel.error_code,
    RequestModel.error_message,
    RequestModel.updated_at,
    RequestModel.failed_date,
    RequestModel.failed_chain,
)
"""What a `ProcessingRequest` exposes; ``claim_token``, ``lease_expires_at`` and ``attempt_count``
are unused since OQ-45."""


def insert_request(values: dict[str, Any]) -> Insert:
    return insert(RequestModel).values(**values)


def select_request(request_id: UUID, *, for_update: bool) -> Select[*tuple[Any, ...]]:
    statement = select(*COLUMNS).where(RequestModel.id == request_id)
    return statement.with_for_update() if for_update else statement


def select_running() -> Select[*tuple[Any, ...]]:
    """The oldest RUNNING run; one worker runs one at a time (OQ-45)."""
    return (
        select(*COLUMNS)
        .where(RequestModel.status == "RUNNING")
        .order_by(RequestModel.created_at, RequestModel.id)
        .limit(1)
    )


def update_request(request_id: UUID, values: dict[str, Any]) -> Update:
    return update(RequestModel).where(RequestModel.id == request_id).values(**values)


def select_newest_first(
    limit: int, after: tuple[datetime, UUID] | None
) -> Select[*tuple[Any, ...]]:
    """Keyset page on ``(created_at, id)`` descending (OQ-26 item 1)."""
    statement = select(*COLUMNS)
    if after is not None:
        statement = statement.where(
            tuple_(RequestModel.created_at, RequestModel.id) < tuple_(*after)
        )
    return statement.order_by(RequestModel.created_at.desc(), RequestModel.id.desc()).limit(limit)
