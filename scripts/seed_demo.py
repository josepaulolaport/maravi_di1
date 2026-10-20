"""Demo data: two weeks of DI1 history, written through the HTTP API on the first `compose up`.

The Compose `demo` service runs it after the API is up (`DI1_DEMO=0` turns it off; `make e2e` does,
to keep its ledger empty). On an empty ledger it writes, from today − 14 to today (São Paulo), so
dates are relative to the first `up`: three January DI1 contracts (the next three years, e.g.
DI1F27, DI1F28, DI1F29 in 2026), deposits, a withdrawal, trades and MANUAL reference prices, all
through the API, so every pricing and validation rule applies. On a non-empty ledger it adds
nothing and exits 0 ("already loaded"), so every later `up` is a no-op. It queues no processing
and writes no positions or P&L: the user processes today − 14 .. today in the Central de Controle.

The trades exercise the accounting rules (spec §7): buys typed as a rate and as a PU, a partial
sale (the average PU stays), a sale that crosses zero into a short, two trades of one contract on
one day ordered by entry_time (a buy, then a sale), and, as in the challenge example, a 200.000
deposit and a buy of 1 contract at 10% (the contract does not mature in 365 days, so the
challenge's figures do not appear; `make e2e` reproduces them). Prices are typed as a rate for
every calendar day, weekends included, from each contract's first trade, with one deliberate gap
(the longest contract on today − 5), so processing shows a Pendência and ends
COMPLETED_WITH_ISSUES.

A PU-typed trade sends a round PU near the market. The script derives it from the DC/365 formula
only to pick a plausible typed value; the API stores the typed PU and computes the rate itself.

Fails when one of its contract codes exists with another maturity. Standard library only.

    python3 scripts/seed_demo.py --api http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, getcontext
from typing import Any
from zoneinfo import ZoneInfo

getcontext().prec = 34

DAYS = 14
FACE_VALUE = Decimal("100000")


@dataclass(frozen=True)
class Contract:
    code: str
    maturity: date  # first business day of January (DI1 code F = January)
    base_rate: Decimal  # the reference rate the daily prices drift around


BASE_RATES = (Decimal("0.1450"), Decimal("0.1000"), Decimal("0.1350"))
GAP_OFFSET = 5  # the longest contract has no reference price on today − 5


def first_business_day_of_january(year: int) -> date:
    """1 January is a holiday; the first weekday after it (other holidays ignored)."""
    day = date(year, 1, 2)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def contracts(today: date) -> tuple[Contract, Contract, Contract]:
    """The January contracts of the next three years: always after today."""
    short, middle, long = (
        Contract(
            f"DI1F{(today.year + n) % 100:02d}",
            first_business_day_of_january(today.year + n),
            BASE_RATES[n - 1],
        )
        for n in (1, 2, 3)
    )
    return short, middle, long


class DemoError(Exception):
    pass


class AlreadyLoadedError(Exception):
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
        raise DemoError(f"{method} {path} → {error.code}: {error.read().decode()}") from error


def round_pu(contract: Contract, day: date, rate: Decimal) -> str:
    """A round PU (2 dp) near ``rate`` on ``day``, to send as a typed PU."""
    days = (contract.maturity - day).days
    pu = FACE_VALUE / (1 + rate) ** (Decimal(days) / Decimal(365))
    return str(pu.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def reference_rate(contract: Contract, offset: int) -> str:
    """The daily reference rate: the base plus a small deterministic drift (± 2 bp)."""
    drift = Decimal((offset * 7) % 5 - 2) / Decimal(10000)
    return str(contract.base_rate + drift)


def demo(api: str) -> None:
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    start = today - timedelta(days=DAYS)

    def day(offset: int) -> date:
        """today − offset."""
        return today - timedelta(days=offset)

    short, middle, long = contracts(today)
    all_contracts = (short, middle, long)

    existing = call(
        api, "GET", f"/api/ledger/entries?start_date=1900-01-01&end_date={today}&limit=1"
    )
    if existing["items"]:
        raise AlreadyLoadedError

    products = call(api, "GET", "/api/products?instrument_type=FUTURE")["items"]
    product = next((p for p in products if p["code"] == "DI1"), None)
    if product is None:
        raise DemoError("no DI1 product: is the catalogue seeded (docker compose up, make seed)?")

    # Reuse a contract left by an interrupted run (the ledger is still empty), else create it.
    listed = call(api, "GET", f"/api/instruments?product_id={product['id']}")["items"]
    ids: dict[str, str] = {i["code"]: i["id"] for i in listed}
    by_code = {c.code: c for c in all_contracts}
    say(f"Demo data from {start} to {today} (São Paulo)")
    for contract in all_contracts:
        if contract.code in ids:
            found = next(i for i in listed if i["code"] == contract.code)
            if found["maturity_date"] != contract.maturity.isoformat():
                raise DemoError(
                    f"{contract.code} exists with maturity {found['maturity_date']}, not"
                    f" {contract.maturity}; run it on a fresh stack (down -v, up)"
                )
        else:
            created = call(
                api,
                "POST",
                "/api/instruments",
                {
                    "product_id": product["id"],
                    "code": contract.code,
                    "maturity_date": contract.maturity.isoformat(),
                },
            )
            ids[contract.code] = created["id"]
        say(f"  contract {contract.code}, maturity {contract.maturity}")

    def cash(offset: int, time: str, amount: str, label: str, description: str) -> None:
        call(
            api,
            "POST",
            "/api/ledger/entries",
            {
                "type": "CASH",
                "date": day(offset).isoformat(),
                "time": time,
                "cash_amount": amount,
                "description": description,  # shown in Lançamentos (OQ-51)
            },
        )
        say(f"  {day(offset)} {time} {label} {amount} ({description})")

    def trade(
        offset: int,
        time: str,
        code: str,
        quantity: int,
        label: str,
        *,
        rate: str = "",
        pu_near: str = "",
    ) -> None:
        """A trade typed as ``rate``, or as a round PU near the rate ``pu_near``."""
        body: dict[str, Any] = {
            "type": "TRADE",
            "date": day(offset).isoformat(),
            "time": time,
            "asset_id": ids[code],
            "signed_quantity": quantity,
        }
        if rate:
            body |= {"input_kind": "RATE", "execution_rate": rate}
        else:
            pu = round_pu(by_code[code], day(offset), Decimal(pu_near))
            body |= {"input_kind": "PU", "execution_pu": pu}
        entry = call(api, "POST", "/api/ledger/entries", body)
        typed = f"rate {rate}" if rate else f"PU {body['execution_pu']}"
        say(
            f"  {day(offset)} {time} {code} {quantity:+d} ({typed} → PU {entry['execution_pu']},"
            f" rate {entry['execution_rate']}): {label}"
        )

    say("Ledger:")
    cash(14, "09:00", "1000000", "opening deposit", "Aporte inicial")
    s, m, lg = short.code, middle.code, long.code
    trade(14, "10:00", s, 4, "buy, typed as a rate", rate="0.1450")
    trade(14, "11:00", lg, 3, "buy, typed as a PU", pu_near="0.1350")
    trade(12, "10:30", s, 2, "buy more, typed as a PU (new average)", pu_near="0.1460")
    cash(10, "09:00", "200000", "deposit, as in the challenge example", "Aporte do exemplo")
    trade(10, "10:00", m, 1, "buy 1 at 10%, as in the challenge example", rate="0.10")
    trade(8, "10:15", s, -3, "partial sale (average kept)", rate="0.1445")
    trade(8, "11:00", lg, 2, "buy: 3 → 5, new average", rate="0.1352")
    trade(8, "14:30", lg, -1, "same contract, same day, later time: 5 → 4", rate="0.1355")
    cash(6, "09:00", "300000", "second deposit", "Segundo aporte")
    trade(4, "11:00", lg, -7, "sale crossing zero: 4 → −3 (short)", pu_near="0.1348")
    cash(2, "16:00", "-150000", "withdrawal", "Retirada parcial")

    first_trade = {s: 14, m: 10, lg: 14}
    say("Reference prices (MANUAL, typed as a rate, every calendar day):")
    for contract in all_contracts:
        written = 0
        for offset in range(first_trade[contract.code], -1, -1):
            if contract is long and offset == GAP_OFFSET:
                continue
            call(
                api,
                "POST",
                "/api/reference-prices",
                {
                    "asset_id": ids[contract.code],
                    "reference_date": day(offset).isoformat(),
                    "input_kind": "RATE",
                    "rate": reference_rate(contract, offset),
                },
            )
            written += 1
        say(f"  {contract.code}: {written} prices, {day(first_trade[contract.code])} to {today}")
    say(f"  deliberate gap: {lg} has no price on {day(GAP_OFFSET)}")
    say(
        f"Nothing was processed. Central de Controle → Processamentos: process Tudo from {start}"
        f" to {today}; expect Concluído com pendências (the {lg} gap on {day(GAP_OFFSET)})."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="API base URL")
    args = parser.parse_args()
    if os.environ.get("DI1_DEMO", "1") == "0":
        say("DEMO DATA SKIPPED (DI1_DEMO=0)")
        return 0
    try:
        demo(args.api.rstrip("/"))
    except AlreadyLoadedError:
        say("DEMO DATA ALREADY LOADED: the ledger has entries; nothing added")
        return 0
    except (DemoError, urllib.error.URLError, TimeoutError, ValueError) as error:
        say(f"DEMO DATA NOT CREATED: {error}", error=True)
        return 1
    say("DEMO DATA CREATED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
