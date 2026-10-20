"""Processing's HTTP shapes against the frozen frontend contract (``processing.ts`` at 57b4df0)
and its MSW fixtures (``frontend/src/api/mocks/fixtures.ts``): the same keys, ISO dates and
instants, problem+json errors (spec §12, OQ-15, OQ-26 item 8)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from di1.composition.errors import install_problem_handlers
from di1.modules.processing.domain.issues import IssueRecord, IssueType
from di1.modules.processing.presentation.http.router import create_router
from di1.modules.processing.public import Chain, ChainStatus, ProcessingStatus
from tests.unit.processing.fakes import Harness, date_status

# The keys of the fixtures' objects (fixtures.ts `job(...)`, `issues`; processing.ts), with
# OQ-31 applied: an issue has no `chain`; OQ-40: a run carries `failed_date` and `failed_chain`.
REQUEST_KEYS = {
    "id",
    "scope",
    "start_date",
    "end_date",
    "status",
    "progress_date",
    "error_code",
    "error_message",
    "created_at",
    "updated_at",
    "dispatched_at",
    "started_at",
    "finished_at",
    "cancel_requested_at",
    "failed_date",
    "failed_chain",
}
PREVIEW_KEYS = {
    "start_date",
    "end_date",
    "total_days",
    "scope",
    "predecessor_date",
    "predecessor",
}
ISSUE_KEYS = {
    "id",
    "issue_type",
    "asset_id",
    "asset_code",
    "affected_date",
    "required_price_date",
    "request_id",
}
PROBLEM_KEYS = {"type", "title", "status", "detail", "errors"}
BODY = {"start_date": "2026-10-14", "end_date": "2026-10-16", "scope": "ALL"}


@pytest.fixture
def harness() -> Harness:
    return Harness()


@pytest.fixture
def client(harness: Harness) -> Iterator[TestClient]:
    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(create_router(get_service=lambda: harness.service))
    with TestClient(app) as client:
        yield client


def _assert_request_shape(body: dict[str, Any]) -> None:
    assert set(body) == REQUEST_KEYS
    UUID(body["id"])
    date.fromisoformat(body["start_date"])
    date.fromisoformat(body["end_date"])
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None
    assert datetime.fromisoformat(body["updated_at"]).tzinfo is not None


def _problem(response: Any, status: int) -> list[dict[str, Any]]:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert set(body) == PROBLEM_KEYS
    errors: list[dict[str, Any]] = body["errors"]
    return errors


def test_post_request_answers_201_with_the_queued_run(client: TestClient) -> None:
    response = client.post("/processing/requests", json=BODY)

    assert response.status_code == 201
    body = response.json()
    _assert_request_shape(body)
    assert {k: body[k] for k in ("scope", "start_date", "end_date", "status")} == {
        "scope": "ALL",
        "start_date": "2026-10-14",
        "end_date": "2026-10-16",
        "status": "QUEUED",
    }
    assert body["progress_date"] is None
    assert (body["failed_date"], body["failed_chain"]) == (None, None)
    assert body["dispatched_at"] is None


@pytest.mark.parametrize(
    ("body", "field", "code"),
    [
        pytest.param(
            {**BODY, "scope": "EVERYTHING"}, "scope", "VALIDATION_ERROR", id="unknown scope"
        ),
        pytest.param(
            {"start_date": "2026-10-14", "end_date": "2026-10-16"},
            "scope",
            "VALIDATION_ERROR",
            id="no scope",
        ),
        pytest.param(
            {**BODY, "start_date": "14/10/2026"},
            "start_date",
            "VALIDATION_ERROR",
            id="not an ISO date",
        ),
        # One of the service's own refusals, to show it answers as a problem too; the range
        # rules themselves are tested on the service (test_processing_service.py).
        pytest.param(
            {**BODY, "start_date": "2026-10-17"},
            "start_date",
            "INVALID_RANGE",
            id="start after end",
        ),
    ],
)
def test_post_request_refuses_a_malformed_range(
    client: TestClient, harness: Harness, body: dict[str, str], field: str, code: str
) -> None:
    errors = _problem(client.post("/processing/requests", json=body), 422)

    assert [(e["code"], e["field"]) for e in errors] == [(code, field)]
    assert harness.requests.rows == {}


def test_get_requests_answers_a_page_of_runs_and_a_cursor(client: TestClient) -> None:
    """The shape only: the keyset order is tested on PostgreSQL (test_requests.py)."""
    for _ in range(3):
        client.post("/processing/requests", json=BODY)

    page = client.get("/processing/requests", params={"limit": 2}).json()

    assert set(page) == {"items", "next_cursor"}
    assert len(page["items"]) == 2
    for item in page["items"]:
        _assert_request_shape(item)
    assert isinstance(page["next_cursor"], str)


@pytest.mark.parametrize(
    ("path", "params", "field"),
    [
        pytest.param("/processing/requests", {"limit": 500}, "limit", id="limit over 200"),
        pytest.param("/processing/requests", {"cursor": "x"}, "cursor", id="invalid cursor"),
        pytest.param(
            "/processing/preview",
            {"start_date": "2026-10-14", "end_date": "2026-10-16"},
            "scope",
            id="preview without a scope",
        ),
    ],
)
def test_a_bad_query_is_a_422_problem(
    client: TestClient, path: str, params: dict[str, Any], field: str
) -> None:
    errors = _problem(client.get(path, params=params), 422)

    assert [(e["code"], e["field"]) for e in errors] == [("VALIDATION_ERROR", field)]


def test_get_request_by_id_or_404(client: TestClient) -> None:
    created = client.post("/processing/requests", json=BODY).json()

    found = client.get(f"/processing/requests/{created['id']}")
    missing = client.get(f"/processing/requests/{uuid4()}")

    assert (found.status_code, found.json()) == (200, created)
    assert [e["code"] for e in _problem(missing, 404)] == ["NOT_FOUND"]


def test_cancel_answers_200_then_409(client: TestClient) -> None:
    created = client.post("/processing/requests", json=BODY).json()

    cancelled = client.post(f"/processing/requests/{created['id']}/cancel")
    again = client.post(f"/processing/requests/{created['id']}/cancel")

    assert cancelled.status_code == 200
    _assert_request_shape(cancelled.json())
    assert cancelled.json()["status"] == "CANCELLED"
    assert [e["code"] for e in _problem(again, 409)] == ["JOB_NOT_CANCELLABLE"]


def test_get_preview_reports_both_chains(client: TestClient, harness: Harness) -> None:
    harness.history.first_trade = date(2026, 10, 1)
    harness.date_statuses.rows[date(2026, 10, 13)] = date_status(
        date(2026, 10, 13), portfolio=ChainStatus.PROCESSED
    )

    response = client.get(
        "/processing/preview",
        params={"start_date": "2026-10-14", "end_date": "2026-10-16", "scope": "CASH"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "start_date": "2026-10-14",
        "end_date": "2026-10-16",
        "total_days": 3,
        "scope": "CASH",
        "predecessor_date": "2026-10-13",
        "predecessor": {"cash": "NOT_PROCESSED", "positions": "PROCESSED"},
    }
    assert set(response.json()) == PREVIEW_KEYS


def test_get_issues_matches_the_fixture(client: TestClient, harness: Harness) -> None:
    # fixtures.ts `issues[0]`.
    asset_id = UUID("7e000000-0000-4000-8000-000000000029")
    request_id = UUID("7f3c9a02-0000-4000-8000-000000000002")
    issue_id = UUID("7d000000-0000-4000-8000-000000000001")
    harness.assets.codes[asset_id] = "DI1F29"
    harness.issues.rows = [
        IssueRecord(
            id=issue_id,
            request_id=request_id,
            issue_type=IssueType.MISSING_REFERENCE_PRICE,
            asset_id=asset_id,
            affected_date=date(2026, 10, 16),
            required_price_date=date(2026, 10, 16),
        )
    ]

    response = client.get("/processing/issues")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": str(issue_id),
                "issue_type": "MISSING_REFERENCE_PRICE",
                "asset_id": str(asset_id),
                "asset_code": "DI1F29",
                "affected_date": "2026-10-16",
                "required_price_date": "2026-10-16",
                "request_id": str(request_id),
            }
        ]
    }
    assert set(response.json()["items"][0]) == ISSUE_KEYS


@pytest.mark.parametrize(
    ("status", "failed_date", "failed_chain", "expected"),
    [
        pytest.param(
            ProcessingStatus.COMPLETED_WITH_ISSUES,
            date(2026, 10, 15),
            Chain.CASH,
            ("2026-10-15", "CASH"),
            id="a chain failed",
        ),
        pytest.param(
            ProcessingStatus.FAILED,
            date(2026, 10, 14),
            None,
            ("2026-10-14", None),
            id="a failure of no chain has a date and no chain",
        ),
    ],
)
def test_oq40_a_run_exposes_its_first_failure(
    client: TestClient,
    harness: Harness,
    status: ProcessingStatus,
    failed_date: date,
    failed_chain: Chain | None,
    expected: tuple[str, str | None],
) -> None:
    created = client.post("/processing/requests", json=BODY).json()
    run = harness.requests.rows[UUID(created["id"])]
    harness.requests.rows[run.id] = replace(
        run, status=status, failed_date=failed_date, failed_chain=failed_chain
    )

    body = client.get(f"/processing/requests/{created['id']}").json()

    assert (body["failed_date"], body["failed_chain"]) == expected


def test_oq40_the_api_never_advertises_all_as_a_failed_chain(client: TestClient) -> None:
    """interfaces.md "Processing": ``failed_chain`` is CASH or POSITIONS, never ALL; the
    frontend generates its types from this schema."""
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    field = schemas["ProcessingRequestResponse"]["properties"]["failed_chain"]
    refs = [option.get("$ref") for option in field["anyOf"] if "$ref" in option]
    enums = [schemas[ref.rsplit("/", 1)[1]]["enum"] for ref in refs] or [
        option["enum"] for option in field["anyOf"] if "enum" in option
    ]

    assert enums == [["CASH", "POSITIONS"]]


def test_run_timestamps_are_serialized_in_utc(client: TestClient, harness: Harness) -> None:
    """The service stamps runs in São Paulo time while PostgreSQL reads them back in UTC; the
    HTTP shape renders both the same way, as UTC with ``Z``, so POST and GET agree."""
    created = client.post("/processing/requests", json=BODY).json()
    cancelled = client.post(f"/processing/requests/{created['id']}/cancel").json()

    stored = harness.requests.rows[UUID(created["id"])]
    expected = stored.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    assert created["created_at"] == expected
    assert created["updated_at"].endswith("Z")
    assert cancelled["cancel_requested_at"].endswith("Z")
    assert cancelled["finished_at"].endswith("Z")
