"""Prices' frozen public contract (plan §3, W0.3b; interfaces.md "Prices")."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.shared.clock import SAO_PAULO
from di1.shared.input_kind import InputKind


def test_price_source_matches_the_schema_check() -> None:
    assert {source.value for source in PriceSource} == {"MANUAL", "B3"}


def test_a_reference_price_is_traceable_to_its_revision() -> None:
    record = ReferencePriceRecord(
        id=uuid4(),
        asset_id=uuid4(),
        reference_date=date(2026, 10, 16),
        source=PriceSource.MANUAL,
        input_kind=InputKind.RATE,
        pu=Decimal("98765.4321000000"),
        rate=Decimal("0.135000000000"),
        revision=2,
        created_at=datetime(2026, 10, 16, 18, 0, tzinfo=SAO_PAULO),
        superseded_at=None,
    )

    assert record.revision == 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.pu = Decimal("1")  # type: ignore[misc]
