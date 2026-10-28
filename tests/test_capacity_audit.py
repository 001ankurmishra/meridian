import pytest

from meridian.evaluation.external.capacity import tie_bounds

pytestmark = pytest.mark.offline_guard_unit


def test_ties_expose_uncertain_capacity_utility():
    rows = [dict(source_row=i, score=1, label=int(i < 2)) for i in range(100)]
    assert tie_bounds(rows, 10)["tp_min"] == 0
    assert tie_bounds(rows, 10)["tp_max"] == 2


def test_above_cutoff_positives_are_fixed():
    rows = [
        dict(source_row=0, score=2, label=1),
        dict(source_row=1, score=1, label=0),
        dict(source_row=2, score=1, label=1),
        dict(source_row=3, score=None, label=1),
    ]
    m = tie_bounds(rows, 2)
    assert (m["tp_min"], m["tp_max"]) == (1, 2)
    assert tie_bounds(rows, 100)["tp_min"] == 2
    assert tie_bounds(rows, 0)["reviewed"] == 0
