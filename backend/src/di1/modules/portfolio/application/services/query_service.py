"""`PortfolioQueryService` (portfolio/public.py): the Carteira and Lançamentos reads.

Published data only, never recalculated on read (spec §11.4). Each date's chain statuses and
processing times come from Processing's ``DateStatusReader`` on the same Unit of Work as the
published rows, and the service's first statement makes that transaction one REPEATABLE READ,
read-only snapshot, so figures and statuses always agree (OQ-23, OQ-31; spec §13 item 12). The
service must therefore be the first to use its Unit of Work. A position row shows the
current preferred price of its date from Prices (OQ-30).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from di1.modules.asset.public import AssetReader
from di1.modules.portfolio.application.interfaces.repository import (
    PortfolioRepository,
    PublishedPosition,
)
from di1.modules.portfolio.domain.valuation import ReferenceSource
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
"""The chain statuses whose published figures a read combines (OQ-38, OQ-40)."""


class PortfolioQueries:
    """Implements `di1.modules.portfolio.public.PortfolioQueryService` on one Unit of Work."""

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
            aum=day.aum if day is not None and _both_processed(status) else None,
        )

    async def get_position_table(self, on: date) -> PositionTableView:
        self._reject_future(on, "date")
        await self._snapshot()
        status = await self._status(on)
        published = await self._repository.get_positions(on)
        asset_ids = [p.asset_id for p in published]
        instruments = await self._assets.get_instruments(asset_ids)
        prices = await self._prices.get_preferred_many(asset_ids, [on]) if asset_ids else {}
        rows = []
        for p in published:
            instrument = instruments[p.asset_id]
            maturity = instrument.maturity_date
            price = prices.get((p.asset_id, on))
            if maturity is not None and on > maturity:
                # After maturity the contract is worth 0 by definition, with no price (OQ-1).
                source, pu, rate = None, ZERO, None
            elif price is None:
                source, pu, rate = None, None, None
            else:
                source, pu, rate = ReferenceSource(price.source.value), price.pu, price.rate
            rows.append(_row(p, instrument.code, maturity, source, pu, rate))
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
        running: Decimal | None = ZERO
        for offset in range((end_date - start_date).days + 1):
            current = start_date + timedelta(days=offset)
            day, status = days.get(current), statuses.get(current)
            if (
                day is None
                or status is None
                or status.portfolio is None
                or status.portfolio_processed_at is None
            ):
                running = None  # not published: the range sum is broken from here (OQ-31 item 8)
                continue
            with financial_context():
                running = (
                    None if running is None or day.daily_pnl is None else running + day.daily_pnl
                )
            points.append(
                PnLPointView(
                    date=current,
                    daily_pnl=day.daily_pnl,
                    cumulative_pnl=day.cumulative_pnl,
                    range_cumulative_pnl=running,
                    pnl_status=day.pnl_status,
                    status=status.portfolio,
                    published_at=status.portfolio_processed_at,
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


def _both_processed(status: DateStatus | None) -> bool:
    """AUM follows both chains' statuses on the date, whichever run wrote it (OQ-38, OQ-40): a
    stored AUM is shown only while neither chain is FAILED, RUNNING or not processed."""
    return status is not None and status.cash in PROCESSED and status.portfolio in PROCESSED


def _future_date(field: str) -> ErrorDetail:
    return ErrorDetail(ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", field)


def _row(
    p: PublishedPosition,
    code: str,
    maturity: date | None,
    source: ReferenceSource | None,
    pu: Decimal | None,
    rate: Decimal | None,
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
        financial_total=p.financial_total,
        position_pnl=p.position_pnl,
        trades_pnl=p.trades_pnl,
        daily_pnl=p.daily_pnl,
        valuation_status=p.valuation_status,
        pnl_status=p.pnl_status,
    )
