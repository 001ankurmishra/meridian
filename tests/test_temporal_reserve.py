import json
from dataclasses import replace
from decimal import Decimal

import pytest

from meridian.evaluation.external.ibm import parse_row
from meridian.evaluation.external.intelligence import features
from meridian.evaluation.external.temporal import (
    LOWER,
    SELECTED,
    UPPER,
    budget_metrics,
    evidence_key,
    selected_features,
    validate_lock,
)

pytestmark = pytest.mark.offline_guard_unit
A = ("1", "A")


def tx(i, stamp, left="A", right="B", value="10"):
    return parse_row(
        [stamp, "1", left, "1", right, value, "Euro", value, "Euro", "Wire", "0"],
        i,
        allow_signed=True,
    )


@pytest.mark.parametrize("problem", [None, "signed", "missing", "currency", "self"])
def test_selected_adapter_preserves_frozen_formulas(problem):
    data = [
        tx(1, "2019/01/08 00:00"),
        tx(2, "2019/01/09 00:00"),
        tx(3, "2019/01/16 00:00"),
        tx(4, "2019/01/16 23:00", "B", "A"),
        tx(5, "2019/01/17 00:00"),
        tx(6, "2019/01/17 00:00", "C", "A"),
        tx(7, "2019/01/18 00:00"),
    ]
    if problem == "signed":
        data[3] = replace(data[3], paid=Decimal("-1"))
    if problem == "missing":
        data[0] = replace(data[0], paid=None)
    if problem == "currency":
        data[0] = replace(data[0], payment_currency="US Dollar")
    if problem == "self":
        data[4] = replace(data[4], receiver_account="A")
    original = features(A, data, LOWER, UPPER)
    actual = selected_features(A, data)
    assert len(original) == len(actual)
    for old, new in zip(original, actual, strict=True):
        assert old["tx"] == new["tx"]
        for name in SELECTED:
            assert old["values"][name] == new["values"][name]
            assert old["reasons"][name] == new["reasons"][name]


def test_reserve_future_ties_and_source_identity():
    data = [
        tx(1, "2019/01/16 23:59", "B", "A"),
        tx(2, "2019/01/17 00:00"),
        tx(3, "2019/01/17 00:00", "C", "A"),
    ]
    r = selected_features(A, data)
    assert r == selected_features(A, data[::-1] + [tx(4, "2019/01/24 00:00", "D", "A")])
    assert r[0]["evidence"]["prior_24h_incoming_rows"] == [1]
    assert r[0]["values"]["reciprocal_24h"] == 1
    assert evidence_key("lock", A, 2, "fan_in_24h") == evidence_key(
        "lock", A, 2, "fan_in_24h"
    )
    assert len({evidence_key("lock", A, i, "fan_in_24h") for i in (2, 3)}) == 2
    assert evidence_key("lock", A, 2, "fan_in_24h") != evidence_key(
        "other", A, 2, "fan_in_24h"
    )


def test_fixed_budget_does_not_expand_with_target_count():
    r = [dict(source_row=i, score=float(i), label=0) for i in range(500)]
    r.append(dict(source_row=500, score=None, label=1))
    m = budget_metrics(r)
    assert m["reviewed"] == 278 and m["fp"] == 278 and m["fn_all_targets"] == 1


def test_protocol_rejects_unlocked_selection(tmp_path):
    p = tmp_path / "lock.json"
    p.write_text(json.dumps({"selected": ["invented"]}))
    with pytest.raises(ValueError, match="definitions"):
        validate_lock(p)
