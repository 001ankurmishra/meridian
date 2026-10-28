from pathlib import Path

import pytest

from meridian.evaluation.external.financial import (
    Components,
    account_features,
    component_split,
    ranking_metrics,
    uncertainty,
)
from meridian.evaluation.external.ibm import parse_row
from meridian.evaluation.external.references import chunks

pytestmark = pytest.mark.offline_guard_unit


def tx(time: str, amount: str, number: int, currency: str = "Euro"):
    return parse_row(
        [time, "1", "A", "2", "B", amount, currency, amount, currency, "Wire", "0"],
        number,
    )


def test_temporal_bounds_and_ties() -> None:
    history = [
        tx("2019/01/01 00:00", "10", 2),
        tx("2019/01/02 00:00", "20", 3),
        tx("2019/01/02 00:00", "100", 4),
        tx("2019/01/02 00:01", "10", 5),
    ]
    features = account_features(history[::-1])
    assert [f["velocity"] for f in features] == [1, 3, 3, 3]
    assert [f["amount"] for f in features[:3]] == [None, 2.0, 10.0]
    # Adding future data cannot change earlier values.
    assert account_features(history[:3]) == features[:3]


def test_missing_and_currency_never_imputed() -> None:
    features = account_features(
        [tx("2019/01/01 00:00", "(null)", 2), tx("2019/01/02 00:00", "20", 3)]
    )
    assert all(f["amount"] is None for f in features)
    assert features[-1]["amount_reason"] == "MISSING_AMOUNT_OR_CURRENCY"
    mixed = account_features(
        [tx("2019/01/01 00:00", "10", 2), tx("2019/01/02 00:00", "20", 3, "US Dollar")]
    )
    assert mixed[-1]["amount_reason"] == "CURRENCY_MISMATCH"


def test_signed_source_amounts_remain_unknown_and_expire() -> None:
    signed = parse_row(
        [
            "2019/01/01 00:00",
            "1",
            "A",
            "2",
            "B",
            "-10",
            "Euro",
            "-10",
            "Euro",
            "Wire",
            "0",
        ],
        2,
        allow_signed=True,
    )
    features = account_features([signed, tx("2019/01/02 00:01", "20", 3)])
    assert features[0]["velocity"] is None
    assert features[1]["velocity"] == 1
    assert features[1]["amount_reason"] == "UNSUPPORTED_SIGNED_AMOUNT"


def test_metric_ties_and_capacity() -> None:
    rows = [
        {"source_row": i, "score": 1, "label": label, "reason": None}
        for i, label in enumerate([0, 1])
    ]
    result = ranking_metrics(rows)
    assert result["roc_auc"] == 0.5
    assert result["average_precision"] == 0.5
    assert (result["tp"], result["fp"], result["fn"], result["tn"]) == (0, 1, 1, 0)
    rows[1]["score"] = 2
    assert ranking_metrics(rows)["roc_auc"] == 1
    assert ranking_metrics(rows)["average_precision"] == 1


def test_component_split_preserves_observed_graph() -> None:
    c = Components()
    a, b, d = ("1", "A"), ("2", "B"), ("3", "C")
    c.join(b, d)
    c.join(a, b)
    assert c.find(d) == a
    assert len({component_split(c.find(n), "seed") for n in [a, b, d]}) == 1


def test_uncertainty_refuses_one_component() -> None:
    rows = [{"score": i, "label": i % 2, "component": "one"} for i in range(20)]
    assert uncertainty(rows, 42)["status"] == "NOT_ESTIMABLE"


def test_chunking_token_ceiling_and_progress() -> None:
    text = " ".join("x" * 90 for _ in range(100))
    result = chunks(text, len)
    assert len(result) == 25
    assert all(len(c) <= 400 for c in result)
    assert all(c in text for c in result)
    with pytest.raises(ValueError, match="Unchunkable"):
        chunks("x" * 500, len)


def test_reference_blank_page_manifest() -> None:
    import json

    spec = json.loads(Path("docs/evaluation/v2/reference-sources.json").read_text())
    assert all(s["verified_blank_pdf_pages"] == [4] for s in spec["sources"])
    assert all(s["document_type"] == "external_reference" for s in spec["sources"])
