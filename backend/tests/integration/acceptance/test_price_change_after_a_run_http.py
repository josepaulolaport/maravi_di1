"""Spec §13 case 17, second half: a price already used by a processed date may be corrected or
removed; that marks nothing, the date keeps its status, time and figures until the user
reprocesses it, and the Carteira shows the current preferred price beside the old figures
(OQ-25, OQ-30, OQ-31).

Today is 01/01/2027 (the challenge date). DI1F28 matures on 01/01/2028, 365 calendar days away.
The user deposits 200.000, buys 1 contract at 10% a.a. and enters a MANUAL price at 10%; the B3
price of the day is 11%. The worker runs in-process with the real composition (OQ-45, OQ-46).

Hand computation (spec §4.1, OQ-3; CLAUDE.md §2):
- PU(10%) = 100000 / 1.10 = 90909.0909090909; cash = 200000 − 90909.0909090909 = 109090.9090909091.
- First run, MANUAL 10% preferred: Q[D−1] = 0 so position P&L = 0 (OQ-4); trades P&L =
  1 × (90909.0909090909 − 90909.0909090909) = 0; market value 90909.0909090909;
  AUM = 109090.9090909091 + 90909.0909090909 = 200000.
- After the MANUAL price is corrected to 12% and then removed, B3 prevails (spec §5): the
  Carteira shows B3's PU and rate, but every processed figure is the first run's. While the
  corrected price, set after the run, is the current one, its row is marked (A10).
- Reprocessing values the day at B3's PU(11%) = 100000 / 1.11: trades P&L = PU(11%) − PU(10%),
  market value PU(11%), AUM = cash + PU(11%).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from di1.shared.clock import SAO_PAULO
from tests.integration.acceptance.support import (
    acceptance_app,
    cash_body,
    create_di1_product,
    create_instrument,
    date_statuses,
    expected_pu,
    price_body,
    run_worker,
    sql,
    trade_body,
)

TODAY = date(2027, 1, 1)
DAY = "2027-01-01"
FIRST_RUN = datetime.combine(TODAY, time(13, 0), tzinfo=SAO_PAULO)
REPROCESSING = datetime.combine(TODAY, time(14, 0), tzinfo=SAO_PAULO)

PU_10 = Decimal("90909.0909090909")
CASH = Decimal("109090.9090909091")


@pytest.fixture
def app() -> Iterator[tuple[TestClient, str]]:
    with acceptance_app(TODAY) as app:
        yield app


def _post(client: TestClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def _process(client: TestClient, database_url: str, now: datetime) -> dict[str, Any]:
    """Queues ALL [DAY, DAY] over HTTP and lets the worker drain it; returns the finished run."""
    queued = _post(
        client, "/api/processing/requests", {"scope": "ALL", "start_date": DAY, "end_date": DAY}
    )
    assert queued["status"] == "QUEUED"
    run_worker(database_url, now)
    response = client.get(f"/api/processing/requests/{queued['id']}")
    assert response.status_code == 200, response.text
    run: dict[str, Any] = response.json()
    return run


def _carteira(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = client.get("/api/portfolio/summary", params={"date": DAY})
    positions = client.get("/api/portfolio/positions", params={"date": DAY})
    assert summary.status_code == 200, summary.text
    assert positions.status_code == 200, positions.text
    [row] = positions.json()["items"]
    return summary.json(), row


def _figures(summary: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Everything the run published for the day, as Decimals (statuses and times as read)."""

    def number(value: str | None) -> Decimal | None:
        return None if value is None else Decimal(value)

    return {
        "cash.status": summary["cash"]["status"],
        "cash.published_at": summary["cash"]["published_at"],
        "cash.balance": number(summary["cash"]["balance"]),
        "positions.status": summary["positions"]["status"],
        "positions.published_at": summary["positions"]["published_at"],
        "positions.market_value": number(summary["positions"]["market_value"]),
        "positions.daily_pnl": number(summary["positions"]["daily_pnl"]),
        "positions.cumulative_pnl": number(summary["positions"]["cumulative_pnl"]),
        "aum": number(summary["aum"]),
        "row.quantity": row["quantity"],
        "row.average_entry_pu": number(row["average_entry_pu"]),
        "row.financial_total": number(row["financial_total"]),
        "row.position_pnl": number(row["position_pnl"]),
        "row.trades_pnl": number(row["trades_pnl"]),
        "row.daily_pnl": number(row["daily_pnl"]),
    }


def _reference(row: dict[str, Any]) -> tuple[str, Decimal, Decimal]:
    return row["reference_source"], Decimal(row["reference_pu"]), Decimal(row["reference_rate"])


