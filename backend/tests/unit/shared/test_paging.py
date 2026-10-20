"""Keyset pagination shared by every list (spec §12; OQ-26 item 1)."""

from __future__ import annotations

import pytest

from di1.shared.errors import ErrorDetail
from di1.shared.paging import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    PageParams,
    decode_cursor,
    encode_cursor,
)


def test_a_page_defaults_to_50_and_allows_up_to_200() -> None:
    assert (DEFAULT_LIMIT, MAX_LIMIT) == (50, 200)
    assert PageParams().limit == 50
    assert PageParams(limit=1).errors() == ()
    assert PageParams(limit=200).errors() == ()


@pytest.mark.parametrize("limit", [0, -1, 201])
def test_a_limit_outside_1_to_200_is_refused(limit: int) -> None:
    assert PageParams(limit=limit).errors() == (
        ErrorDetail.validation("Use um limite entre 1 e 200.", "limit"),
    )


def test_a_cursor_round_trips_its_parts() -> None:
    token = encode_cursor("2026-10-01", "09:30:00", "42")

    assert "=" not in token
    assert decode_cursor(token, parts=3) == ("2026-10-01", "09:30:00", "42")


@pytest.mark.parametrize("token", ["", "!!!", "bm90IGEgY3Vyc29y", "w4k"])
def test_a_token_that_is_not_a_cursor_decodes_to_none(token: str) -> None:
    assert decode_cursor(token, parts=3) is None


def test_a_cursor_with_another_number_of_parts_is_refused() -> None:
    assert decode_cursor(encode_cursor("a", "b"), parts=3) is None
