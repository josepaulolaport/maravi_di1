"""Builders for the portfolio accounting tests: decimals from strings, fixed asset ids."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from uuid import UUID

from di1.modules.portfolio.domain.positions import OpenPosition
from di1.modules.portfolio.domain.trade import Trade

DI1F27 = UUID("00000000-0000-0000-0000-000000000027")
DI1F28 = UUID("00000000-0000-0000-0000-000000000028")
DI1F29 = UUID("00000000-0000-0000-0000-000000000029")

DAY = date(2027, 1, 4)


def trade(
    quantity: int,
    pu: str,
    rate: str = "0.1",
    *,
    asset_id: UUID = DI1F27,
    on: date = DAY,
    at: str = "10:00",
    seq: int = 1,
) -> Trade:
    return Trade(
        asset_id=asset_id,
        trade_date=on,
        trade_time=time.fromisoformat(at),
        seq=seq,
        signed_quantity=quantity,
        execution_pu=Decimal(pu),
        execution_rate=Decimal(rate),
    )


def position(quantity: int, pu: str, rate: str, *, asset_id: UUID = DI1F27) -> OpenPosition:
    return OpenPosition(
        asset_id=asset_id,
        quantity=quantity,
        average_entry_pu=Decimal(pu),
        average_entry_rate=Decimal(rate),
    )
