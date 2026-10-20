"""Portfolio's trade input: chronological order (spec §6.1; OQ-13). A zero quantity and a trade of
another date are rejected in test_positions.py::test_an_impossible_input_is_rejected."""

from __future__ import annotations

from datetime import date

from tests.support.builders import portfolio_trade


def test_trades_order_by_date_then_time_then_seq() -> None:
    monday = date(2027, 1, 4)
    late_seq_early_time = portfolio_trade(1, "95000", on=monday, at="09:00", seq=9)
    early_seq_late_time = portfolio_trade(1, "95000", on=monday, at="11:00", seq=1)
    same_time_next_seq = portfolio_trade(1, "95000", on=monday, at="09:00", seq=10)
    previous_day = portfolio_trade(1, "95000", on=date(2027, 1, 3), at="18:00", seq=20)

    ordered = sorted(
        [early_seq_late_time, same_time_next_seq, late_seq_early_time, previous_day],
        key=lambda t: t.order_key,
    )

    assert ordered == [previous_day, late_seq_early_time, same_time_next_seq, early_seq_late_time]
