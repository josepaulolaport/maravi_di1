"""Each date's status per chain (OQ-21, OQ-23, OQ-31; schema ``processing.date_status``).

A date with no status is "Não processado". No date is stored RUNNING (OQ-50 item 4): a run takes
each date from its old status straight to its new one in one transaction, and a read shows
"Processando" for the active run's current date (`with_active_run`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum


class Chain(StrEnum):
    """One of the two daily chains (OQ-21): the one name used for a date's status column, a
    run's ``failed_chain`` and a Pendência's chain. ``POSITIONS`` is the ``portfolio`` column."""

    CASH = "CASH"
    POSITIONS = "POSITIONS"


class ChainStatus(StrEnum):
    """The status of one chain on one date (schema ``processing.date_status``)."""

    PROCESSED = "PROCESSED"
    """Processado."""
    PROCESSED_WITH_ISSUES = "PROCESSED_WITH_ISSUES"
    """Processado com pendências: a missing price or an expired open position."""
    RUNNING = "RUNNING"
    """Processando: derived on read for the active run, never stored (OQ-50 item 4)."""
    FAILED = "FAILED"
    """Erro: the run failed on this date, e.g. its day before was not processed (OQ-31)."""

    @property
    def is_processed(self) -> bool:
        """Whether the chain's figures of the date may be shown and combined: AUM (OQ-38), a P&L
        point (OQ-41) and the next date's predecessor (OQ-31)."""
        return self in (ChainStatus.PROCESSED, ChainStatus.PROCESSED_WITH_ISSUES)


@dataclass(frozen=True, slots=True)
class DateStatus:
    """Both chains on one date; ``None`` is "not processed". Each ``*_processed_at`` is when a
    run last committed that chain for the date, shown as "Processado em dd/mm/aaaa hh:mm";
    ``None`` if never (OQ-31)."""

    date: date
    portfolio: ChainStatus | None = None
    cash: ChainStatus | None = None
    portfolio_processed_at: datetime | None = None
    cash_processed_at: datetime | None = None

    def status(self, chain: Chain) -> ChainStatus | None:
        return self.cash if chain is Chain.CASH else self.portfolio

    def settled(
        self, chain: Chain, status: ChainStatus, processed_at: datetime | None
    ) -> DateStatus:
        """``chain`` set to its new status; ``processed_at`` replaces the chain's processing time
        when given (a FAILED date keeps the old one)."""
        if chain is Chain.CASH:
            return replace(
                self, cash=status, cash_processed_at=processed_at or self.cash_processed_at
            )
        return replace(
            self,
            portfolio=status,
            portfolio_processed_at=processed_at or self.portfolio_processed_at,
        )


def with_active_run(
    statuses: Mapping[date, DateStatus],
    *,
    current_date: date | None,
    live_chains: tuple[Chain, ...],
    start_date: date,
    end_date: date,
) -> dict[date, DateStatus]:
    """``statuses`` of [start_date, end_date] as the screens show them: the active run's
    ``current_date`` (``None`` without one) is RUNNING for its ``live_chains``; its processing
    times stay as stored."""
    shown = dict(statuses)
    if current_date is None or not start_date <= current_date <= end_date:
        return shown
    status = shown.get(current_date, DateStatus(current_date))
    for chain in live_chains:
        status = status.settled(chain, ChainStatus.RUNNING, None)
    shown[current_date] = status
    return shown
