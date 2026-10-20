"""The ledger list: an inclusive date range, a search and keyset pagination (spec §11.3, §12;
OQ-24, OQ-26 item 1).

- Order: ``(entry_date, entry_time, seq)`` across both types; ``desc`` (the default) newest first,
  ``asc`` the exact reverse. ``seq`` is unique, so the key is unique and a page boundary is exact.
- The page size and the cursor codec are shared (``di1.shared.paging``). The cursor is the key of
  the last entry of the previous page. An empty cursor is the first page; a cursor the API did not
  write is refused.
- Search (frozen frontend contract, mock ``handlers/ledger.ts``): case- and accent-insensitive,
  by substring; a trade matches its contract code, a cash entry the label of its sign, "Aporte"
  (positive) or "Retirada" (negative), or its description (OQ-51).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum

from di1.modules.ledger.domain.entries import LedgerEntryView
from di1.shared.errors import ErrorDetail, invalid_cursor, invalid_range
from di1.shared.paging import PageParams, decode_cursor, encode_cursor
from di1.shared.text import fold

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TIME = re.compile(r"[0-9]{2}:[0-9]{2}:[0-9]{2}")
_SEQ = re.compile(r"[1-9][0-9]{0,18}")

_SEQ_MAX = 2**63 - 1
"""``seq BIGINT``: a larger key could not be compared with the column."""

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
        return encode_cursor(self.entry_date.isoformat(), moment, str(self.seq))

    @classmethod
    def decode(cls, token: str) -> EntryCursor | None:
        """The cursor ``encode`` wrote, and only that: a valid ``DATE``, a naive whole-second
        ``TIME`` and a ``seq`` in ``BIGINT``'s positive range, spelled exactly as ``encode``
        spells it; ``None`` for anything else, crafted or corrupted."""
        parts = decode_cursor(token, parts=3)
        if parts is None:
            return None
        day, moment, seq = parts
        if not (_DATE.fullmatch(day) and _TIME.fullmatch(moment) and _SEQ.fullmatch(seq)):
            return None
        try:
            cursor = cls(date.fromisoformat(day), time.fromisoformat(moment), int(seq))
        except ValueError:
            return None
        return cursor if cursor.seq <= _SEQ_MAX and cursor.encode() == token else None


@dataclass(frozen=True, slots=True)
class EntrySearch:
    """A non-blank search, folded (lowercase, no accents)."""

    needle: str

    @classmethod
    def parse(cls, text: str | None) -> EntrySearch | None:
        folded = fold(text or "").strip()
        return cls(folded) if folded else None

    def matches_code(self, code: str) -> bool:
        return self.needle in fold(code)

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
        return self.needle in fold(DEPOSIT_LABEL)

    @property
    def includes_withdrawals(self) -> bool:
        return self.needle in fold(WITHDRAWAL_LABEL)


@dataclass(frozen=True, slots=True)
class PageRequest:
    """A validated request for one page of the ledger list."""

    start_date: date
    end_date: date
    search: EntrySearch | None
    order: ListOrder
    limit: int
    after: EntryCursor | None

    @classmethod
    def of(
        cls,
        *,
        start_date: date,
        end_date: date,
        search: str | None,
        order: ListOrder,
        page: PageParams,
    ) -> PageRequest:
        """The request `validate_page_request` accepted. An empty ``?cursor=`` is no cursor: the
        first page; any other cursor must decode, or the request was not validated."""
        after = EntryCursor.decode(page.cursor) if page.cursor else None
        if page.cursor and after is None:
            raise ValueError("PageRequest.of needs a page request validate_page_request accepted")
        return cls(
            start_date=start_date,
            end_date=end_date,
            search=EntrySearch.parse(search),
            order=order,
            limit=page.limit,
            after=after,
        )


@dataclass(frozen=True, slots=True)
class LedgerEntryPage:
    items: Sequence[LedgerEntryView]
    next_cursor: str | None


def validate_page_request(
    *, start_date: date, end_date: date, page: PageParams
) -> tuple[ErrorDetail, ...]:
    """A range whose start is after its end and a page size outside [1, 200]; when both are
    valid, a cursor this API did not write."""
    errors: list[ErrorDetail] = []
    if start_date > end_date:
        errors.append(invalid_range())
    errors.extend(page.errors())
    # The cursor is checked only once the range and the size are valid, as before the shared
    # codec: one problem at a time for the list's own parameters.
    if not errors and page.cursor and EntryCursor.decode(page.cursor) is None:
        errors.append(invalid_cursor())
    return tuple(errors)
