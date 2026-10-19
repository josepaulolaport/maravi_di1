"""The envelope is generic, round-trips through JSON, and never carries a float.

CLAUDE.md §2 (JSON carries decimal strings); schema.sql ``platform.outbox_messages``
(``message_type VARCHAR(128)``, ``schema_version SMALLINT > 0``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from di1.platform.messaging.envelope import Envelope

CREATED_AT = datetime(2026, 10, 18, 15, 30, tzinfo=UTC)


def _envelope(**overrides: Any) -> Envelope:
    fields: dict[str, Any] = {
        "message_id": uuid.uuid4(),
        "message_type": "test.command",
        "schema_version": 1,
        "created_at": CREATED_AT,
        "payload": {"amount": "1234.5678901234", "count": 3, "items": [{"ok": True}]},
    }
    return Envelope(**(fields | overrides))


def test_round_trips_through_json() -> None:
    envelope = _envelope()

    assert Envelope.from_json(envelope.to_json()) == envelope


@pytest.mark.parametrize(
    "payload",
    [{"pu": 98765.43}, {"nested": {"rate": 0.1}}, {"list": ["1", 2.5]}],
)
def test_a_float_anywhere_in_the_payload_is_rejected(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="float"):
        _envelope(payload=payload)


def test_a_float_in_a_received_body_is_rejected() -> None:
    body = _envelope(payload={}).to_json().replace(b'"payload":{}', b'"payload":{"pu":1.5}')

    with pytest.raises(ValidationError, match="float"):
        Envelope.from_json(body)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("message_type", ""),
        ("message_type", "x" * 129),
        ("schema_version", 0),
        ("schema_version", 32768),
        ("created_at", datetime(2026, 10, 18, 15, 30)),  # noqa: DTZ001 - naive on purpose
    ],
)
def test_field_bounds(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        _envelope(**{field: value})


def test_unknown_fields_are_rejected() -> None:
    body = _envelope().to_json().replace(b'{"message_id"', b'{"extra":1,"message_id"')

    with pytest.raises(ValidationError, match="extra"):
        Envelope.from_json(body)


@pytest.mark.parametrize("body", [b"", b"not json", b"[]", b'{"message_id": "x"}'])
def test_a_body_that_is_not_an_envelope_is_rejected(body: bytes) -> None:
    with pytest.raises(ValidationError):
        Envelope.from_json(body)


def test_the_envelope_is_immutable() -> None:
    envelope = _envelope()

    with pytest.raises(ValidationError):
        envelope.message_type = "other"  # type: ignore[misc]


def test_a_payload_changed_after_validation_cannot_be_serialized_with_a_float() -> None:
    """`frozen` stops reassigning ``payload``, not changing the dict inside it."""
    envelope = _envelope(payload={"pu": "1.5"})
    envelope.payload["pu"] = 1.5

    with pytest.raises(ValueError, match="float"):
        envelope.to_json()
