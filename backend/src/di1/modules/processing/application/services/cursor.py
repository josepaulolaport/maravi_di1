"""The opaque keyset cursor of the run history: the ``(created_at, id)`` of a page's last run
(spec §12, OQ-26 item 1)."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from uuid import UUID

from di1.shared.errors import DomainError, ErrorCode, ErrorDetail


def _invalid_cursor() -> DomainError:
    return DomainError(ErrorDetail(ErrorCode.VALIDATION_ERROR, "Cursor inválido.", "cursor"))


def encode_cursor(created_at: datetime, request_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{request_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """The keyset in ``cursor``; ``VALIDATION_ERROR`` on ``cursor`` when it is not one."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        created_at, request_id = raw.split("|")
        keyset = datetime.fromisoformat(created_at), UUID(request_id)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise _invalid_cursor() from None
    if keyset[0].tzinfo is None:
        raise _invalid_cursor()
    return keyset
