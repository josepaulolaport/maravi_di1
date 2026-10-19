"""Portfolio's frozen public contract (plan §3, W0.3c; interfaces.md "Portfolio"; OQ-23, OQ-28).

The read models mirror the frozen HTTP contract (`frontend/src/api/contract/portfolio.ts`).
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import date

import pytest

from di1.modules.portfolio.public import (
    CashSummaryView,
    PnLPointView,
    PortfolioResultsWriter,
    PortfolioSummaryView,
    PositionRowView,
    PositionsSummaryView,
    PositionTableView,
    PreviousPositionsDay,
)

VIEWS = [
    CashSummaryView,
    PositionsSummaryView,
    PortfolioSummaryView,
    PositionRowView,
    PositionTableView,
    PnLPointView,
    PreviousPositionsDay,
]


def _fields(view: type) -> list[str]:
    return [field.name for field in dataclasses.fields(view)]


@pytest.mark.parametrize("view", VIEWS, ids=lambda view: view.__name__)
def test_views_are_frozen_dataclasses(view: type) -> None:
    assert dataclasses.is_dataclass(view)
    assert view.__dataclass_params__.frozen  # type: ignore[attr-defined]


def test_the_summary_mirrors_the_http_contract_and_aum_has_no_status() -> None:
    assert _fields(PortfolioSummaryView) == ["date", "cash", "positions", "aum"]
    assert _fields(CashSummaryView) == [
        "status",
        "balance",
        "trades_cash_flow",
        "deposits",
        "withdrawals",
        "published_at",
    ]
    assert _fields(PositionsSummaryView) == [
        "status",
        "published_at",
        "market_value",
        "valuation_status",
        "position_pnl",
        "trades_pnl",
        "daily_pnl",
        "cumulative_pnl",
        "pnl_status",
    ]


def test_a_position_row_traces_its_price_by_source_not_id() -> None:
    fields = _fields(PositionRowView)

    assert "reference_source" in fields
    assert "reference_price_id" not in fields
    assert fields == [
        "asset_id",
        "asset_code",
        "maturity_date",
        "quantity",
        "average_entry_pu",
        "average_entry_rate",
        "reference_source",
        "reference_pu",
        "reference_rate",
        "financial_total",
        "position_pnl",
        "trades_pnl",
        "daily_pnl",
        "valuation_status",
        "pnl_status",
    ]


def test_the_writer_publishes_one_date_per_chain() -> None:
    positions = inspect.signature(PortfolioResultsWriter.write_positions_day)
    cash = inspect.signature(PortfolioResultsWriter.write_cash_day)

    assert list(positions.parameters) == ["self", "day", "valuation", "asset_pnl", "pnl", "uow"]
    assert positions.parameters["uow"].kind is inspect.Parameter.KEYWORD_ONLY
    assert list(cash.parameters) == ["self", "day", "uow"]
    assert not hasattr(PortfolioResultsWriter, "publish_range")


def test_a_table_is_dated_and_carries_its_chain_status() -> None:
    table = PositionTableView(date=date(2026, 10, 1), status=None, published_at=None, items=())

    assert table.status is None  # not processed


def test_the_previous_day_carries_no_reference_pus() -> None:
    assert _fields(PreviousPositionsDay) == ["state", "cumulative_pnl"]


def test_each_pnl_point_carries_the_range_sum_and_the_positions_processing_time() -> None:
    # OQ-31 item 8: positions chain only; the chart sums daily P&L from the start date.
    assert _fields(PnLPointView) == [
        "date",
        "daily_pnl",
        "cumulative_pnl",
        "range_cumulative_pnl",
        "pnl_status",
        "status",
        "published_at",
    ]
