"""Asset's frozen public contract (plan §3, W0.3b; interfaces.md "Asset")."""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from di1.modules.asset.public import InstrumentDescriptor


def test_a_descriptor_carries_the_di1_specification() -> None:
    descriptor = InstrumentDescriptor(
        id=uuid4(),
        code="DI1F27",
        product_id=uuid4(),
        product_code="DI1",
        instrument_type="FUTURE",
        asset_class="INTEREST_RATE_FUTURE",
        maturity_date=date(2027, 1, 1),
        face_value=Decimal("100000"),
        multiplier=Decimal("1"),
        settlement_method="FINANCIAL",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        descriptor.code = "DI1N27"  # type: ignore[misc]
