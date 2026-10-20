"""HTTP shapes of the Portfolio reads: the frontend contract ``frontend/src/api/contract/
portfolio.ts`` with the OQ-31 status names. Decimals cross as strings in plain notation; absent
values are ``null``, never 0; a chain with no status is ``NOT_PROCESSED``. The read models are
mapped one to one: the HTTP layer only renames and formats (portfolio/public.py)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from di1.modules.portfolio.public import (
    CashSummaryView,
    PnLPointView,
    PortfolioSummaryView,
    PositionRowView,
    PositionsSummaryView,
    PositionTableView,
)
from di1.modules.processing.public import ChainStatus
from di1.shared.decimals import to_plain

NOT_PROCESSED = "NOT_PROCESSED"


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else to_plain(value)


def _status(status: ChainStatus | None) -> str:
    return NOT_PROCESSED if status is None else status.value


def _code(value: StrEnum | None) -> str | None:
    return None if value is None else value.value


class CashSummaryOut(BaseModel):
    status: str
    balance: str | None
    trades_cash_flow: str | None
    deposits: str | None
    withdrawals: str | None
    published_at: datetime | None

    @classmethod
    def of(cls, view: CashSummaryView) -> CashSummaryOut:
        return cls(
            status=_status(view.status),
            balance=_decimal(view.balance),
            trades_cash_flow=_decimal(view.trades_cash_flow),
            deposits=_decimal(view.deposits),
            withdrawals=_decimal(view.withdrawals),
            published_at=view.published_at,
        )


class PositionsSummaryOut(BaseModel):
    status: str
    published_at: datetime | None
    market_value: str | None
    valuation_status: str | None
    position_pnl: str | None
    trades_pnl: str | None
    daily_pnl: str | None
    cumulative_pnl: str | None
    pnl_status: str | None

    @classmethod
    def of(cls, view: PositionsSummaryView) -> PositionsSummaryOut:
        return cls(
            status=_status(view.status),
            published_at=view.published_at,
            market_value=_decimal(view.market_value),
            valuation_status=_code(view.valuation_status),
            position_pnl=_decimal(view.position_pnl),
            trades_pnl=_decimal(view.trades_pnl),
            daily_pnl=_decimal(view.daily_pnl),
            cumulative_pnl=_decimal(view.cumulative_pnl),
            pnl_status=_code(view.pnl_status),
        )


class PortfolioSummaryOut(BaseModel):
    date: date
    cash: CashSummaryOut
    positions: PositionsSummaryOut
    aum: str | None

    @classmethod
    def of(cls, view: PortfolioSummaryView) -> PortfolioSummaryOut:
        return cls(
            date=view.date,
            cash=CashSummaryOut.of(view.cash),
            positions=PositionsSummaryOut.of(view.positions),
            aum=_decimal(view.aum),
        )


class PositionRowOut(BaseModel):
    asset_id: str
    asset_code: str
    maturity_date: date | None
    quantity: int
    average_entry_pu: str | None
    average_entry_rate: str | None
    reference_source: str | None
    reference_pu: str | None
    reference_rate: str | None
    reference_price_changed: bool
    financial_total: str | None
    position_pnl: str | None
    trades_pnl: str | None
    daily_pnl: str | None
    valuation_status: str
    pnl_status: str

    @classmethod
    def of(cls, row: PositionRowView) -> PositionRowOut:
        return cls(
            asset_id=str(row.asset_id),
            asset_code=row.asset_code,
            maturity_date=row.maturity_date,
            quantity=row.quantity,
            average_entry_pu=_decimal(row.average_entry_pu),
            average_entry_rate=_decimal(row.average_entry_rate),
            reference_source=_code(row.reference_source),
            reference_pu=_decimal(row.reference_pu),
            reference_rate=_decimal(row.reference_rate),
            reference_price_changed=row.reference_price_changed,
            financial_total=_decimal(row.financial_total),
            position_pnl=_decimal(row.position_pnl),
            trades_pnl=_decimal(row.trades_pnl),
            daily_pnl=_decimal(row.daily_pnl),
            valuation_status=row.valuation_status.value,
            pnl_status=row.pnl_status.value,
        )


class PortfolioPositionsOut(BaseModel):
    date: date
    status: str
    published_at: datetime | None
    items: list[PositionRowOut]

    @classmethod
    def of(cls, view: PositionTableView) -> PortfolioPositionsOut:
        return cls(
            date=view.date,
            status=_status(view.status),
            published_at=view.published_at,
            items=[PositionRowOut.of(r) for r in view.items],
        )


class PnlPointOut(BaseModel):
    """One calendar date of the range, processed or not (OQ-41, OQ-49)."""

    date: date
    daily_pnl: str | None
    range_cumulative_pnl: str
    status: str

    @classmethod
    def of(cls, point: PnLPointView) -> PnlPointOut:
        return cls(
            date=point.date,
            daily_pnl=_decimal(point.daily_pnl),
            range_cumulative_pnl=to_plain(point.range_cumulative_pnl),
            status=_status(point.status),
        )


class PnlSeriesOut(BaseModel):
    items: list[PnlPointOut]
