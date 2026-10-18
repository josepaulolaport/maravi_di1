"""The real source tree respects every import boundary (CLAUDE.md §3; plan §0-§1)."""

from __future__ import annotations

from pathlib import Path

from tests.architecture.boundaries import find_violations

SOURCE_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "di1"


def test_source_tree_exists() -> None:
    assert (SOURCE_PACKAGE / "__init__.py").is_file()


def test_source_respects_import_boundaries() -> None:
    assert find_violations(SOURCE_PACKAGE) == []
