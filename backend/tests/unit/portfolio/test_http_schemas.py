"""Portfolio HTTP shapes (``frontend/src/api/contract/portfolio.ts`` with the OQ-31 status names).

The MSW fixtures (``frontend/src/api/mocks/fixtures.ts``: ``summaries`` and ``positions`` of
2026-10-14 and 2026-10-15) are the golden examples: field names, decimals as strings in their
stored scale, ``null`` rather than 0, a chain with no status ``NOT_PROCESSED``, instants in UTC.
The HTTP layer only renames and formats the read models; what they hold is tested in
test_queries.py, and the routes' error answers in tests/integration/portfolio/test_http.py."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from di1.modules.pnl.public import CalculationCompleteness
from di1.modules.portfolio.presentation.http.schemas import (
    PnlSeriesResponse,
    PortfolioPositionsResponse,
    PortfolioSummaryResponse,
)
from di1.modules.portfolio.public import (
    CashSummaryView,
    PnLPointView,
    PortfolioSummaryView,
    PositionRowView,
    PositionsSummaryView,
    PositionTableView,
    ValuationStatus,
)
from di1.modules.prices.public import PriceSource
from di1.modules.processing.public import ChainStatus

OCT_14, OCT_15, OCT_16 = date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)
# fixtures.ts writes the instant in São Paulo time; the API sends every instant in UTC (S4).
PUBLISHED_AT = datetime(2026, 10, 16, 18, 40, tzinfo=timezone(timedelta(hours=-3)))
PUBLISHED_AT_JSON = "2026-10-16T21:40:00Z"
DI1F28 = UUID("00000000-0000-0000-0000-000000000028")
DI1F29 = UUID("00000000-0000-0000-0000-000000000029")
COMPLETE = CalculationCompleteness.COMPLETE
D = Decimal


def _json(response: Any) -> Any:
    return response.model_dump(mode="json")


# fixtures.ts summaries[0], with the OQ-31 status names.
SUMMARY_OCT_14 = PortfolioSummaryView(
    date=OCT_14,
    cash=CashSummaryView(
        status=ChainStatus.PROCESSED,
        balance=D("609935.3745326500"),
        trades_cash_flow=D("-890064.6254673500"),
        deposits=D("1500000.00"),
        withdrawals=D("0.00"),
        published_at=PUBLISHED_AT,
    ),
    positions=PositionsSummaryView(
        status=ChainStatus.PROCESSED,
        published_at=PUBLISHED_AT,
        market_value=D("890064.6254673500"),
        valuation_status=COMPLETE,
        position_pnl=D("0"),
        trades_pnl=D("0.0000000000"),
        daily_pnl=D("0.0000000000"),
        cumulative_pnl=D("0.0000000000"),
        pnl_status=COMPLETE,
    ),
    aum=D("1500000.0000000000"),
)
GOLDEN_SUMMARY_OCT_14 = {
    "date": "2026-10-14",
    "cash": {
        "status": "PROCESSED",
        "balance": "609935.3745326500",
        "trades_cash_flow": "-890064.6254673500",
        "deposits": "1500000.00",
        "withdrawals": "0.00",
        "published_at": PUBLISHED_AT_JSON,
    },
    "positions": {
        "status": "PROCESSED",
        "published_at": PUBLISHED_AT_JSON,
        "market_value": "890064.6254673500",
        "valuation_status": "COMPLETE",
        "position_pnl": "0",
        "trades_pnl": "0.0000000000",
        "daily_pnl": "0.0000000000",
        "cumulative_pnl": "0.0000000000",
        "pnl_status": "COMPLETE",
    },
    "aum": "1500000.0000000000",
}
NEVER_PROCESSED_SUMMARY = PortfolioSummaryView(
    date=OCT_16,
    cash=CashSummaryView(None, None, None, None, None, None),
    positions=PositionsSummaryView(None, None, None, None, None, None, None, None, None),
    aum=None,
)
GOLDEN_NEVER_PROCESSED_SUMMARY = {
    "date": "2026-10-16",
    "cash": {
        "status": "NOT_PROCESSED",
        "balance": None,
        "trades_cash_flow": None,
        "deposits": None,
        "withdrawals": None,
        "published_at": None,
    },
    "positions": {
        "status": "NOT_PROCESSED",
        "published_at": None,
        "market_value": None,
        "valuation_status": None,
        "position_pnl": None,
        "trades_pnl": None,
        "daily_pnl": None,
        "cumulative_pnl": None,
        "pnl_status": None,
    },
    "aum": None,
}


@pytest.mark.parametrize(
    ("view", "golden"),
    [
        pytest.param(SUMMARY_OCT_14, GOLDEN_SUMMARY_OCT_14, id="processed-fixture-of-14-10"),
        pytest.param(NEVER_PROCESSED_SUMMARY, GOLDEN_NEVER_PROCESSED_SUMMARY, id="never-processed"),
    ],
)
def test_the_summary_matches_the_fixture(view: PortfolioSummaryView, golden: Any) -> None:
    assert _json(PortfolioSummaryResponse.of(view)) == golden


def _row(
    asset_id: UUID,
    code: str,
    maturity: date,
    quantity: int,
    average: tuple[str, str],
    reference: tuple[PriceSource, str, str],
    pnl: tuple[str, str, str],
    financial_total: str,
) -> PositionRowView:
    source, pu, rate = reference
    return PositionRowView(
        asset_id=asset_id,
        asset_code=code,
        maturity_date=maturity,
        quantity=quantity,
        average_entry_pu=D(average[0]),
        average_entry_rate=D(average[1]),
        reference_source=source,
        reference_pu=D(pu),
        reference_rate=D(rate),
        reference_price_changed=False,
        financial_total=D(financial_total),
        position_pnl=D(pnl[0]),
        trades_pnl=D(pnl[1]),
        daily_pnl=D(pnl[2]),
        valuation_status=ValuationStatus.COMPLETE,
        pnl_status=COMPLETE,
    )


# fixtures.ts positions[0] and positions[1].
TABLE_OCT_14 = PositionTableView(
    date=OCT_14,
    status=ChainStatus.PROCESSED,
    published_at=PUBLISHED_AT,
    items=(
        _row(
            DI1F28,
            "DI1F28",
            date(2028, 1, 3),
            10,
            ("89006.4625467350", "0.10"),
            (PriceSource.MANUAL, "89006.4625467350", "0.10"),
            ("0", "0.0000000000", "0.0000000000"),
            "890064.6254673500",
        ),
    ),
)
GOLDEN_ROW_OCT_14 = {
    "asset_id": str(DI1F28),
    "asset_code": "DI1F28",
    "maturity_date": "2028-01-03",
    "quantity": 10,
    "average_entry_pu": "89006.4625467350",
    "average_entry_rate": "0.10",
    "reference_source": "MANUAL",
    "reference_pu": "89006.4625467350",
    "reference_rate": "0.10",
    "reference_price_changed": False,
    "financial_total": "890064.6254673500",
    "position_pnl": "0",
    "trades_pnl": "0.0000000000",
    "daily_pnl": "0.0000000000",
    "valuation_status": "COMPLETE",
    "pnl_status": "COMPLETE",
}
TABLE_OCT_15 = PositionTableView(
    date=OCT_15,
    status=ChainStatus.PROCESSED,
    published_at=PUBLISHED_AT,
    items=(
        _row(
            DI1F28,
            "DI1F28",
            date(2028, 1, 3),
            10,
            ("89006.4625467350", "0.10"),
            (PriceSource.B3, "89128.4824345118", "0.0990"),
            ("1220.1988777680", "0", "1220.1988777680"),
            "891284.8243451180",
        ),
        _row(
            DI1F29,
            "DI1F29",
            date(2029, 1, 2),
            5,
            ("82057.00", "0.093203413834"),
            (PriceSource.MANUAL, "80206.1333187932", "0.1045"),
            ("0", "-9254.3334060340", "-9254.3334060340"),
            "401030.6665939660",
        ),
    ),
)
GOLDEN_ROWS_OCT_15 = [
    {
        "asset_id": str(DI1F28),
        "asset_code": "DI1F28",
        "maturity_date": "2028-01-03",
        "quantity": 10,
        "average_entry_pu": "89006.4625467350",
        "average_entry_rate": "0.10",
        "reference_source": "B3",
        "reference_pu": "89128.4824345118",
        "reference_rate": "0.0990",
        "reference_price_changed": False,
        "financial_total": "891284.8243451180",
        "position_pnl": "1220.1988777680",
        "trades_pnl": "0",
        "daily_pnl": "1220.1988777680",
        "valuation_status": "COMPLETE",
        "pnl_status": "COMPLETE",
    },
    {
        "asset_id": str(DI1F29),
        "asset_code": "DI1F29",
        "maturity_date": "2029-01-02",
        "quantity": 5,
        "average_entry_pu": "82057.00",
        "average_entry_rate": "0.093203413834",
        "reference_source": "MANUAL",
        "reference_pu": "80206.1333187932",
        "reference_rate": "0.1045",
        "reference_price_changed": False,
        "financial_total": "401030.6665939660",
        "position_pnl": "0",
        "trades_pnl": "-9254.3334060340",
        "daily_pnl": "-9254.3334060340",
        "valuation_status": "COMPLETE",
        "pnl_status": "COMPLETE",
    },
]


@pytest.mark.parametrize(
    ("view", "golden"),
    [
        pytest.param(
            TABLE_OCT_14,
            {
                "date": "2026-10-14",
                "status": "PROCESSED",
                "published_at": PUBLISHED_AT_JSON,
                "items": [GOLDEN_ROW_OCT_14],
            },
            id="fixture-of-14-10",
        ),
        pytest.param(
            TABLE_OCT_15,
            {
                "date": "2026-10-15",
                "status": "PROCESSED",
                "published_at": PUBLISHED_AT_JSON,
                "items": GOLDEN_ROWS_OCT_15,
            },
            id="fixture-of-15-10",
        ),
        pytest.param(
            PositionTableView(date=OCT_16, status=None, published_at=None, items=()),
            {"date": "2026-10-16", "status": "NOT_PROCESSED", "published_at": None, "items": []},
            id="never-processed",
        ),
    ],
)
def test_the_positions_table_matches_the_fixture(view: PositionTableView, golden: Any) -> None:
    assert _json(PortfolioPositionsResponse.of(view)) == golden


def test_the_pnl_series_sends_every_date_with_the_range_sum() -> None:
    # OQ-31 item 8, OQ-41: 16/10 is not processed: no daily P&L, the range sum carried.
    points = (
        PnLPointView(OCT_14, D("0.0000000000"), D("0.0000000000"), ChainStatus.PROCESSED),
        PnLPointView(OCT_15, D("-8034.1345282660"), D("-8034.1345282660"), ChainStatus.PROCESSED),
        PnLPointView(OCT_16, None, D("-8034.1345282660"), None),
    )

    assert _json(PnlSeriesResponse.of(points)) == {
        "items": [
            {
                "date": "2026-10-14",
                "daily_pnl": "0.0000000000",
                "range_cumulative_pnl": "0.0000000000",
                "status": "PROCESSED",
            },
            {
                "date": "2026-10-15",
                "daily_pnl": "-8034.1345282660",
                "range_cumulative_pnl": "-8034.1345282660",
                "status": "PROCESSED",
            },
            {
                "date": "2026-10-16",
                "daily_pnl": None,
                "range_cumulative_pnl": "-8034.1345282660",
                "status": "NOT_PROCESSED",
            },
        ]
    }
