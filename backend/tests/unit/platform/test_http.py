"""The shared ``DecimalString`` HTTP type: ASCII digits only, parsed to ``Decimal``, a string in
the JSON schema (CLAUDE.md §2)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from di1.platform.http import DecimalString


class _Body(BaseModel):
    value: DecimalString


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", "0"), ("-1.50", "-1.50"), ("89006.4625467350", "89006.4625467350")],
)
def test_a_plain_decimal_string_is_parsed_exactly(raw: str, expected: str) -> None:
    parsed = _Body.model_validate({"value": raw}).value

    assert isinstance(parsed, Decimal)
    assert str(parsed) == expected  # trailing zeros were typed and are kept (OQ-3)


@pytest.mark.parametrize(
    "raw",
    [
        "\u0661\u0662\u0663",  # Arabic-Indic 123
        "\uff11\uff12\uff13",  # fullwidth 123
        "1e5",
        "Infinity",
        "NaN",
        "",
        "1,5",
        "+1",
        ".5",
        "1.",
        " 1",
        82057.0,
        1,
    ],
)
def test_anything_else_is_refused(raw: object) -> None:
    with pytest.raises(ValidationError):
        _Body.model_validate({"value": raw})


def test_the_json_schema_is_a_string_with_an_ascii_pattern() -> None:
    schema = _Body.model_json_schema()["properties"]["value"]

    assert (schema["type"], schema["pattern"]) == ("string", r"^-?[0-9]+(\.[0-9]+)?$")
