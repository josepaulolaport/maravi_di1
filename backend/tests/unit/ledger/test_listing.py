"""The parameters of the ledger list: range, page size, keyset cursor and search.

Rules: spec §11.3 and §12 (an inclusive date range, search and keyset pagination on
(entry_date, entry_time, seq), `{items, next_cursor}`, OQ-26 item 1); interfaces "Errors"
(INVALID_RANGE for start after end). The search mirrors the frozen frontend contract's mock
(frontend/src/api/mocks/handlers/ledger.ts at 57b4df0): case- and accent-insensitive; a trade
matches its contract code, a cash entry the label of its sign, "Aporte" or "Retirada".
"""

from __future__ import annotations

import base64
from datetime import date, time

import pytest

from di1.modules.ledger.domain.listing import (
    EntryCursor,
    EntrySearch,
    ListOrder,
    PageRequest,
    validate_page_request,
)
from di1.shared.errors import DomainError, ErrorCode
from di1.shared.paging import DEFAULT_LIMIT, MAX_LIMIT, PageParams


def page_request(
    *,
    start_date: date,
    end_date: date,
    search: str | None,
    order: ListOrder,
    limit: int | None,
    cursor: str | None,
) -> PageRequest:
    """The request the service builds, or the `DomainError` it raises."""
    page = PageParams(DEFAULT_LIMIT if limit is None else limit, cursor)
    errors = validate_page_request(start_date=start_date, end_date=end_date, page=page)
    if errors:
        raise DomainError(*errors)
    return PageRequest.of(
        start_date=start_date, end_date=end_date, search=search, order=order, page=page
    )


def test_the_cursor_round_trips_and_is_opaque() -> None:
    cursor = EntryCursor(date(2026, 10, 16), time(15, 0), 4)

    token = cursor.encode()

    assert "2026" not in token
    assert EntryCursor.decode(token) == cursor


@pytest.mark.parametrize("token", ["", "not-base64!", "MjAyNi0xMC0xNg", "eyJhIjogMX0"])
def test_a_malformed_cursor_decodes_to_nothing(token: str) -> None:
    assert EntryCursor.decode(token) is None


@pytest.mark.parametrize("token", ["not-base64!", "MjAyNi0xMC0xNg", "eyJhIjogMX0"])
def test_a_malformed_cursor_is_a_validation_error_on_cursor(token: str) -> None:
    with pytest.raises(DomainError) as error:
        page_request(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 18),
            search=None,
            order=ListOrder.DESC,
            limit=None,
            cursor=token,
        )

    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert error.value.errors[0].field == "cursor"
    assert error.value.errors[0].message == "Cursor inválido."


def _token(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    "raw",
    [
        "2026-10-16|10:00:00+03:00|4",  # an aware time: PostgreSQL would compare timetz to time
        "2026-10-16|10:00:00.5|4",  # fractions: entry times are whole seconds
        "2026-10-16|10:00|4",  # not the HH:MM:SS the encoder writes
        "2026-10-16|10:00:00|99999999999999999999",  # beyond BIGINT
        "2026-10-16|10:00:00|9223372036854775808",  # 2^63, one past BIGINT
        "2026-10-16|10:00:00|0",  # seq starts at 1
        "2026-10-16|10:00:00|-4",
        "2026-10-16|10:00:00|+4",
        "2026-10-16|10:00:00| 4",
        "2026-10-16|10:00:00|04",
        "20261016|10:00:00|4",
        "2026-10-16|10:00:00|4|extra",
    ],
)
def test_a_crafted_cursor_is_refused_not_a_server_error(raw: str) -> None:
    assert EntryCursor.decode(_token(raw)) is None


def test_only_the_encoders_own_spelling_is_accepted() -> None:
    token = EntryCursor(date(2026, 10, 16), time(15, 0), 4).encode()

    assert EntryCursor.decode(token + "==") is None  # padding the encoder never writes
    assert EntryCursor.decode(token[:5] + "!" + token[5:]) is None  # a character base64 skips


def test_the_largest_seq_round_trips() -> None:
    cursor = EntryCursor(date(2026, 10, 16), time(23, 59, 59), 2**63 - 1)

    assert EntryCursor.decode(cursor.encode()) == cursor


def test_an_empty_cursor_is_the_first_page() -> None:
    request = page_request(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 18),
        search=None,
        order=ListOrder.DESC,
        limit=None,
        cursor="",
    )

    assert request.after is None


