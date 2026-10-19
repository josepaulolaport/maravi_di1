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


def test_price_reader_is_exact_dates_and_latest() -> None:
    get = inspect.signature(PriceReader.get)
    assert list(get.parameters) == ["self", "asset_ids", "dates"]
    get_hints = typing.get_type_hints(PriceReader.get)
    assert get_hints["asset_ids"] == Collection[UUID]
    assert get_hints["dates"] == Collection[date]
    assert get_hints["return"] == Mapping[tuple[UUID, date], ReferencePriceRecord]

    latest = inspect.signature(PriceReader.latest)
    assert list(latest.parameters) == ["self", "asset_ids"]
    latest_hints = typing.get_type_hints(PriceReader.latest)
    assert latest_hints["asset_ids"] == Collection[UUID]
    assert latest_hints["return"] == Mapping[UUID, ReferencePriceRecord]

    assert not hasattr(PriceReader, "get_preferred")
    assert not hasattr(PriceReader, "get_preferred_many")
    assert not hasattr(PriceReader, "get_latest_preferred_many")
