"""The generic message envelope: what the outbox stores and what travels on the broker.

It carries no business meaning: ``message_type`` names the command, ``payload`` is its JSON body
and belongs to the module that defines the type (Processing, for the dispatch command).
``message_id`` is the identity used for idempotency (``platform.inbox_messages``).

Numbers in a payload are integers or decimal strings, never floats (CLAUDE.md §2: JSON carries
decimal strings), so a float is rejected both when a message is written and when one is read.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator

MESSAGE_TYPE_MAX_LENGTH = 128
"""``platform.outbox_messages.message_type`` is ``VARCHAR(128)``."""

CONTENT_TYPE = "application/json"


class Envelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: uuid.UUID
    message_type: Annotated[str, Field(min_length=1, max_length=MESSAGE_TYPE_MAX_LENGTH)]
    schema_version: Annotated[int, Field(gt=0, le=32767)]
    created_at: AwareDatetime
    payload: dict[str, JsonValue]

    @field_validator("payload")
    @classmethod
    def _no_floats(cls, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _reject_floats(payload, "payload")
        return payload

    def to_json(self) -> bytes:
        # `frozen` stops reassigning ``payload`` but not changing the dict inside it, so the
        # rule is checked again before anything is serialized.
        _reject_floats(self.payload, "payload")
        return self.model_dump_json().encode()

    @classmethod
    def from_json(cls, body: bytes) -> Envelope:
        """Parse a broker body; raises `pydantic.ValidationError` when it is not an envelope."""
        return cls.model_validate_json(body)


def _reject_floats(value: JsonValue, path: str) -> None:
    if isinstance(value, float):
        raise ValueError(f"{path} is a float; send decimals as strings")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_floats(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for index, item in enumerate(value):
            _reject_floats(item, f"{path}[{index}]")
