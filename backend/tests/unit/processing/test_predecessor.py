"""The predecessor rule, per day (interfaces.md "Predecessor rule, per day"; OQ-26 item 8,
OQ-31 item 4, OQ-37 item 4, OQ-40 item 5): one pure decision for the preview and the run."""

from __future__ import annotations

import pytest

from di1.modules.processing.domain.predecessor import (
    PredecessorFact,
    PredecessorState,
    allows_run,
    predecessor_state,
)

RECORDED = [
    PredecessorState.PROCESSED,
    PredecessorState.PROCESSED_WITH_ISSUES,
    PredecessorState.RUNNING,
    PredecessorState.FAILED,
]


@pytest.mark.parametrize("recorded", RECORDED)
def test_a_status_on_the_day_before_is_reported_as_is_without_asking_for_more(
    recorded: PredecessorState,
) -> None:
    assert predecessor_state(recorded) is recorded


def test_without_a_status_the_rule_asks_first_for_an_earlier_status() -> None:
    assert predecessor_state(None) is PredecessorFact.EARLIER_STATUS


def test_an_earlier_status_without_one_on_the_day_before_is_a_gap_and_the_ledger_is_not_asked() -> (
    None
):
    assert predecessor_state(None, has_earlier_status=True) is PredecessorState.NOT_PROCESSED


def test_with_no_status_at_all_the_rule_asks_the_ledger() -> None:
    assert predecessor_state(None, has_earlier_status=False) is PredecessorFact.CHAIN_ENTRIES


def test_entries_of_the_chain_on_or_before_the_day_before_mean_not_processed() -> None:
    state = predecessor_state(None, has_earlier_status=False, has_chain_entries=True)

    assert state is PredecessorState.NOT_PROCESSED


def test_no_status_and_no_entry_is_the_zero_state() -> None:
    state = predecessor_state(None, has_earlier_status=False, has_chain_entries=False)

    assert state is PredecessorState.ZERO_STATE


def test_a_recorded_status_wins_over_any_fact() -> None:
    state = predecessor_state(
        PredecessorState.PROCESSED, has_earlier_status=False, has_chain_entries=False
    )

    assert state is PredecessorState.PROCESSED


@pytest.mark.parametrize("derived", [PredecessorState.NOT_PROCESSED, PredecessorState.ZERO_STATE])
def test_a_derived_state_is_not_a_recorded_status(derived: PredecessorState) -> None:
    with pytest.raises(ValueError, match="recorded"):
        predecessor_state(derived)


@pytest.mark.parametrize(
    ("state", "runs"),
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
    state: PredecessorState, runs: bool
) -> None:
    assert allows_run(state) is runs


def test_oq31_the_predecessor_has_no_stale_state() -> None:
    assert {s.value for s in PredecessorState} == {
        "PROCESSED",
        "PROCESSED_WITH_ISSUES",
        "RUNNING",
        "FAILED",
        "NOT_PROCESSED",
        "ZERO_STATE",
    }
