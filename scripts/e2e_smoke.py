"""End-to-end smoke test: the challenge example on the running stack, through the HTTP API.

Dated today (spec §15 D4): DI1 maturing today + 365 days, a 200.000 deposit, a buy of 1 contract
at 10% a.a., a 10% reference price (D2), then an ALL processing run for today (D3). Expected,
by hand (spec §4.1, OQ-3): PU = 100000 / 1.1 = 90909.0909090909; cash = 200000 − PU =
109090.9090909091 (109.090,91); AUM = cash + market value = 200000.

Needs an empty stack with the catalogue roots seeded (`scripts/seed_catalogue.sql`); `make e2e`
starts one, runs this and removes it. Standard library only, so it runs from any Python 3.12.

    python scripts/e2e_smoke.py --api http://127.0.0.1:18000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

EXPECTED_PU = Decimal("90909.0909090909")
EXPECTED_CASH = Decimal("109090.9090909091")
EXPECTED_AUM = Decimal("200000")
FINISHED = {"COMPLETED", "COMPLETED_WITH_ISSUES", "CANCELLED", "FAILED"}


class SmokeError(Exception):
    pass


def say(message: str, *, error: bool = False) -> None:
    (sys.stderr if error else sys.stdout).write(message + "\n")


def call(api: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        api + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        raise SmokeError(f"{method} {path} → {error.code}: {error.read().decode()}") from error


def check(label: str, actual: object, expected: object) -> None:
    status = "ok " if actual == expected else "FAIL"
    say(f"  [{status}] {label}: {actual} (expected {expected})")
    if actual != expected:
        raise SmokeError(f"{label}: {actual} != {expected}")


def wait_until_finished(api: str, request_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        run: dict[str, Any] = call(api, "GET", f"/api/processing/requests/{request_id}")
        if run["status"] in FINISHED:
            return run
        if time.monotonic() > deadline:
            raise SmokeError(
                f"run {request_id} still {run['status']} after {timeout:.0f}s:"
                " is the worker running?"
            )
        time.sleep(1)


def smoke(api: str, timeout: float) -> None:
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    maturity = today + timedelta(days=365)
    day = today.isoformat()
    say(f"Challenge example dated {day}, DI1 maturing {maturity.isoformat()} (365 days)")

    health = call(api, "GET", "/health")
    check("GET /health", health["status"], "ok")

    types = call(api, "GET", "/api/instrument-types")["items"]
    asset_class_id = next(
        c["id"]
        for t in types
        if t["code"] == "FUTURE"
        for c in t["asset_classes"]
        if c["code"] == "INTEREST_RATE_FUTURE"
    )

    product = call(
        api,
        "POST",
        "/api/products",
        {
            "asset_class_id": asset_class_id,
            "code": "DI1",
            "name": "Futuro de Depósito Interfinanceiro",
            "futures": {
                "face_value": "100000",
                "contract_multiplier": "1",
                "settlement_method": "CASH",
            },
        },
    )
    instrument = call(
        api,
        "POST",
        "/api/instruments",
        {"product_id": product["id"], "code": "DI1E2E", "maturity_date": maturity.isoformat()},
    )

    call(
        api,
        "POST",
        "/api/ledger/entries",
        {"type": "CASH", "date": day, "time": "09:00", "cash_amount": "200000"},
    )
    trade = call(
        api,
        "POST",
        "/api/ledger/entries",
        {
            "type": "TRADE",
            "asset_id": instrument["id"],
            "date": day,
            "time": "10:00",
            "signed_quantity": 1,
            "input_kind": "RATE",
            "execution_rate": "0.10",
        },
    )
    check("trade execution PU", Decimal(trade["execution_pu"]), EXPECTED_PU)

    price = call(
        api,
        "POST",
        "/api/reference-prices",
        {
            "asset_id": instrument["id"],
            "reference_date": day,
            "input_kind": "RATE",
            "rate": "0.10",
        },
    )
    check("reference PU", Decimal(price["pu"]), EXPECTED_PU)

    run = call(
        api,
        "POST",
        "/api/processing/requests",
        {"start_date": day, "end_date": day, "scope": "ALL"},
    )
    say(f"  processing run {run['id']} queued; waiting up to {timeout:.0f}s")
    run = wait_until_finished(api, run["id"], timeout)
    check("run status", run["status"], "COMPLETED")

    summary = call(api, "GET", f"/api/portfolio/summary?date={day}")
    check("cash status", summary["cash"]["status"], "PROCESSED")
    check("positions status", summary["positions"]["status"], "PROCESSED")
    check("cash balance", Decimal(summary["cash"]["balance"]), EXPECTED_CASH)
    check("AUM", Decimal(summary["aum"]), EXPECTED_AUM)

    positions = call(api, "GET", f"/api/portfolio/positions?date={day}")
    rows = positions["items"]
    check("open positions", len(rows), 1)
    check("position quantity", rows[0]["quantity"], 1)
    check("position reference PU", Decimal(rows[0]["reference_pu"]), EXPECTED_PU)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--timeout", type=float, default=60, help="seconds to wait for the run")
    args = parser.parse_args()
    try:
        smoke(args.api.rstrip("/"), args.timeout)
    except (SmokeError, urllib.error.URLError) as error:
        say(f"E2E SMOKE FAILED: {error}", error=True)
        return 1
    say("E2E SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
