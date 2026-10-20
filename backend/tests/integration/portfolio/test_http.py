"""Portfolio HTTP routes against PostgreSQL 16, through the real app: status and problem shape
(RFC 9457, OQ-15) of the errors the routes answer.

The JSON shapes are tested on the schemas (tests/unit/portfolio/test_http_schemas.py), the reads
on the service (tests/unit/portfolio/test_queries.py), FUTURE_DATE on the three routes in the
phase-2 acceptance tests (test_challenge_example_http.py), and the published rows in
test_published_rows.py."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from di1.composition.dependencies import get_unit_of_work
from di1.main import create_app
from di1.modules.asset.dependencies import build_asset_reader
from di1.modules.portfolio.dependencies import build_portfolio_service
from di1.modules.portfolio.presentation.http.router import create_router
from di1.modules.portfolio.public import PortfolioService
from di1.platform.config import Settings
from di1.platform.database.unit_of_work import UnitOfWork
from tests.support.fakes import FakeClock, FakeDateStatusReader, FakePriceReader
from tests.support.http import problem

REQUEST_UOW = Depends(get_unit_of_work)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    def provide(uow: UnitOfWork = REQUEST_UOW) -> PortfolioService:
        return build_portfolio_service(
            uow,
            assets=build_asset_reader(uow.session),
            prices=FakePriceReader(),
            date_statuses=FakeDateStatusReader(),
            clock=FakeClock(date(2026, 10, 16)),
        )

    app = create_app(settings)
    app.include_router(create_router(get_service=provide))
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(
            "/portfolio/summary?date=14/10/2026", {"code": "VALIDATION_ERROR"}, id="malformed-date"
        ),
        pytest.param(
            "/portfolio/pnl?start_date=2026-10-15&end_date=2026-10-14",
            {
                "code": "INVALID_RANGE",
                "message": "A data inicial deve ser anterior ou igual à data final.",
                "field": "start_date",
            },
            id="start-after-end",
        ),
        # 2016-10-08 .. 2026-10-16 is 3,661 dates, ends included.
        pytest.param(
            "/portfolio/pnl?start_date=2016-10-08&end_date=2026-10-16",
            {
                "code": "INVALID_RANGE",
                "message": "O período deve ter no máximo 3.660 dias.",
                "field": "end_date",
            },
            id="range-longer-than-3660-dates",
        ),
    ],
)
def test_an_invalid_read_is_a_422_problem(
    client: TestClient, path: str, expected: dict[str, str]
) -> None:
    (error,) = problem(client.get(path), 422)["errors"]
    assert {key: error[key] for key in expected} == expected
