from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest

from meridian.evaluation.external.ibm import parse_row
from meridian.evaluation.external.intelligence import features

pytestmark = pytest.mark.offline_guard_unit
A = ("1", "A")
LOWER = datetime(2019, 1, 10)
UPPER = datetime(2019, 1, 17)


def tx(number, time, amount="10", left="A", right="B", currency="Euro"):
    return parse_row(
        [time, "1", left, "1", right, amount, currency, amount, currency, "Wire", "0"],
        number,
        allow_signed=True,
    )


def test_robust_amounts_do_not_follow_single_extreme_history():
    events = [
        tx(i, f"2019/01/0{i} 00:00", str(v))
        for i, v in enumerate([10, 10, 10, 10, 1000], 1)
    ]
    events.append(tx(6, "2019/01/10 00:00", "20"))
    result = features(A, events, LOWER, UPPER)[0]
    assert result["values"]["median_ratio"] == 2
    assert result["values"]["p95_ratio"] == 0.02
    assert result["values"]["amount"] == pytest.approx(20 / 208)
    assert result["evidence"]["prior_outgoing_rows"] == [1, 2, 3, 4, 5]


def test_future_events_and_same_timestamp_order_cannot_change_prior_features():
    events = [
        tx(1, "2019/01/09 23:00", left="B", right="A"),
        tx(2, "2019/01/10 00:00", left="A", right="B"),
        tx(3, "2019/01/10 00:00", left="C", right="A"),
    ]
    prior = features(A, events, LOWER, UPPER)
    assert prior == features(
        A, list(reversed(events)) + [tx(4, "2019/01/18 00:00", "999")], LOWER, UPPER
    )
    assert prior[0]["values"]["incoming_recency"] == pytest.approx(1 / 61)
    assert prior[0]["values"]["reciprocal_24h"] == 1
    assert prior[0]["evidence"]["prior_24h_incoming_rows"] == [1]


def test_velocity_windows_are_disjoint_and_include_boundary():
    events = [
        tx(1, "2019/01/02 00:00"),
        tx(2, "2019/01/08 23:59"),
        tx(3, "2019/01/09 00:00"),
        tx(4, "2019/01/10 00:00"),
    ]
    r = features(A, events, LOWER, UPPER)[0]
    assert r["values"]["relative_velocity"] == 7
    assert r["facts"]["preceding_week_count"] == 2
    assert r["values"]["velocity"] == 2


def test_inflow_currency_matching_and_missing_directions():
    events = [
        tx(1, "2019/01/09 23:00", "10", left="B", right="A"),
        tx(2, "2019/01/09 23:30", "100", left="C", right="A", currency="US Dollar"),
        tx(3, "2019/01/10 00:00", "10"),
    ]
    r = features(A, events, LOWER, UPPER)[0]
    assert r["values"]["inflow_amount_match"] == 1
    assert r["values"]["fan_in_24h"] == 2
    events[0] = replace(events[0], received=None)
    r = features(A, events, LOWER, UPPER)[0]
    assert r["values"]["inflow_amount_match"] is None
    assert r["values"]["reciprocal_24h"] is None
    assert r["reasons"]["inflow_amount_match"] == "UNSUPPORTED_OR_MISSING_DIRECTION"


def test_empty_history_and_local_absence_are_distinct():
    r = features(A, [tx(1, "2019/01/10 00:00")], LOWER, UPPER)[0]
    assert r["values"]["counterparty_novelty"] is None
    assert r["values"]["incoming_recency"] is None
    assert r["values"]["inflow_amount_match"] is None
    assert r["values"]["reciprocal_24h"] == 0
    assert r["values"]["fan_in_24h"] == 0


def test_self_transfers_are_not_pass_through_evidence():
    r = features(
        A,
        [
            tx(1, "2019/01/09 23:00", left="B", right="A"),
            tx(2, "2019/01/10 00:00", right="A"),
        ],
        LOWER,
        UPPER,
    )[0]
    assert r["values"]["inflow_amount_match"] is None
    assert r["reasons"]["incoming_recency"] == "TARGET_SELF_TRANSFER"


@pytest.mark.parametrize("value", [None, Decimal("-1")])
def test_invalid_history_is_unknown_not_imputed(value):
    events = [replace(tx(1, "2019/01/09 00:00"), paid=value), tx(2, "2019/01/10 00:00")]
    r = features(A, events, LOWER, UPPER)[0]
    assert r["values"]["counterparty_novelty"] is None
    assert r["values"]["median_ratio"] is None


def test_novelty_excludes_ties_and_uses_bank_account_pair():
    events = [
        tx(1, "2019/01/09 00:00"),
        tx(2, "2019/01/10 00:00", right="C"),
        tx(3, "2019/01/10 00:00", right="C"),
    ]
    r = features(A, events, LOWER, UPPER)
    assert [x["values"]["counterparty_novelty"] for x in r] == [1, 1]
    events[1] = replace(events[1], receiver_bank="2", receiver_account="B")
    assert features(A, events, LOWER, UPPER)[0]["values"]["counterparty_novelty"] == 1


def test_common_review_budget_counts_unknown_positive_as_missed():
    from meridian.evaluation.external.intelligence_eval import fixed_budget

    rows = [dict(source_row=i, score=float(i), label=0) for i in range(199)]
    rows.append(dict(source_row=199, score=None, label=1))
    m = fixed_budget(rows)
    assert m["budget"] == 2
    assert m["fp"] == 2
    assert m["recall_all_positives"] == 0


def test_binary_tie_burden_is_visible():
    from meridian.evaluation.external.intelligence_eval import fixed_budget

    rows = [dict(source_row=i, score=1, label=int(i == 99)) for i in range(100)]
    m = fixed_budget(rows)
    assert m["tied_at_cutoff"] == 100
    assert m["tp"] == 0
