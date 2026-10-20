"""The ledger list: an inclusive date range, a search and keyset pagination (spec §11.3, §12;
OQ-24, OQ-26 item 1).

- Order: ``(entry_date, entry_time, seq)`` across both types; ``desc`` (the default) newest first,
  ``asc`` the exact reverse. ``seq`` is unique, so the key is unique and a page boundary is exact.
- The cursor is opaque to the client: the key of the last entry of the previous page. An empty
  cursor is the first page; a cursor the API did not write is refused.
- Search (frozen frontend contract, mock ``handlers/ledger.ts``): case- and accent-insensitive,
  by substring; a trade matches its contract code, a cash entry the label of its sign, "Aporte"
  (positive) or "Retirada" (negative), or its description (OQ-51).
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum

from di1.shared.errors import DomainError, ErrorCode, ErrorDetail

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

_CURSOR_KEY = re.compile(
    r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\|(?P<time>[0-9]{2}:[0-9]{2}:[0-9]{2})\|(?P<seq>[1-9][0-9]{0,18})"
)
"""``YYYY-MM-DD|HH:MM:SS|seq``: what `EntryCursor.encode` writes."""

_BIGINT_MAX = 2**63 - 1
"""``seq BIGINT``."""

DESCRIPTION_ACCENTED = "áàâãäåéèêëíìîïóòôõöúùûüçñýÿ"
DESCRIPTION_PLAIN = "aaaaaaeeeeiiiiooooouuuucnyy"
"""How the list folds a stored description, in SQL as ``translate(lower(description), ...)``:
the schema does not install ``unaccent`` (as for Asset's search). It covers the accented
letters of Portuguese and their Latin-1 kin; any other letter (e.g. "ß") is only lowercased
(OQ-51). Descriptions are stored composed (NFC), so these precomposed letters are what is there."""

_DESCRIPTION_FOLD = str.maketrans(DESCRIPTION_ACCENTED, DESCRIPTION_PLAIN)

DEPOSIT_LABEL = "Aporte"
WITHDRAWAL_LABEL = "Retirada"


class ListOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True, slots=True)
class EntryCursor:
    """The order key of the last entry of a page."""

    entry_date: date
    entry_time: time
    seq: int

    def encode(self) -> str:
        moment = self.entry_time.isoformat(timespec="seconds")
        raw = f"{self.entry_date.isoformat()}|{moment}|{self.seq}"
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, token: str) -> EntryCursor:
        """The cursor ``encode`` wrote, and only that: the key must be a valid ``DATE``, a naive
        whole-second ``TIME`` and a ``seq`` in ``BIGINT``'s positive range, spelled exactly as
        ``encode`` spells it. Anything else, crafted or corrupted, raises `DomainError`
        (``VALIDATION_ERROR`` on ``cursor``) before it reaches a query."""
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("ascii")
            key = _CURSOR_KEY.fullmatch(raw)
            if key is None:
                raise ValueError("not a cursor key")
            cursor = cls(
                date.fromisoformat(key["date"]),
                time.fromisoformat(key["time"]),
                int(key["seq"]),
            )
            if cursor.seq > _BIGINT_MAX or cursor.encode() != token:
                raise ValueError("not a cursor this API wrote")
            return cursor
        except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
            raise DomainError(ErrorDetail.validation("Cursor inválido.", "cursor")) from exc


@dataclass(frozen=True, slots=True)
class EntrySearch:
    """A non-blank search, folded (lowercase, no accents)."""

    needle: str

    @classmethod
    def parse(cls, text: str | None) -> EntrySearch | None:
        folded = _fold(text or "").strip()
        return cls(folded) if folded else None

    def matches_code(self, code: str) -> bool:
        return self.needle in _fold(code)

    @property
    def has_nul(self) -> bool:
        """PostgreSQL text cannot hold NUL (OQ-15): such a search is never sent to the database
        and matches no description, as no stored text holds it."""
        return "\x00" in self.needle

    def matches_description(self, description: str | None) -> bool:
        """What the list's SQL does with ``ledger.entries.description``: a substring of the
        description lowercased and folded with `DESCRIPTION_ACCENTED` (OQ-51)."""
        if description is None or self.has_nul:
            return False
        return self.needle in description.lower().translate(_DESCRIPTION_FOLD)

    @property
    def includes_deposits(self) -> bool:
        return self.needle in _fold(DEPOSIT_LABEL)

    @property
    def includes_withdrawals(self) -> bool:
        return self.needle in _fold(WITHDRAWAL_LABEL)


@dataclass(frozen=True, slots=True)
class PageRequest:
    """A validated request for one page of the ledger list."""

    start_date: date
    end_date: date
    search: EntrySearch | None
    order: ListOrder
    limit: int
    after: EntryCursor | None


def validate_page_request(
    *,
    start_date: date,
    end_date: date,
    search: str | None,
    order: ListOrder,
    limit: int | None,
    cursor: str | None,
) -> PageRequest:
    """Raises `DomainError` for a range whose start is after its end, a page size outside
    [1, 200] or a malformed cursor."""
    errors: list[ErrorDetail] = []
    if start_date > end_date:
        errors.append(
            ErrorDetail(
                ErrorCode.INVALID_RANGE,
                "A data inicial deve ser anterior ou igual à data final.",
                "start_date",
            )
        )
    page_size = DEFAULT_PAGE_SIZE if limit is None else limit
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        errors.append(ErrorDetail.validation(f"Use um limite entre 1 e {MAX_PAGE_SIZE}.", "limit"))
    if errors:
        raise DomainError(*errors)
    return PageRequest(
        start_date=start_date,
        end_date=end_date,
        search=EntrySearch.parse(search),
        order=order,
        limit=page_size,
        # An empty ``?cursor=`` is no cursor: the first page.
        after=EntryCursor.decode(cursor) if cursor else None,
    )


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
