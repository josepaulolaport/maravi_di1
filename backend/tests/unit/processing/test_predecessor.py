"""The predecessor rule, per day (interfaces.md "Predecessor rule, per day"; OQ-26 item 8,
OQ-31 item 4, OQ-37 item 4, OQ-40 item 5): one lazy rule for the preview and the run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pytest

from di1.modules.processing.application.services.predecessor import read_predecessor
from di1.modules.processing.domain.date_status import Chain, ChainStatus
from di1.modules.processing.domain.predecessor import PredecessorState
from tests.unit.processing.fakes import FakeChainHistory, InMemoryDateStatuses, date_status

D0 = date(2026, 10, 5)


@dataclass
class Spy(InMemoryDateStatuses):
    """Records which chains were asked for an earlier status."""

    asked: list[Chain] = field(default_factory=list)

    async def has_status_before(self, chain: Chain, day: date) -> bool:
        self.asked.append(chain)
        return await super().has_status_before(chain, day)


async def state(
    stored: ChainStatus | None,
    *,
    earlier: bool = False,
    entries: bool = False,
    statuses: Spy | None = None,
    history: FakeChainHistory | None = None,
) -> PredecessorState:
    statuses = statuses or Spy()
    if earlier:
        statuses.rows[date(2026, 10, 1)] = date_status(date(2026, 10, 1), cash=ChainStatus.FAILED)
    history = history or FakeChainHistory(first_cash_movement=D0 if entries else None)
    return await read_predecessor(Chain.CASH, D0, stored, date_statuses=statuses, history=history)


@pytest.mark.parametrize("stored", list(ChainStatus))
async def test_a_status_on_the_day_before_is_reported_as_is_without_asking_for_more(
    stored: ChainStatus,
) -> None:
    statuses, history = Spy(), FakeChainHistory()

    assert await state(stored, statuses=statuses, history=history) == stored.value
    assert (statuses.asked, history.asked) == ([], [])


async def test_an_earlier_status_alone_is_a_gap_and_the_ledger_is_not_asked() -> None:
    history = FakeChainHistory(first_cash_movement=D0)

    assert await state(None, earlier=True, history=history) is PredecessorState.NOT_PROCESSED
    assert history.asked == []


async def test_entries_of_the_chain_on_or_before_the_day_before_mean_not_processed() -> None:
    assert await state(None, entries=True) is PredecessorState.NOT_PROCESSED


async def test_no_status_and_no_entry_is_the_zero_state() -> None:
    statuses, history = Spy(), FakeChainHistory()

    assert await state(None, statuses=statuses, history=history) is PredecessorState.ZERO_STATE
    assert (statuses.asked, history.asked) == ([Chain.CASH], [(Chain.CASH, D0)])


@pytest.mark.parametrize(
    ("state_", "runs"),
    [
        (PredecessorState.PROCESSED, True),
        (PredecessorState.PROCESSED_WITH_ISSUES, True),
        (PredecessorState.ZERO_STATE, True),
        (PredecessorState.NOT_PROCESSED, False),
        (PredecessorState.FAILED, False),  # a FAILED D−1 counts as not processed (OQ-31)
        (PredecessorState.RUNNING, False),
    ],
)
def test_only_a_processed_day_before_or_the_zero_state_lets_the_date_run(
    state_: PredecessorState, runs: bool
) -> None:
    assert state_.allows_run is runs


def test_oq31_the_predecessor_has_no_stale_state() -> None:
    assert {s.value for s in PredecessorState} == {
        "PROCESSED",
        "PROCESSED_WITH_ISSUES",
        "RUNNING",
        "FAILED",
        "NOT_PROCESSED",
        "ZERO_STATE",
    }
