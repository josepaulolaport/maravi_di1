"""HTTP types shared by every module's request schemas."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated

from pydantic import BeforeValidator, WithJsonSchema

_DECIMAL = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")


def _decimal_string(value: object) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ValueError("a decimal number as a string")
    return Decimal(value)


DecimalString = Annotated[
    Decimal,
    BeforeValidator(_decimal_string),
    WithJsonSchema({"type": "string", "pattern": _DECIMAL.pattern}),
]
r"""A typed decimal sent as a JSON string in plain notation (``"89006.4625467350"``), parsed to
``Decimal`` with its trailing zeros kept, since they were typed (OQ-3). A JSON number (it may
already have lost precision), an exponent, a non-finite value and any non-ASCII digit are refused:
``\d`` would accept other scripts' digits, and ``Decimal`` parses Arabic-Indic "123" as 123."""
