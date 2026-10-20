"""`PortfolioService` (portfolio/public.py): the Carteira and Lançamentos reads.

Published data only, never recalculated on read (spec §11.4), except AUM, the sum of the date's
published cash and market value (OQ-21). Each date's chain statuses and
processing times come from Processing's ``DateStatusReader`` on the same Unit of Work as the
published rows, and the service's first statement makes that transaction one REPEATABLE READ,
read-only snapshot, so figures and statuses always agree (OQ-23, OQ-31; spec §13 item 12). The
service must therefore be the first to use its Unit of Work. A position row shows the
current preferred price of its date from Prices (OQ-30), marked when that price or D−1's was
registered after the date's positions chain was processed (OQ-50 item 3).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from di1.modules.asset.public import AssetReader
from di1.modules.portfolio.application.services.repository import (
    PortfolioRepository,
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.portfolio.domain.cash import CashDay
from di1.modules.portfolio.domain.maturity import is_past_maturity, reference_pu_on
from di1.modules.portfolio.domain.valuation import PriceSource
from di1.modules.portfolio.public import (
    CashSummaryView,
    PnLPointView,
    PortfolioSummaryView,
    PositionRowView,
    PositionsSummaryView,
    PositionTableView,
)
from di1.modules.prices.public import PriceReader
from di1.modules.processing.public import ChainStatus, DateStatus, DateStatusReader
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock
from di1.shared.decimals import financial_context
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail

ZERO = Decimal("0")
PROCESSED = frozenset({ChainStatus.PROCESSED, ChainStatus.PROCESSED_WITH_ISSUES})
"""The chain statuses whose published figures a read shows and combines: AUM (OQ-38, OQ-40)
and a P&L point's daily figures (OQ-41 item 4)."""


