"""Shared values of Prices' integration tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from di1.modules.prices.application.services.price_service import PriceService
from di1.platform.database.unit_of_work import UnitOfWork
from tests.support.builders import DI1F28, DI1F29, DI1V26

TODAY = date(2026, 10, 19)

CONTRACTS = (DI1F28, DI1F29, DI1V26)
"""The catalogue contracts these tests price and store."""

ServiceOn = Callable[[UnitOfWork], PriceService]
"""Builds the service on a Unit of Work, as the composition does per request."""
