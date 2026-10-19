"""Prices' frozen public contract (plan §3, W0.3b; interfaces.md "Prices")."""

from __future__ import annotations

import dataclasses
import inspect
import typing
from collections.abc import Collection, Mapping
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from di1.modules.prices.public import (
    LatestPriceReader,
    PriceReader,
    PriceSource,
    ReferencePriceRecord,
)
from di1.shared.clock import SAO_PAULO
from di1.shared.input_kind import InputKind


def test_price_source_matches_the_schema_check() -> None:
    assert {source.value for source in PriceSource} == {"MANUAL", "B3"}


def test_a_reference_price_is_frozen() -> None:
    record = ReferencePriceRecord(
        id=uuid4(),
        asset_id=uuid4(),
        reference_date=date(2026, 10, 16),
        source=PriceSource.MANUAL,
        input_kind=InputKind.RATE,
        pu=Decimal("98765.4321000000"),
        rate=Decimal("0.135000000000"),
        created_at=datetime(2026, 10, 16, 18, 0, tzinfo=SAO_PAULO),
        updated_at=datetime(2026, 10, 16, 18, 0, tzinfo=SAO_PAULO),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        record.pu = Decimal("1")  # type: ignore[misc]


def test_the_latest_price_read_is_its_own_narrow_contract() -> None:
    # OQ-48: Asset fills Instrument.last_reference from this read; PriceReader stays unchanged.
    signature = inspect.signature(LatestPriceReader.get_latest_preferred_many)
    assert list(signature.parameters) == ["self", "asset_ids"]
    hints = typing.get_type_hints(LatestPriceReader.get_latest_preferred_many)
    assert hints["asset_ids"] == Collection[UUID]
    assert hints["return"] == Mapping[UUID, ReferencePriceRecord]
    assert not hasattr(PriceReader, "get_latest_preferred_many")
