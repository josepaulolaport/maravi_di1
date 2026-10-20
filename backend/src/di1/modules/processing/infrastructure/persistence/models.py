"""ORM mappings of the ``processing.*`` tables, mirroring `docs/schema.sql` (migrations own the
DDL; foreign keys to other modules' tables are not declared here)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from di1.platform.database.base import Base

SCHEMA = "processing"


class RequestRow(Base):
    __tablename__ = "requests"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    scope: Mapped[str] = mapped_column(String(16))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32))
    progress_date: Mapped[date | None] = mapped_column(Date)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    dispatched_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    cancel_requested_at: Mapped[datetime | None]
    # Unused since OQ-45/OQ-46 (no lease, no claim token, no recovery cap); kept, with
    # dispatched_at, to mirror docs/schema.sql: the user kept the schema as it is.
    claim_token: Mapped[uuid.UUID | None]
    lease_expires_at: Mapped[datetime | None]
    attempt_count: Mapped[int] = mapped_column(server_default=text("0"))
    failed_date: Mapped[date | None] = mapped_column(Date)
    failed_chain: Mapped[str | None] = mapped_column(String(16))


class DateStatusRow(Base):
    __tablename__ = "date_status"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    # "date" is the column; the attribute is renamed so it does not shadow the type.
    day: Mapped[date] = mapped_column("date", Date, primary_key=True)
    portfolio: Mapped[str | None] = mapped_column(String(32))
    cash: Mapped[str | None] = mapped_column(String(32))
    # Unused since OQ-50 item 4 (no date is stored RUNNING, so nothing is restored).
    portfolio_previous: Mapped[str | None] = mapped_column(String(32))
    cash_previous: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    portfolio_processed_at: Mapped[datetime | None]
    cash_processed_at: Mapped[datetime | None]


class IssueRow(Base):
    __tablename__ = "issues"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    request_id: Mapped[uuid.UUID]
    asset_id: Mapped[uuid.UUID | None]
    affected_date: Mapped[date] = mapped_column(Date)
    required_price_date: Mapped[date | None] = mapped_column(Date)
    issue_type: Mapped[str] = mapped_column(String(64))
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