class PortfolioService:
    """Public `PortfolioService` on one Unit of Work."""

    def __init__(
        self,
        repository: PortfolioRepository,
        *,
        uow: UnitOfWork,
        assets: AssetReader,
        prices: PriceReader,
        date_statuses: DateStatusReader,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._uow = uow
        self._assets = assets
        self._prices = prices
        self._date_statuses = date_statuses
        self._clock = clock
        self._snapshot_started = False

    async def get_summary(self, on: date) -> PortfolioSummaryView:
        self._reject_future(on, "date")
        await self._snapshot()
        status = await self._status(on)
        cash = await self._repository.get_cash(on)
        day = await self._repository.get_portfolio_day(on)
        return PortfolioSummaryView(
            date=on,
            cash=CashSummaryView(
                status=None if status is None else status.cash,
                balance=None if cash is None else cash.cash_balance,
                trades_cash_flow=None if cash is None else cash.trades_cash_flow,
                deposits=None if cash is None else cash.deposits,
                withdrawals=None if cash is None else cash.withdrawals,
                published_at=None if status is None else status.cash_processed_at,
            ),
            positions=PositionsSummaryView(
                status=None if status is None else status.portfolio,
                published_at=None if status is None else status.portfolio_processed_at,
                market_value=None if day is None else day.positions_market_value,
                valuation_status=None if day is None else day.valuation_status,
                position_pnl=None if day is None else day.position_pnl,
                trades_pnl=None if day is None else day.trades_pnl,
                daily_pnl=None if day is None else day.daily_pnl,
                cumulative_pnl=None if day is None else day.cumulative_pnl,
                pnl_status=None if day is None else day.pnl_status,
            ),
            aum=_aum(status, cash, day),
        )

    async def get_position_table(self, on: date) -> PositionTableView:
        self._reject_future(on, "date")
        await self._snapshot()
        status = await self._status(on)
        published = await self._repository.get_positions(on)
        asset_ids = [p.asset_id for p in published]
        instruments = await self._assets.get_instruments(asset_ids)
        before = on - timedelta(days=1)
        prices = await self._prices.get(asset_ids, [before, on]) if asset_ids else {}
        processed_at = None if status is None else status.portfolio_processed_at
        rows = []
        for p in published:
            instrument = instruments[p.asset_id]
            maturity = instrument.maturity_date
            # After maturity no price is read: the PU is 0 by definition, with no source (OQ-1).
            price = None if is_past_maturity(on, maturity) else prices.get((p.asset_id, on))
            pu = reference_pu_on(on, maturity, None if price is None else price.pu)
            source = None if price is None else price.source
            rate = None if price is None else price.rate
            # OQ-50 item 3: the stored figures come from the D and D−1 prices the run read; one
            # registered after it (a re-saved price is a new row, OQ-25) means reprocess D.
            previous = (
                None if is_past_maturity(before, maturity) else prices.get((p.asset_id, before))
            )
            changed = processed_at is not None and any(
                used is not None and used.created_at > processed_at for used in (price, previous)
            )
            rows.append(_row(p, instrument.code, maturity, source, pu, rate, changed))
        return PositionTableView(
            date=on,
            status=None if status is None else status.portfolio,
            published_at=None if status is None else status.portfolio_processed_at,
            items=tuple(sorted(rows, key=lambda r: r.asset_code)),
        )

    async def get_pnl_series(self, start_date: date, end_date: date) -> tuple[PnLPointView, ...]:
        errors = []
        if start_date > end_date:
            errors.append(
                ErrorDetail(
                    ErrorCode.INVALID_RANGE,
                    "A data inicial deve ser anterior ou igual à data final.",
                    "start_date",
                )
            )
        if end_date > self._clock.today():
            errors.append(_future_date("end_date"))
        if errors:
            raise DomainError(*errors)
        await self._snapshot()
        statuses = await self._date_statuses.get_date_statuses(start_date, end_date, uow=self._uow)
        days = {d.date: d for d in await self._repository.get_portfolio_days(start_date, end_date)}
        points: list[PnLPointView] = []
        running = ZERO
        for offset in range((end_date - start_date).days + 1):
            current = start_date + timedelta(days=offset)
            status = statuses.get(current)
            chain = None if status is None else status.portfolio
            # A date's figures show and count only when its positions chain is processed (OQ-23,
            # OQ-41 item 4): not processed, FAILED or RUNNING show no P&L and add 0, whatever
            # older rows remain.
            day = days.get(current) if chain in PROCESSED else None
            if day is not None and day.daily_pnl is not None:
                with financial_context():
                    running = running + day.daily_pnl  # a gap or a null daily adds 0 (OQ-41)
            points.append(
                PnLPointView(
                    date=current,
                    daily_pnl=None if day is None else day.daily_pnl,
                    range_cumulative_pnl=running,
                    status=chain,
                )
            )
        return tuple(points)

    def _reject_future(self, on: date, field: str) -> None:
        """A read dated after today in São Paulo is refused (OQ-35)."""
        if on > self._clock.today():
            raise DomainError(_future_date(field))

    async def _snapshot(self) -> None:
        """Every read of this Unit of Work, the statuses included, sees one snapshot."""
        if not self._snapshot_started:
            await self._repository.start_read_snapshot()
            self._snapshot_started = True

    async def _status(self, on: date) -> DateStatus | None:
        return (await self._date_statuses.get_date_statuses(on, on, uow=self._uow)).get(on)


def _aum(
    status: DateStatus | None, cash: CashDay | None, day: PublishedPortfolioDay | None
) -> Decimal | None:
    """AUM = the date's cash + its market value, computed on read and never stored (OQ-21,
    OQ-28). It follows both chains' statuses on the date, whichever run wrote them (OQ-38,
    OQ-40): null unless both are PROCESSED or PROCESSED_WITH_ISSUES, and null when either side
    is missing, an expected asset without a price included (OQ-10)."""
    if status is None or status.cash not in PROCESSED or status.portfolio not in PROCESSED:
        return None
    if cash is None or day is None or day.positions_market_value is None:
        return None
    with financial_context():
        return cash.cash_balance + day.positions_market_value


def _future_date(field: str) -> ErrorDetail:
    return ErrorDetail(ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", field)


def _row(
    p: PublishedPosition,
    code: str,
    maturity: date | None,
    source: PriceSource | None,
    pu: Decimal | None,
    rate: Decimal | None,
    reference_price_changed: bool,
) -> PositionRowView:
    return PositionRowView(
        asset_id=p.asset_id,
        asset_code=code,
        maturity_date=maturity,
        quantity=p.quantity,
        average_entry_pu=p.average_entry_pu,
        average_entry_rate=p.average_entry_rate,
        reference_source=source,
        reference_pu=pu,
        reference_rate=rate,
        reference_price_changed=reference_price_changed,
        financial_total=p.financial_total,
        position_pnl=p.position_pnl,
        trades_pnl=p.trades_pnl,
        daily_pnl=p.daily_pnl,
        valuation_status=p.valuation_status,
        pnl_status=p.pnl_status,
    )
