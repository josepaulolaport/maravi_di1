"""``scripts/seed_demo.py`` decides "already loaded" by its completion marker, the last price it
writes, not by "any ledger entry": a run that died part-way is reported, never taken as done."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "seed_demo.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_demo", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_demo"] = module
    spec.loader.exec_module(module)
    return module


seed_demo = _load()

TODAY = date(2026, 10, 19)
API = "http://api"


class FakeApi:
    """The routes the script reads and writes, in memory."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self.instruments: list[dict[str, Any]] = []
        self.prices: list[dict[str, Any]] = []
        self.fail_on_price: int | None = None
        """Raise on this price POST (0-based): the run dies part-way."""

    def __call__(self, api: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = urlsplit(path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        route = (method, url.path)
        if route == ("GET", "/api/ledger/entries"):
            ordered = sorted(self.entries, key=lambda e: (e["date"], e["time"], e["seq"]))
            if query.get("order", "desc") == "desc":
                ordered.reverse()
            return {"items": ordered[: int(query["limit"])], "next_cursor": None}
        if route == ("POST", "/api/ledger/entries"):
            assert body is not None
            entry = {
                **body,
                "time": body["time"] + ":00",
                "seq": len(self.entries) + 1,
                "execution_pu": body.get("execution_pu", "95000"),
                "execution_rate": body.get("execution_rate", "0.1"),
            }
            self.entries.append(entry)
            return entry
        if route == ("GET", "/api/products"):
            return {"items": [{"id": "di1", "code": "DI1"}]}
        if route == ("GET", "/api/instruments"):
            return {"items": self.instruments}
        if route == ("POST", "/api/instruments"):
            assert body is not None
            created = {"id": body["code"], "code": body["code"], **body}
            self.instruments.append(created)
            return created
        if route == ("POST", "/api/reference-prices"):
            assert body is not None
            if self.fail_on_price == len(self.prices):
                raise seed_demo.DemoError("POST /api/reference-prices → 503: down")
            self.prices.append(body)
            return body
        if route == ("GET", "/api/reference-prices"):
            return {
                "items": [
                    {"reference_date": p["reference_date"]}
                    for p in self.prices
                    if p["asset_id"] == query["asset_id"]
                    and query["start_date"] <= p["reference_date"] <= query["end_date"]
                ]
            }
        raise AssertionError(f"unexpected {method} {path}")


def run(api: FakeApi, today: date = TODAY) -> int:
    return int(seed_demo.run(API, call=api, today=today))


def test_an_empty_ledger_gets_the_demo_and_a_second_run_adds_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = FakeApi()

    assert run(api) == 0
    written = (len(api.entries), len(api.prices))
    assert run(api, TODAY + timedelta(days=30)) == 0  # a later `up`, on another day

    assert (len(api.entries), len(api.prices)) == written
    assert "DEMO DATA ALREADY LOADED" in capsys.readouterr().out


def test_a_failed_run_exits_0_and_says_why_so_the_ui_still_starts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The web service waits for the demo to complete successfully: a failure must never block
    the UI, so the demo exits 0 and prints why its data is not loaded."""
    api = FakeApi()
    api.fail_on_price = 20  # the ledger is complete, the prices are not

    assert run(api) == 0
    assert "DEMO DATA NOT LOADED: POST /api/reference-prices" in capsys.readouterr().err


def test_a_run_that_died_before_its_last_price_is_reported_never_loaded_again(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = FakeApi()
    api.fail_on_price = 20
    run(api)
    capsys.readouterr()

    api.fail_on_price = None
    entries = len(api.entries)
    assert run(api, TODAY + timedelta(days=1)) == 0  # a later `up`

    assert len(api.entries) == entries  # nothing written twice, never "already loaded"
    err = capsys.readouterr().err
    assert "DEMO DATA NOT LOADED" in err
    assert "stopped before its last price" in err


def test_an_unreachable_api_exits_0_and_says_why(capsys: pytest.CaptureFixture[str]) -> None:
    def down(*_: object, **__: object) -> None:
        raise seed_demo.urllib.error.URLError("connection refused")

    assert int(seed_demo.run(API, call=down, today=TODAY)) == 0
    assert "DEMO DATA NOT LOADED" in capsys.readouterr().err


def test_a_ledger_that_is_not_the_demos_is_left_alone(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApi()
    api.entries.append(
        {"type": "CASH", "date": "2026-10-01", "time": "15:00:00", "seq": 1, "cash_amount": "5"}
    )

    assert run(api) == 0

    assert len(api.entries) == 1
    assert api.prices == []
    assert "nothing added" in capsys.readouterr().out
