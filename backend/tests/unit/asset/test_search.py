"""Catalogue search (user, 2026-10-19): a case- and accent-insensitive substring of any of the
searched values; an empty or blank search matches everything."""

from __future__ import annotations

import pytest

from di1.modules.asset.domain.search import matches

DI1_NAME = "Futuro de Taxa Média de Depósitos Interfinanceiros de Um Dia"


@pytest.mark.parametrize("search", [None, "", "   "])
def test_no_search_matches_everything(search: str | None) -> None:
    assert matches(("DI1",), search)


@pytest.mark.parametrize("search", ["di1", "DI1", " di1 ", "f27"])
def test_is_a_case_insensitive_substring(search: str) -> None:
    assert matches(("DI1F27",), search)


@pytest.mark.parametrize("search", ["depositos", "DEPÓSITOS", "média", "taxa media"])
def test_ignores_accents(search: str) -> None:
    assert matches(("DI1", DI1_NAME), search)


def test_any_value_may_match() -> None:
    assert matches(("DI1", None, "Futuros de Taxa de Juros"), "juros")


def test_a_search_found_nowhere_does_not_match() -> None:
    assert not matches(("DI1", DI1_NAME, None), "dólar")
