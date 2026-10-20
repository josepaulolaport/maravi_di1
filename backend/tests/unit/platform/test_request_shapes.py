"""The request base and the instant type every module's HTTP schemas share."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, ValidationError

from di1.platform.http import RequestBody, UtcDatetime
from di1.shared.clock import SAO_PAULO


class _Body(RequestBody):
    name: str


class _Stamped(BaseModel):
    at: UtcDatetime


def test_a_request_body_refuses_unknown_fields() -> None:
    with pytest.raises(ValidationError) as caught:
        _Body.model_validate({"name": "DI1", "extra": 1})

    assert caught.value.errors()[0]["type"] == "extra_forbidden"


def test_an_instant_is_rendered_in_utc() -> None:
    stamped = _Stamped(at=datetime(2026, 10, 19, 18, 30, tzinfo=SAO_PAULO))

    assert stamped.at == datetime(2026, 10, 19, 21, 30, tzinfo=UTC)
    assert stamped.at.utcoffset() == timedelta(0)
    assert stamped.model_dump(mode="json") == {"at": "2026-10-19T21:30:00Z"}


def test_an_instant_already_in_utc_is_unchanged() -> None:
    at = datetime(2026, 10, 19, 21, 30, tzinfo=timezone(timedelta(0)))

    assert _Stamped(at=at).model_dump(mode="json") == {"at": "2026-10-19T21:30:00Z"}


def test_a_naive_instant_is_refused() -> None:
    with pytest.raises(ValidationError):
        _Stamped(at=datetime(2026, 10, 19, 21, 30))  # noqa: DTZ001
