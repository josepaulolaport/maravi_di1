"""ORM models of Portfolio's published tables, mirroring docs/schema.sql (the migrations own the
DDL; nothing is created from this metadata). After migration 0004 ``position_metrics`` stores no
reference PU or source: they stay in ``prices.reference_prices`` (OQ-30)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, ForeignKeyConstraint, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from di1.platform.database.base import Base

SCHEMA = "portfolio"


class PositionRow(Base):
    __tablename__ = "positions"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset.instruments.id", ondelete="RESTRICT"), primary_key=True
    )
    position_date: Mapped[date] = mapped_column(Date, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class PositionMetricsRow(Base):
    __tablename__ = "position_metrics"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_id", "metric_date"],
            [f"{SCHEMA}.positions.asset_id", f"{SCHEMA}.positions.position_date"],
            ondelete="CASCADE",
        ),
        {"schema": SCHEMA},
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    metric_date: Mapped[date] = mapped_column(Date, primary_key=True)
    average_entry_pu: Mapped[Decimal | None]
    average_entry_rate: Mapped[Decimal | None]
    financial_total: Mapped[Decimal | None]
    position_pnl: Mapped[Decimal | None]
    trades_pnl: Mapped[Decimal | None]
    daily_pnl: Mapped[Decimal | None]
    valuation_status: Mapped[str] = mapped_column(String(16))
    pnl_status: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class PortfolioMetricsRow(Base):
    __tablename__ = "portfolio_metrics"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    metric_date: Mapped[date] = mapped_column(Date, primary_key=True)
    positions_market_value: Mapped[Decimal | None]
    aum: Mapped[Decimal | None]
    position_pnl: Mapped[Decimal | None]
    trades_pnl: Mapped[Decimal | None]
    daily_pnl: Mapped[Decimal | None]
    cumulative_pnl: Mapped[Decimal | None]
    valuation_status: Mapped[str] = mapped_column(String(16))
    pnl_status: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class CashBalanceRow(Base):
    __tablename__ = "cash_balances"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    balance_date: Mapped[date] = mapped_column(Date, primary_key=True)
    cash_balance: Mapped[Decimal]
    trades_cash_flow: Mapped[Decimal]
    deposits: Mapped[Decimal]
    withdrawals: Mapped[Decimal]
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
