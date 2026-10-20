"""Case- and accent-insensitive text comparison (user, 2026-10-19)."""

from __future__ import annotations

import pytest

from di1.shared.text import fold


@pytest.mark.parametrize(
    ("text", "folded"),
    [("Depósitos", "depositos"), ("RETIRADA", "retirada"), ("Ação", "acao"), ("DI1F27", "di1f27")],
)
def test_fold_drops_accents_and_case(text: str, folded: str) -> None:
    assert fold(text) == folded
