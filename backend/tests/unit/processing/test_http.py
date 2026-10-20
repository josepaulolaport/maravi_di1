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
from fastapi.testclient import TestClient

from di1.modules.processing.domain.issues import IssueRecord, IssueType
from di1.modules.processing.presentation.http.router import create_router
from di1.modules.processing.public import Chain, ChainStatus, ProcessingStatus
from tests.support.builders import di1_contract
from tests.support.http import app_client, problem
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
BODY = {"start_date": "2026-10-14", "end_date": "2026-10-16", "scope": "ALL"}


@pytest.fixture
def harness() -> Harness:
    return Harness()


@pytest.fixture
def client(harness: Harness) -> Iterator[TestClient]:
    with app_client(create_router(get_service=lambda: harness.service)) as client:
        yield client


def _assert_request_shape(body: dict[str, Any]) -> None:
    assert set(body) == REQUEST_KEYS
    UUID(body["id"])
    date.fromisoformat(body["start_date"])
    date.fromisoformat(body["end_date"])
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None
    assert datetime.fromisoformat(body["updated_at"]).tzinfo is not None


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
        ({**BODY, "scope": "EVERYTHING"}, "scope", "VALIDATION_ERROR"),
        ({"start_date": "2026-10-14", "end_date": "2026-10-16"}, "scope", "VALIDATION_ERROR"),
        ({**BODY, "start_date": "14/10/2026"}, "start_date", "VALIDATION_ERROR"),
        ({**BODY, "start_date": "2026-10-17"}, "start_date", "INVALID_RANGE"),
        ({**BODY, "end_date": "2026-10-20"}, "end_date", "FUTURE_DATE"),
        ({**BODY, "start_date": "0001-01-01"}, "start_date", "INVALID_RANGE"),
    ],
)
def test_post_request_refuses_a_malformed_range(
    client: TestClient, harness: Harness, body: dict[str, str], field: str, code: str
) -> None:
    errors = problem(client.post("/processing/requests", json=body), 422)["errors"]

    assert [(e["code"], e["field"]) for e in errors] == [(code, field)]
    assert harness.requests.rows == {}


def test_get_requests_is_a_page_newest_first(client: TestClient) -> None:
    ids = [client.post("/processing/requests", json=BODY).json()["id"] for _ in range(3)]

    first = client.get("/processing/requests", params={"limit": 2}).json()
    second = client.get(
        "/processing/requests", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()

    assert set(first) == {"items", "next_cursor"}
    for item in first["items"]:
        _assert_request_shape(item)
    assert [r["id"] for r in first["items"] + second["items"]] == ids[::-1]
    assert second["next_cursor"] is None


def test_get_requests_refuses_a_bad_limit_or_cursor(client: TestClient) -> None:
    bad_limit = problem(client.get("/processing/requests", params={"limit": 500}), 422)["errors"]
    bad_cursor = problem(client.get("/processing/requests", params={"cursor": "x"}), 422)["errors"]

    assert [(e["code"], e["field"]) for e in bad_limit] == [("VALIDATION_ERROR", "limit")]
    assert [(e["code"], e["field"]) for e in bad_cursor] == [("VALIDATION_ERROR", "cursor")]


def test_get_request_by_id_or_404(client: TestClient) -> None:
    created = client.post("/processing/requests", json=BODY).json()

    found = client.get(f"/processing/requests/{created['id']}")
    missing = client.get(f"/processing/requests/{uuid4()}")

    assert (found.status_code, found.json()) == (200, created)
    assert [e["code"] for e in problem(missing, 404)["errors"]] == ["NOT_FOUND"]


def test_cancel_answers_200_then_409(client: TestClient) -> None:
    created = client.post("/processing/requests", json=BODY).json()

    cancelled = client.post(f"/processing/requests/{created['id']}/cancel")
    again = client.post(f"/processing/requests/{created['id']}/cancel")

    assert cancelled.status_code == 200
    _assert_request_shape(cancelled.json())
    assert cancelled.json()["status"] == "CANCELLED"
    assert [e["code"] for e in problem(again, 409)["errors"]] == ["JOB_NOT_CANCELLABLE"]


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


def test_get_preview_requires_the_scope(client: TestClient) -> None:
    errors = problem(
        client.get(
            "/processing/preview", params={"start_date": "2026-10-14", "end_date": "2026-10-16"}
        ),
        422,
    )["errors"]

    assert [(e["code"], e["field"]) for e in errors] == [("VALIDATION_ERROR", "scope")]


def test_get_issues_matches_the_fixture(client: TestClient, harness: Harness) -> None:
    # fixtures.ts `issues[0]`.
    asset_id = UUID("7e000000-0000-4000-8000-000000000029")
    request_id = UUID("7f3c9a02-0000-4000-8000-000000000002")
    issue_id = UUID("7d000000-0000-4000-8000-000000000001")
    harness.assets.add(di1_contract("DI1F29", asset_id, date(2029, 1, 2)))
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


def test_oq40_a_run_exposes_its_first_failure(client: TestClient, harness: Harness) -> None:
    created = client.post("/processing/requests", json=BODY).json()
    run = harness.requests.rows[UUID(created["id"])]
    harness.requests.rows[run.id] = replace(
        run,
        status=ProcessingStatus.COMPLETED_WITH_ISSUES,
        failed_date=date(2026, 10, 15),
        failed_chain=Chain.CASH,
    )

    body = client.get(f"/processing/requests/{created['id']}").json()

    assert (body["failed_date"], body["failed_chain"]) == ("2026-10-15", "CASH")


def test_oq40_a_failure_of_no_chain_has_a_date_and_no_chain(
    client: TestClient, harness: Harness
) -> None:
    created = client.post("/processing/requests", json=BODY).json()
    run = harness.requests.rows[UUID(created["id"])]
    harness.requests.rows[run.id] = replace(
        run, status=ProcessingStatus.FAILED, failed_date=date(2026, 10, 14), failed_chain=None
    )

    body = client.get(f"/processing/requests/{created['id']}").json()

    assert (body["failed_date"], body["failed_chain"]) == ("2026-10-14", None)


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
