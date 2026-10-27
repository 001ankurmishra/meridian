import copy
import json

import pytest

from meridian.evaluation.external.selection import (
    load_dev_protocol,
    ranked_metrics,
    select_dev_threshold,
)

pytestmark = pytest.mark.offline_guard_unit


def test_graded_metrics_distinguish_context_and_support():
    result = ranked_metrics(
        ["context", "partial", "direct"],
        {"context": 1, "partial": 2, "direct": 3},
        ["context", "partial", "direct", "other"],
    )
    assert result["hit_at_1"] is False
    assert result["precision_at_5"] == 0.4
    assert result["recall_at_5"] == 1
    assert result["mrr_at_5"] == 0.5
    assert result["ndcg_at_5"] == pytest.approx(0.6806060567)


def test_candidate_recall_survives_query_abstention():
    result = ranked_metrics([], {"a": 3, "b": 3}, ["a"])
    assert result["candidate_recall"] == 0.5
    assert result["recall_at_5"] == 0
    assert result["abstained"] is True


def test_negatives_have_no_recall_denominator():
    result = ranked_metrics(["noise"], {}, ["noise"])
    assert result["recall_at_5"] is None
    assert result["ndcg_at_5"] is None
    assert result["precision_at_5"] == 0


@pytest.mark.parametrize(
    "returned,candidates",
    [(["a", "a"], ["a"]), (["a"], ["a", "a"]), (["invented"], ["a"])],
)
def test_invalid_rankings_fail(returned, candidates):
    with pytest.raises(ValueError):
        ranked_metrics(returned, {"a": 3}, candidates)


def test_threshold_selection_handles_ties_without_claiming_calibration():
    fit = select_dev_threshold([0.5], [0.5])
    assert fit["threshold"] > 0.5
    assert fit["status"] == "EXPLORATORY_NOT_CALIBRATED"


@pytest.mark.parametrize(
    "positive,negative", [([], [1.0]), ([float("nan")], [0.0]), ([1.0], [float("inf")])]
)
def test_threshold_rejects_unusable_scores(positive, negative):
    with pytest.raises(ValueError):
        select_dev_threshold(positive, negative)


@pytest.fixture
def protocol_files(tmp_path):
    import hashlib

    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(json.dumps({"chunk_id": "a"}) + "\n")
    protocol = {
        "measurement_scope": "DEV_ONLY",
        "label_status": "PROPOSED_AI_AUTHORED_NOT_INDEPENDENTLY_VALIDATED",
        "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest(),
        "queries": [
            {
                "id": "one",
                "split": "DEV",
                "query": "Question?",
                "relevance_grades": {"a": 3},
                "expectation": "RETRIEVE",
                "family": "topic",
                "rationale": "source",
                "applicability": {"scope": "reference"},
            }
        ],
    }
    return tmp_path / "protocol.json", corpus, protocol


@pytest.mark.parametrize(
    "change", ["heldout", "unknown", "duplicate", "contradiction", "corpus", "grade"]
)
def test_protocol_fail_closed(protocol_files, change):
    path, corpus, original = protocol_files
    obj = copy.deepcopy(original)
    if change == "heldout":
        obj["queries"][0]["split"] = "HELDOUT"
    elif change == "unknown":
        obj["queries"][0]["relevance_grades"] = {"invented": 3}
    elif change == "duplicate":
        obj["queries"].append(copy.deepcopy(obj["queries"][0]))
    elif change == "contradiction":
        obj["queries"][0]["expectation"] = "ABSTAIN"
    elif change == "grade":
        obj["queries"][0]["relevance_grades"] = {"a": True}
    else:
        obj["corpus_sha256"] = "wrong"
    path.write_text(json.dumps(obj))
    with pytest.raises(ValueError):
        load_dev_protocol(path, corpus)


def test_valid_protocol(protocol_files):
    path, corpus, obj = protocol_files
    path.write_text(json.dumps(obj))
    assert load_dev_protocol(path, corpus) == obj