def test_the_page_request_defaults() -> None:
    request = page_request(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 18),
        search=None,
        order=ListOrder.DESC,
        limit=None,
        cursor=None,
    )

    assert request.limit == DEFAULT_LIMIT == 50
    assert request.search is None
    assert request.after is None


def test_a_single_day_range_is_valid() -> None:
    day = date(2026, 10, 16)
    request = page_request(
        start_date=day, end_date=day, search=None, order=ListOrder.ASC, limit=1, cursor=None
    )
    assert (request.start_date, request.end_date) == (day, day)


def test_start_after_end_is_an_invalid_range() -> None:
    with pytest.raises(DomainError) as error:
        page_request(
            start_date=date(2026, 10, 18),
            end_date=date(2026, 10, 17),
            search=None,
            order=ListOrder.DESC,
            limit=None,
            cursor=None,
        )

    assert error.value.code is ErrorCode.INVALID_RANGE
    assert error.value.errors[0].field == "start_date"


@pytest.mark.parametrize("limit", [0, -1, MAX_LIMIT + 1])
def test_the_page_size_is_between_1_and_200(limit: int) -> None:
    with pytest.raises(DomainError) as error:
        page_request(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 18),
            search=None,
            order=ListOrder.DESC,
            limit=limit,
            cursor=None,
        )

    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert error.value.errors[0].field == "limit"
    assert error.value.errors[0].message == "Use um limite entre 1 e 200."


def test_the_cursor_is_decoded_into_the_request() -> None:
    cursor = EntryCursor(date(2026, 10, 16), time(15, 0), 4)
    request = page_request(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 18),
        search="  ",
        order=ListOrder.DESC,
        limit=200,
        cursor=cursor.encode(),
    )

    assert request.after == cursor
    assert request.search is None  # blank search filters nothing


# --- search -------------------------------------------------------------------------------------


def test_a_contract_code_matches_case_insensitively_by_substring() -> None:
    search = EntrySearch.parse("f28")

    assert search is not None
    assert search.matches_code("DI1F28")
    assert not search.matches_code("DI1F29")


def test_search_ignores_accents_and_surrounding_spaces() -> None:
    search = EntrySearch.parse("  RETIRÁDA ")

    assert search is not None
    assert search.includes_withdrawals
    assert not search.includes_deposits


def test_a_prefix_of_aporte_selects_deposits_only() -> None:
    search = EntrySearch.parse("apo")

    assert search is not None
    assert search.includes_deposits
    assert not search.includes_withdrawals
    assert not search.matches_code("DI1F28")


def test_a_letter_in_both_labels_selects_both_signs() -> None:
    search = EntrySearch.parse("r")

    assert search is not None
    assert search.includes_deposits and search.includes_withdrawals


def test_a_code_search_selects_no_cash_entry() -> None:
    search = EntrySearch.parse("DI1")

    assert search is not None
    assert not search.includes_deposits
    assert not search.includes_withdrawals


def test_an_empty_search_is_none() -> None:
    assert EntrySearch.parse(None) is None
    assert EntrySearch.parse("   ") is None


def test_the_cursor_is_checked_once_the_range_and_size_are_valid() -> None:
    errors = validate_page_request(
        start_date=date(2026, 10, 18),
        end_date=date(2026, 10, 17),
        page=PageParams(limit=0, cursor="not-a-cursor"),
    )

    assert [(e.code, e.field) for e in errors] == [
        (ErrorCode.INVALID_RANGE, "start_date"),
        (ErrorCode.VALIDATION_ERROR, "limit"),
    ]


def test_an_unvalidated_bad_cursor_never_becomes_the_first_page() -> None:
    with pytest.raises(ValueError, match="validate_page_request"):
        PageRequest.of(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 18),
            search=None,
            order=ListOrder.DESC,
            page=PageParams(cursor="not-a-cursor"),
        )


def test_a_description_matches_ignoring_case_and_accents() -> None:
    search = EntrySearch.parse("Aplicacao")

    assert search is not None
    assert search.matches_description("Aplicação inicial")
    assert not search.matches_description("Resgate")
    assert not search.matches_description(None)
    assert search.matches_description("APLICAÇÃO")


def test_the_description_fold_is_the_sql_one_for_portuguese_letters() -> None:
    # The list folds the stored description in SQL with lower() and a fixed table of accented
    # letters (no unaccent); a letter outside it, like "ß", is not folded (OQ-51).
    search = EntrySearch.parse("strasse")

    assert search is not None
    assert not search.matches_description("Straße")


def test_a_search_with_a_nul_character_matches_no_description() -> None:
    search = EntrySearch.parse("a\x00")

    assert search is not None
    assert not search.matches_description("a\x00")
