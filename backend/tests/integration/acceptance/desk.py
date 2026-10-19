"""A user's desk for the processing scenarios: register contracts, entries and prices through
``/api``, queue processing over HTTP, let the one worker drain the queue in-process with the real
composition (``support.run_worker``, OQ-45/OQ-46), then read the Carteira and the Pendências.

Every figure crosses as a JSON decimal string and is returned here as `Decimal` (or ``None``),
never float or text. `Desk.process` returns the finished run; each scenario asserts its status
and `Desk.statuses` before any figure, so a setup run that failed cannot pass silently.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from di1.shared.clock import SAO_PAULO
from tests.integration.acceptance.support import (
    cash_body,
    create_di1_product,
    create_instrument,
    date_statuses,
    price_body,
    run_worker,
    sql,
    trade_body,
)

Figure = Decimal | None


def number(value: str | None) -> Figure:
    return None if value is None else Decimal(value)


class Desk:
    def __init__(self, client: TestClient, database_url: str, today: date) -> None:
        self.client = client
        self.database_url = database_url
        self.today = today
        self._product_id: str | None = None
        self._runs = 0

    # Setup through the API ------------------------------------------------------------------

    def contract(self, code: str, maturity: str) -> str:
        if self._product_id is None:
            self._product_id = create_di1_product(self.client)
        return create_instrument(self.client, self._product_id, code, maturity)

    def trade(
        self,
        asset: str,
        on: date,
        quantity: int,
        *,
        pu: str | None = None,
        rate: str | None = None,
        at: str = "10:00",
    ) -> dict[str, Any]:
        return self.post(
            "/api/ledger/entries", trade_body(asset, on.isoformat(), at, quantity, rate=rate, pu=pu)
        )

    def cash(self, on: date, amount: str, *, at: str = "09:00") -> dict[str, Any]:
        return self.post("/api/ledger/entries", cash_body(on.isoformat(), at, amount))

    def price(
        self, asset: str, on: date, *, pu: str | None = None, rate: str | None = None
    ) -> dict[str, Any]:
        return self.post(
            "/api/reference-prices", price_body(asset, on.isoformat(), rate=rate, pu=pu)
        )

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(path, json=body)
        assert response.status_code == 201, response.text
        created: dict[str, Any] = response.json()
        return created

    # Processing ------------------------------------------------------------------------------

    def queue(self, scope: str, start: date, end: date) -> dict[str, Any]:
        queued = self.post(
            "/api/processing/requests",
            {"scope": scope, "start_date": start.isoformat(), "end_date": end.isoformat()},
        )
        assert queued["status"] == "QUEUED", queued
        return queued

    def work(self) -> datetime:
        """The worker starts (recover, then drain); each start is one minute after the last,
        from 13:00 of today, so processing times tell the runs apart."""
        self._runs += 1
        now = datetime.combine(self.today, time(13, 0), tzinfo=SAO_PAULO) + timedelta(
            minutes=self._runs
        )
        run_worker(self.database_url, now)
        return now

    def process(self, scope: str, start: date, end: date) -> dict[str, Any]:
        """Queues ``scope`` [start, end] over HTTP, lets the worker drain it, returns the run."""
        queued = self.queue(scope, start, end)
        self.work()
        return self.run(queued["id"])

    def run(self, request_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/processing/requests/{request_id}")
        assert response.status_code == 200, response.text
        run: dict[str, Any] = response.json()
        return run

    def statuses(self) -> dict[date, tuple[str | None, str | None]]:
        """``{date: (cash, positions)}`` from ``processing.date_status`` (OQ-23, OQ-31)."""
        return date_statuses(self.database_url)

    def issues(self) -> list[tuple[str, str | None, date, date | None]]:
        """Pendências as ``(type, asset code, earliest affected date, required price date)``."""
        response = self.client.get("/api/processing/issues")
        assert response.status_code == 200, response.text
        return sorted(
            (
                i["issue_type"],
                i["asset_code"],
                date.fromisoformat(i["affected_date"]),
                None
                if i["required_price_date"] is None
                else date.fromisoformat(i["required_price_date"]),
            )
            for i in response.json()["items"]
        )

    # The Carteira ----------------------------------------------------------------------------

    def summary(self, on: date) -> dict[str, Any]:
        response = self.client.get("/api/portfolio/summary", params={"date": on.isoformat()})
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    def aum(self, on: date) -> Figure:
        return number(self.summary(on)["aum"])

    def cash_balance(self, on: date) -> Figure:
        return number(self.summary(on)["cash"]["balance"])

    def portfolio_pnl(self, on: date) -> dict[str, Any]:
        """The positions side of the summary: market value and P&L as Decimal, statuses as read."""
        positions = self.summary(on)["positions"]
        return {
            key: number(value) if key in _FIGURES else value for key, value in positions.items()
        }

    def positions(self, on: date) -> dict[str, dict[str, Any]]:
        """The position table by asset code, figures as Decimal."""
        response = self.client.get("/api/portfolio/positions", params={"date": on.isoformat()})
        assert response.status_code == 200, response.text
        return {
            row["asset_code"]: {
                key: number(value) if key in _ROW_FIGURES else value for key, value in row.items()
            }
            for row in response.json()["items"]
        }

    def pnl_series(self, start: date, end: date) -> list[dict[str, Any]]:
        response = self.client.get(
            "/api/portfolio/pnl",
            params={"start_date": start.isoformat(), "end_date": end.isoformat()},
        )
        assert response.status_code == 200, response.text
        return [
            {
                key: number(value) if key in _SERIES_FIGURES else value
                for key, value in point.items()
            }
            for point in response.json()["items"]
        ]

    def sql(self, statement: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        return sql(self.database_url, statement, params)


_FIGURES = {"market_value", "position_pnl", "trades_pnl", "daily_pnl", "cumulative_pnl"}
_ROW_FIGURES = {
    "average_entry_pu",
    "average_entry_rate",
    "reference_pu",
    "reference_rate",
    "financial_total",
    "position_pnl",
    "trades_pnl",
    "daily_pnl",
}
_SERIES_FIGURES = {"daily_pnl", "cumulative_pnl", "range_cumulative_pnl"}
