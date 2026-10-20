"""Each enum stored in a column with an ``IN`` CHECK has exactly that CHECK's values
(`docs/schema.sql`). ``processing.issues.issue_type`` has no such CHECK, so it is not compared.

The values are read from the schema file, so adding a value to one side alone fails here, in the
pre-commit hook, before any database test runs. `docs/schema.sql` is the revisions' result
(`tests/integration/test_migrations_match_schema.py`).
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import pytest

from di1.modules.ledger.public import EntryType
from di1.modules.pnl.public import CalculationCompleteness
from di1.modules.portfolio.public import ValuationStatus
from di1.modules.prices.public import PriceSource
from di1.modules.processing.public import Chain, ChainStatus, ProcessingScope, ProcessingStatus
from di1.shared.input_kind import InputKind

SCHEMA_SQL = Path(__file__).resolve().parents[3] / "docs" / "schema.sql"


def _check_values(table: str, column: str) -> set[str]:
    """The values every ``<column> IN (...)`` of ``table``'s CREATE TABLE allows."""
    schema = SCHEMA_SQL.read_text()
    start = schema.index(f"CREATE TABLE {table} (")
    body = schema[start : schema.index("\n);", start)]
    lists = re.findall(rf"\b{column} IN \(([^)]*)\)", body)
    assert lists, f"{table}.{column} has no IN check"
    sets = [set(re.findall(r"'([^']*)'", values)) for values in lists]
    assert all(values == sets[0] for values in sets), f"{table}.{column} checks disagree"
    return sets[0]


def _values(enum: type[Enum]) -> set[str]:
    return {member.value for member in enum}


@pytest.mark.parametrize(
    ("table", "column", "enum"),
    [
        ("ledger.entries", "type", EntryType),
        ("ledger.entries", "input_kind", InputKind),
        ("prices.reference_prices", "input_kind", InputKind),
        ("prices.reference_prices", "source", PriceSource),
        ("processing.requests", "scope", ProcessingScope),
        ("processing.requests", "status", ProcessingStatus),
        ("processing.requests", "failed_chain", Chain),
        ("processing.date_status", "portfolio", ChainStatus),
        ("processing.date_status", "cash", ChainStatus),
        ("portfolio.position_metrics", "valuation_status", ValuationStatus),
        ("portfolio.position_metrics", "pnl_status", CalculationCompleteness),
        ("portfolio.portfolio_metrics", "pnl_status", CalculationCompleteness),
    ],
    ids=lambda value: value if isinstance(value, str) else value.__name__,
)
def test_the_enum_has_exactly_the_check_values(table: str, column: str, enum: type[Enum]) -> None:
    assert _values(enum) == _check_values(table, column)


def test_a_failed_chain_is_one_chain_never_all() -> None:
    # OQ-40: a run's first failure belongs to the CASH or the POSITIONS chain.
    assert _check_values("processing.requests", "failed_chain") == _values(ProcessingScope) - {
        "ALL"
    }


def test_a_portfolio_total_is_valued_or_missing_never_not_required() -> None:
    # A flat asset needs no price (NOT_REQUIRED); the portfolio total is complete or missing.
    assert _check_values("portfolio.portfolio_metrics", "valuation_status") == _values(
        ValuationStatus
    ) - {"NOT_REQUIRED"}
