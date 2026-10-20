"""Keyset pagination shared by every list (spec §12; OQ-26 item 1).

- A page holds ``limit`` items: 50 by default, 1 to 200.
- The cursor is opaque to the client: the order key of the last item of the previous page, its
  parts joined by ``|`` and base64url-encoded without padding. What the parts are, and how strictly
  they are parsed, is the list's own rule; `decode_cursor` only undoes `encode_cursor`.

Standard library only: domain code imports this module.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from di1.shared.errors import ErrorDetail, limit_out_of_range

__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "PageParams", "decode_cursor", "encode_cursor"]

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

_SEPARATOR = "|"


@dataclass(frozen=True, slots=True)
class PageParams:
    """The page a list request asks for: its size and the cursor after which it starts (``None``
    for the first page)."""

    limit: int = DEFAULT_LIMIT
    cursor: str | None = None

    def errors(self) -> tuple[ErrorDetail, ...]:
        """A page size outside [1, `MAX_LIMIT`]; the list checks its cursor itself."""
        return () if 1 <= self.limit <= MAX_LIMIT else (limit_out_of_range(MAX_LIMIT),)


def encode_cursor(*parts: str) -> str:
    raw = _SEPARATOR.join(parts)
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(token: str, *, parts: int) -> tuple[str, ...] | None:
    """The ``parts`` strings `encode_cursor` joined into ``token``, or ``None`` when the token is
    not base64url of that many ASCII parts."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("ascii")
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    found = tuple(raw.split(_SEPARATOR))
    return found if raw and len(found) == parts else None
