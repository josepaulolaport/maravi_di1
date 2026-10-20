"""Portfolio HTTP reads against PostgreSQL 16, through the real app (interfaces.md "HTTP
endpoints"; ``frontend/src/api/contract/portfolio.ts`` with the OQ-31 status names).

The MSW fixtures (``frontend/src/api/mocks/fixtures.ts``: ``summaries`` and ``positions`` of
2026-10-14 and 2026-10-15) are the golden examples: field names, decimals as strings in their
stored scale, ``null`` rather than 0. The asset id is server-generated and compared by type.
Prices and Processing implement their readers in other lanes, so the test wires stand-ins
through their public protocols; Asset's reader is the real one.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from di1.composition.dependencies import get_session_factory
from di1.main import create_app
from di1.modules.asset.dependencies import asset_reader
from di1.modules.pnl.public import AssetPnLResult, CalculationCompleteness, PortfolioPnLResult
from di1.modules.portfolio.dependencies import portfolio_query_service, results_writer
from di1.modules.portfolio.domain.cash import CashDay
from di1.modules.portfolio.domain.positions import PositionDay, PositionsDay
from di1.modules.portfolio.domain.trade import Trade
from di1.modules.portfolio.domain.valuation import (
    AssetValuation,
    PortfolioValuation,
    ValuationStatus,
)
from di1.modules.portfolio.presentation.http.router import create_router
from di1.modules.portfolio.public import PortfolioService
from di1.modules.prices.public import PriceSource
from di1.modules.processing.public import ChainStatus, DateStatus
from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.session import create_session_factory
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.shared.clock import FixedClock
from tests.integration.asset.conftest import Di1Catalogue, seed_di1
from tests.unit.portfolio.fakes import FakeDateStatusReader, FakePriceReader

OCT_14, OCT_15, OCT_16 = date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)
PUBLISHED_AT = datetime(2026, 10, 16, 18, 40, tzinfo=timezone(timedelta(hours=-3)))
PUBLISHED_AT_JSON = "2026-10-16T18:40:00-03:00"
COMPLETE = CalculationCompleteness.COMPLETE

# fixtures.ts summaries[0], with the OQ-31 status names.
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
# fixtures.ts positions[0].items[0], the asset id aside.
GOLDEN_ROW_OCT_14 = {
    "asset_code": "DI1F28",
    "maturity_date": "2028-01-03",
    "quantity": 10,
    "average_entry_pu": "89006.4625467350",
    "average_entry_rate": "0.10",
    "reference_source": "MANUAL",
    "reference_pu": "89006.4625467350",
    "reference_rate": "0.10",
    "financial_total": "890064.6254673500",
    "position_pnl": "0",
    "trades_pnl": "0.0000000000",
    "daily_pnl": "0.0000000000",
    "valuation_status": "COMPLETE",
    "pnl_status": "COMPLETE",
}


async def _publish_fixture_days(settings: Settings, di1f28: UUID, di1f29: UUID) -> None:
    """Writes 14/10 (both chains) and 15/10 (positions totals) as Processing would."""
    engine = create_engine(settings)
    try:
        factory = create_session_factory(engine)
        writer = results_writer()
        buy = Trade(di1f28, OCT_14, time(10), 1, 10, Decimal("89006.4625467350"), Decimal("0.10"))
        async with SqlAlchemyUnitOfWork(factory) as uow:
            # OQ-38, OQ-40: an ALL date writes positions first, then cash.
            await writer.write_positions_day(
                PositionsDay(
                    OCT_14,
                    (
                        PositionDay(
                            di1f28, 0, 10, Decimal("89006.4625467350"), Decimal("0.10"), (buy,)
                        ),
                    ),
                ),
                PortfolioValuation(
                    OCT_14,
                    (
                        AssetValuation(
                            di1f28,
                            Decimal("89006.4625467350"),
                            Decimal("890064.6254673500"),
                            ValuationStatus.COMPLETE,
                        ),
                    ),
                    Decimal("890064.6254673500"),
                    ValuationStatus.COMPLETE,
                ),
                {
                    di1f28: AssetPnLResult(
                        Decimal("0"),
                        Decimal("0.0000000000"),
                        Decimal("0.0000000000"),
                        COMPLETE,
                        frozenset(),
                    )
                },
                PortfolioPnLResult(
                    Decimal("0"),
                    Decimal("0.0000000000"),
                    Decimal("0.0000000000"),
                    Decimal("0.0000000000"),
                    COMPLETE,
                ),
                uow=uow,
            )
            await writer.write_cash_day(
                CashDay(
                    OCT_14,
                    Decimal("0"),
                    Decimal("-890064.6254673500"),
                    Decimal("1500000.00"),
                    Decimal("0.00"),
                    Decimal("609935.3745326500"),
                ),
                uow=uow,
            )
            await uow.commit()
        async with SqlAlchemyUnitOfWork(factory) as uow:
            # fixtures.ts positions[1]: DI1F28 held, DI1F29 bought 5 on 15/10.
            buy_f29 = Trade(
                di1f29, OCT_15, time(11), 2, 5, Decimal("82057.00"), Decimal("0.093203413834")
            )
            await writer.write_positions_day(
                PositionsDay(
                    OCT_15,
                    (
                        PositionDay(
                            di1f28, 10, 10, Decimal("89006.4625467350"), Decimal("0.10"), ()
                        ),
                        PositionDay(
                            di1f29,
                            0,
                            5,
                            Decimal("82057.00"),
                            Decimal("0.093203413834"),
                            (buy_f29,),
                        ),
                    ),
                ),
                PortfolioValuation(
                    OCT_15,
                    (
                        AssetValuation(
                            di1f28,
                            Decimal("89128.4824345118"),
                            Decimal("891284.8243451180"),
                            ValuationStatus.COMPLETE,
                        ),
                        AssetValuation(
                            di1f29,
                            Decimal("80206.1333187932"),
                            Decimal("401030.6665939660"),
                            ValuationStatus.COMPLETE,
                        ),
                    ),
                    Decimal("1292315.4909390840"),
                    ValuationStatus.COMPLETE,
                ),
                {
                    di1f28: AssetPnLResult(
                        Decimal("1220.1988777680"),
                        Decimal("0"),
                        Decimal("1220.1988777680"),
                        COMPLETE,
                        frozenset(),
                    ),
                    di1f29: AssetPnLResult(
                        Decimal("0"),
                        Decimal("-9254.3334060340"),
                        Decimal("-9254.3334060340"),
                        COMPLETE,
                        frozenset(),
                    ),
                },
                PortfolioPnLResult(
                    Decimal("1220.1988777680"),
                    Decimal("-9254.3334060340"),
                    Decimal("-8034.1345282660"),
                    Decimal("-8034.1345282660"),
                    COMPLETE,
                ),
                uow=uow,
            )
            await uow.commit()
    finally:
        await engine.dispose()


@pytest.fixture
def seeded(settings: Settings) -> Di1Catalogue:
    async def seed() -> Di1Catalogue:
        engine = create_engine(settings)
        try:
            catalogue = await seed_di1(create_session_factory(engine))
        finally:
            await engine.dispose()
        await _publish_fixture_days(
            settings, catalogue.instrument_ids["DI1F28"], catalogue.instrument_ids["DI1F29"]
        )
        return catalogue

    return asyncio.run(seed())


@pytest.fixture
def statuses() -> FakeDateStatusReader:
    processed = ChainStatus.PROCESSED
    return FakeDateStatusReader(
        {
            OCT_14: DateStatus(OCT_14, processed, processed, PUBLISHED_AT, PUBLISHED_AT),
            OCT_15: DateStatus(OCT_15, processed, None, PUBLISHED_AT, None),
        }
    )


@pytest.fixture
def client(
    settings: Settings, seeded: Di1Catalogue, statuses: FakeDateStatusReader
) -> Iterator[TestClient]:
    prices = FakePriceReader()
    prices.add(
        seeded.instrument_ids["DI1F28"], OCT_14, PriceSource.MANUAL, "89006.4625467350", "0.10"
    )
    prices.add(
        seeded.instrument_ids["DI1F28"], OCT_15, PriceSource.B3, "89128.4824345118", "0.0990"
    )
    prices.add(
        seeded.instrument_ids["DI1F29"], OCT_15, PriceSource.MANUAL, "80206.1333187932", "0.1045"
    )

    async def provide(request: Request) -> AsyncIterator[PortfolioService]:
        async with SqlAlchemyUnitOfWork(get_session_factory(request)) as uow:
            yield portfolio_query_service(
                uow,
                assets=asset_reader(uow.session),
                prices=prices,
                date_statuses=statuses,
                clock=FixedClock(OCT_16),
            )

    app = create_app(settings)
    app.include_router(create_router(provide))
    with TestClient(app) as client:
        yield client


def _get(client: TestClient, path: str, status: int = 200) -> Any:
    response = client.get(path)
    assert response.status_code == status, response.text
    return response.json()


def test_the_summary_matches_the_fixture(client: TestClient) -> None:
    assert _get(client, "/portfolio/summary?date=2026-10-14") == GOLDEN_SUMMARY_OCT_14


def test_a_date_never_processed_reads_null_and_not_processed(client: TestClient) -> None:
    body = _get(client, "/portfolio/summary?date=2026-10-16")

    assert body["cash"] == {
        "status": "NOT_PROCESSED",
        "balance": None,
        "trades_cash_flow": None,
        "deposits": None,
        "withdrawals": None,
        "published_at": None,
    }
    assert body["positions"]["status"] == "NOT_PROCESSED"
    assert body["positions"]["market_value"] is None
    assert body["aum"] is None


def test_positions_alone_have_no_aum(client: TestClient) -> None:
    # OQ-28: AUM is cash + market value of the same date; 15/10 has no published cash.
    body = _get(client, "/portfolio/summary?date=2026-10-15")

    assert body["cash"]["status"] == "NOT_PROCESSED"
    assert body["positions"]["market_value"] == "1292315.4909390840"
    assert body["aum"] is None


def test_the_positions_table_matches_the_fixture(client: TestClient, seeded: Di1Catalogue) -> None:
    body = _get(client, "/portfolio/positions?date=2026-10-14")

    assert body["date"] == "2026-10-14"
    assert body["status"] == "PROCESSED"
    assert body["published_at"] == PUBLISHED_AT_JSON
    (row,) = body["items"]
    assert UUID(row.pop("asset_id")) == seeded.instrument_ids["DI1F28"]
    assert row == GOLDEN_ROW_OCT_14


def test_the_15_10_table_matches_the_fixture(client: TestClient) -> None:
    # fixtures.ts positions[1].items, the asset ids aside.
    body = _get(client, "/portfolio/positions?date=2026-10-15")

    rows = [{k: v for k, v in row.items() if k != "asset_id"} for row in body["items"]]
    assert rows == [
        {
            "asset_code": "DI1F28",
            "maturity_date": "2028-01-03",
            "quantity": 10,
            "average_entry_pu": "89006.4625467350",
            "average_entry_rate": "0.10",
            "reference_source": "B3",
            "reference_pu": "89128.4824345118",
            "reference_rate": "0.0990",
            "financial_total": "891284.8243451180",
            "position_pnl": "1220.1988777680",
            "trades_pnl": "0",
            "daily_pnl": "1220.1988777680",
            "valuation_status": "COMPLETE",
            "pnl_status": "COMPLETE",
        },
        {
            "asset_code": "DI1F29",
            "maturity_date": "2029-01-02",
            "quantity": 5,
            "average_entry_pu": "82057.00",
            "average_entry_rate": "0.093203413834",
            "reference_source": "MANUAL",
            "reference_pu": "80206.1333187932",
            "reference_rate": "0.1045",
            "financial_total": "401030.6665939660",
            "position_pnl": "0",
            "trades_pnl": "-9254.3334060340",
            "daily_pnl": "-9254.3334060340",
            "valuation_status": "COMPLETE",
            "pnl_status": "COMPLETE",
        },
    ]


def test_a_date_never_processed_has_an_empty_table(client: TestClient) -> None:
    assert _get(client, "/portfolio/positions?date=2026-10-16") == {
        "date": "2026-10-16",
        "status": "NOT_PROCESSED",
        "published_at": None,
        "items": [],
    }


def test_the_pnl_series_has_every_date_with_the_range_sum(client: TestClient) -> None:
    # OQ-31 item 8, OQ-41: Σ daily_pnl from start_date; 16/10 is not processed and adds 0.
    body = _get(client, "/portfolio/pnl?start_date=2026-10-14&end_date=2026-10-16")

    assert body == {
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


def test_a_malformed_date_is_a_validation_error(client: TestClient) -> None:
    body = _get(client, "/portfolio/summary?date=14/10/2026", status=422)

    assert [e["code"] for e in body["errors"]] == ["VALIDATION_ERROR"]


def test_a_start_after_the_end_is_an_invalid_range(client: TestClient) -> None:
    body = _get(client, "/portfolio/pnl?start_date=2026-10-15&end_date=2026-10-14", status=422)

    assert body["errors"] == [
        {
            "code": "INVALID_RANGE",
            "message": "A data inicial deve ser anterior ou igual à data final.",
            "field": "start_date",
        }
    ]


@pytest.mark.parametrize(
    ("path", "field"),
    [
        ("/portfolio/summary?date=2026-10-17", "date"),
        ("/portfolio/positions?date=2026-10-17", "date"),
        ("/portfolio/pnl?start_date=2026-10-14&end_date=2026-10-17", "end_date"),
    ],
)
def test_a_read_after_today_is_a_future_date(client: TestClient, path: str, field: str) -> None:
    # OQ-35, with the clock fixed at 16/10/2026.
    body = _get(client, path, status=422)

    assert body["errors"] == [
        {"code": "FUTURE_DATE", "message": "A data não pode ser posterior a hoje.", "field": field}
    ]
