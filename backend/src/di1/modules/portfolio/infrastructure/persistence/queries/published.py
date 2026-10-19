"""The SQL of Portfolio's published tables, one date at a time (OQ-23).

AUM lives in ``portfolio_metrics`` but its cash side is in ``cash_balances`` (OQ-21): both writes
recompute it in SQL from the two rows of the same date, so it is exact NUMERIC and ``NULL`` when
either side is missing (OQ-28)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from sqlalchemy import (
    Delete,
    Insert,
    Select,
    TextClause,
    Update,
    delete,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from di1.modules.portfolio.infrastructure.persistence.models import (
    CashBalanceRow,
    PortfolioMetricsRow,
    PositionMetricsRow,
    PositionRow,
)

READ_SNAPSHOT: TextClause = text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
"""One snapshot for a whole read transaction: PostgreSQL's default, READ COMMITTED, takes a new
snapshot per statement, so a commit landing between two reads would mix dates' states."""


def delete_positions(on: date) -> Delete:
    """``on``'s positions; their ``position_metrics`` rows go with them (ON DELETE CASCADE)."""
    return delete(PositionRow).where(PositionRow.position_date == on)


def insert_positions(rows: Sequence[Mapping[str, Any]]) -> Insert:
    return insert(PositionRow).values(list(rows))


def insert_position_metrics(rows: Sequence[Mapping[str, Any]]) -> Insert:
    return insert(PositionMetricsRow).values(list(rows))


def upsert_portfolio_metrics(values: Mapping[str, Any]) -> Insert:
    statement = pg_insert(PortfolioMetricsRow).values(dict(values))
    changed = {k: statement.excluded[k] for k in values if k != "metric_date"}
    return statement.on_conflict_do_update(
        index_elements=[PortfolioMetricsRow.metric_date],
        set_={**changed, "updated_at": func.now()},
    )


def upsert_cash_balance(values: Mapping[str, Any]) -> Insert:
    statement = pg_insert(CashBalanceRow).values(dict(values))
    changed = {k: statement.excluded[k] for k in values if k != "balance_date"}
    return statement.on_conflict_do_update(
        index_elements=[CashBalanceRow.balance_date],
        set_={**changed, "updated_at": func.now()},
    )


def recompute_aum(on: date, *, other_chain_processed: bool) -> Update:
    """AUM = the date's cash + its market value; NULL propagates from either side, and AUM is
    NULL while the other chain of the date is not processed (OQ-38)."""
    if not other_chain_processed:
        return (
            update(PortfolioMetricsRow)
            .where(PortfolioMetricsRow.metric_date == on)
            .values(aum=None, updated_at=func.now())
        )
    cash = (
        select(CashBalanceRow.cash_balance)
        .where(CashBalanceRow.balance_date == on)
        .scalar_subquery()
    )
    return (
        update(PortfolioMetricsRow)
        .where(PortfolioMetricsRow.metric_date == on)
        .values(aum=cash + PortfolioMetricsRow.positions_market_value, updated_at=func.now())
    )


def cash_balance(on: date) -> Select[CashBalanceRow]:
    return select(CashBalanceRow).where(CashBalanceRow.balance_date == on)


def portfolio_metrics(start_date: date, end_date: date) -> Select[PortfolioMetricsRow]:
    return (
        select(PortfolioMetricsRow)
        .where(PortfolioMetricsRow.metric_date.between(start_date, end_date))
        .order_by(PortfolioMetricsRow.metric_date)
    )


def positions_with_metrics(on: date) -> Select[PositionRow, PositionMetricsRow]:
    """Every position of ``on`` with its metrics; the writer always writes both together."""
    return (
        select(PositionRow, PositionMetricsRow)
        .join(
            PositionMetricsRow,
            (PositionMetricsRow.asset_id == PositionRow.asset_id)
            & (PositionMetricsRow.metric_date == PositionRow.position_date),
        )
        .where(PositionRow.position_date == on)
        .order_by(PositionRow.asset_id)
    )
