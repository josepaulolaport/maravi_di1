"""Asset's frozen public contract (plan §3, W0.3b; interfaces.md "Asset")."""

from __future__ import annotations

import dataclasses
import inspect
import typing
from collections.abc import Collection, Mapping
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from di1.modules.asset.public import AssetReader, Instrument
from tests.support.builders import CREATED_AT


def test_a_descriptor_carries_the_di1_specification() -> None:
    descriptor = Instrument(
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
        created_at=CREATED_AT,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        descriptor.code = "DI1N27"  # type: ignore[misc]


def test_asset_reader_is_a_batch_lookup() -> None:
    signature = inspect.signature(AssetReader.get_instruments)
    assert list(signature.parameters) == ["self", "instrument_ids"]
    hints = typing.get_type_hints(AssetReader.get_instruments)
    assert hints["instrument_ids"] == Collection[UUID]
    assert hints["return"] == Mapping[UUID, Instrument]
    assert not hasattr(AssetReader, "get_instrument")
