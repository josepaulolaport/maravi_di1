"""Pricing's module-local factory (interfaces.md "DI composition"). The composition root wires it
for Ledger and Prices, passing Asset's `AssetReader` on the caller's session, so the read sees the
caller's transaction."""

from __future__ import annotations

from di1.modules.asset.public import AssetReader
from di1.modules.pricing.application.services.pricing_service import DefaultPricingService
from di1.modules.pricing.public import PricingService


def build_pricing_service(assets: AssetReader) -> PricingService:
    return DefaultPricingService(assets)
