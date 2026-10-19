"""Pricing's frozen public contract (plan §3, W0.3c; interfaces.md "Pricing")."""

from __future__ import annotations

import dataclasses
import inspect
from decimal import Decimal

import pytest

from di1.modules.pricing.public import InputKind, Price, PricingService, Quote
from di1.shared import input_kind


def test_input_kind_is_the_shared_one() -> None:
    assert InputKind is input_kind.InputKind


def test_a_quote_records_what_was_typed() -> None:
    assert Quote(InputKind.PU, Decimal("90000")).kind == InputKind.PU
    assert Quote(InputKind.RATE, Decimal("0.1")).kind == InputKind.RATE


def test_a_price_is_a_frozen_complete_pair() -> None:
    price = Price(pu=Decimal("90000"), rate=Decimal("0.1"), input_kind=InputKind.PU)

    with pytest.raises(dataclasses.FrozenInstanceError):
        price.pu = Decimal("1")  # type: ignore[misc]


def test_calculate_takes_the_instrument_id() -> None:
    parameters = list(inspect.signature(PricingService.calculate).parameters)

    assert parameters == ["self", "instrument_id", "reference_date", "quote"]
