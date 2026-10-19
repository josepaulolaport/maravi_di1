"""Asset's public contract: what other modules may know about an instrument (interfaces.md "Asset").

Frozen in W0.3b; the catalogue type and the cross-module read are the same `Instrument`
(integrator simplify). Lane A implements `AssetReader`; changes go through the integrator.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Protocol
from uuid import UUID

from di1.modules.asset.domain.model import Instrument as Instrument

__all__ = ["AssetReader", "Instrument"]


class AssetReader(Protocol):
    """Read access for Pricing, Ledger, Prices, Portfolio and Processing."""

    async def get_instruments(self, instrument_ids: Collection[UUID]) -> Mapping[UUID, Instrument]:
        """The instruments that exist among ``instrument_ids``; unknown ids are absent.
        A caller that needs 404 raises it itself (Pricing)."""
        ...
