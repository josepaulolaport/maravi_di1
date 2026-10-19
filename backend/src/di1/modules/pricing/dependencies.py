"""Pricing's module-local factory (interfaces.md "DI composition"). The composition root wires it
for Ledger and Prices: from its providers (HTTP) and plain factories (workers), passing Asset's
`AssetReader` on the caller's session, so the read sees the caller's transaction."""

from __future__ import annotations

from di1.modules.asset.public import AssetReader
from di1.modules.pricing.application.services.pricing_service import InstrumentPricingService
from di1.modules.pricing.domain.futures.di1 import DI1Calculator
from di1.modules.pricing.public import PricingService


def pricing_service(asset_reader: AssetReader) -> PricingService:
    """`PricingService` over ``asset_reader``; the calculator is stateless and pure."""
    return InstrumentPricingService(asset_reader, DI1Calculator())