def test_a_used_price_corrected_or_removed_keeps_the_processed_date_until_reprocessing(
    app: tuple[TestClient, str],
) -> None:
    client, database_url = app
    asset = create_instrument(client, create_di1_product(client), "DI1F28", "2028-01-01")
    pu_11, pu_12 = Decimal(expected_pu("0.11", 365)), Decimal(expected_pu("0.12", 365))
    _post(client, "/api/ledger/entries", cash_body(DAY, "09:00", "200000"))
    _post(client, "/api/ledger/entries", trade_body(asset, DAY, "10:00", 1, rate="0.10"))
    manual = _post(client, "/api/reference-prices", price_body(asset, DAY, rate="0.10"))
    sql(  # B3 has no HTTP route; the import would insert it like this
        database_url,
        "INSERT INTO prices.reference_prices (asset_id, reference_date, source, input_kind, pu,"
        " rate) VALUES (%s, %s, 'B3', 'RATE', %s, '0.11')",
        (asset, DAY, str(pu_11)),
    )

    first = _process(client, database_url, FIRST_RUN)

    # The setup run must have succeeded before its figures mean anything.
    assert (first["status"], first["error_code"]) == ("COMPLETED", None), first
    assert date_statuses(database_url) == {TODAY: ("PROCESSED", "PROCESSED")}
    summary, row = _carteira(client)
    processed = _figures(summary, row)
    assert processed == {
        "cash.status": "PROCESSED",
        "cash.published_at": processed["cash.published_at"],
        "cash.balance": CASH,
        "positions.status": "PROCESSED",
        "positions.published_at": processed["positions.published_at"],
        "positions.market_value": PU_10,
        "positions.daily_pnl": Decimal(0),
        "positions.cumulative_pnl": Decimal(0),
        "aum": Decimal(200000),
        "row.quantity": 1,
        "row.average_entry_pu": PU_10,
        "row.financial_total": PU_10,
        "row.position_pnl": Decimal(0),
        "row.trades_pnl": Decimal(0),
        "row.daily_pnl": Decimal(0),
    }
    assert datetime.fromisoformat(processed["cash.published_at"]) == FIRST_RUN
    assert datetime.fromisoformat(processed["positions.published_at"]) == FIRST_RUN
    assert _reference(row) == ("MANUAL", PU_10, Decimal("0.10"))
    assert row["reference_price_changed"] is False

    # Correcting the used price is allowed and marks nothing (OQ-25, OQ-31).
    corrected = _post(client, "/api/reference-prices", price_body(asset, DAY, rate="0.12"))
    # created_at is the database's now(), not the test's injected 2027 clock: put the correction
    # where the wall clock would, half an hour after the first run.
    sql(
        database_url,
        "UPDATE prices.reference_prices SET created_at = %s WHERE id = %s",
        (FIRST_RUN + timedelta(minutes=30), corrected["id"]),
    )
    summary, row = _carteira(client)

    assert _figures(summary, row) == processed
    assert _reference(row) == ("MANUAL", pu_12, Decimal("0.12"))  # the current price (OQ-30)
    assert row["reference_price_changed"] is True  # set after the run: reprocess (A10)
    assert date_statuses(database_url) == {TODAY: ("PROCESSED", "PROCESSED")}

    # Removing it lets B3 prevail, and still marks nothing.
    assert corrected["id"] != manual["id"]
    removed = client.delete(f"/api/reference-prices/{corrected['id']}")
    summary, row = _carteira(client)

    assert removed.status_code == 204, removed.text
    assert _figures(summary, row) == processed
    assert _reference(row) == ("B3", pu_11, Decimal("0.11"))
    assert date_statuses(database_url) == {TODAY: ("PROCESSED", "PROCESSED")}
    # No job was created and no pendência raised by either write.
    assert [r["id"] for r in client.get("/api/processing/requests").json()["items"]] == [
        first["id"]
    ]
    assert client.get("/api/processing/issues").json()["items"] == []

    # Only the user's reprocessing publishes the day again, at the current preferred price.
    second = _process(client, database_url, REPROCESSING)

    assert (second["status"], second["error_code"]) == ("COMPLETED", None), second
    assert date_statuses(database_url) == {TODAY: ("PROCESSED", "PROCESSED")}
    summary, row = _carteira(client)
    reprocessed = _figures(summary, row)
    assert reprocessed == processed | {
        "cash.published_at": reprocessed["cash.published_at"],
        "positions.published_at": reprocessed["positions.published_at"],
        "positions.market_value": pu_11,
        "positions.daily_pnl": pu_11 - PU_10,
        "positions.cumulative_pnl": pu_11 - PU_10,
        "aum": CASH + pu_11,
        "row.financial_total": pu_11,
        "row.trades_pnl": pu_11 - PU_10,
        "row.daily_pnl": pu_11 - PU_10,
    }
    assert datetime.fromisoformat(reprocessed["cash.published_at"]) == REPROCESSING
    assert datetime.fromisoformat(reprocessed["positions.published_at"]) == REPROCESSING
    assert _reference(row) == ("B3", pu_11, Decimal("0.11"))
    assert row["reference_price_changed"] is False
