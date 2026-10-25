"""Independent ranking oracles and approved payload identity checks."""

import hashlib
import itertools
import json
from pathlib import Path

import pytest

from meridian.evaluation import policy
from meridian.evaluation.policy_metrics import score_ranking
from meridian.fixtures.policy_retrieval_eval_set import build_eval_set, canonical_json


def test_random_baselines_match_exhaustive_permutations():
    grades = [2, 1, 1, 0, 0]
    scores = [
        score_ranking(grades, list(order)) for order in itertools.permutations(range(5))
    ]
    for definition in ("strict", "lenient", "graded"):
        for metric, expected in scores[0][definition]["random"].items():
            actual = sum(row[definition]["observed"][metric] for row in scores) / len(
                scores
            )
            assert actual == pytest.approx(expected, abs=1e-12)
    ideal = score_ranking(grades, list(range(5)))
    assert ideal["strict"]["observed"]["RR"] == 1
    assert ideal["graded"]["observed"]["nDCG@5"] == 1


def test_zero_relevance_excluded_and_bad_ranking_rejected():
    result = score_ranking([0] * 5, list(range(5)))
    assert all(value["excluded"] for value in result.values())
    with pytest.raises(ValueError):
        score_ranking([2, 1, 0, 0, 0], [0, 0, 1, 2, 3])


def test_freeze_preserves_approved_labels_and_review_hash():
    root = policy.EVALUATION_DIR
    review = json.loads((root / "policy_retrieval_eval_v1.review.json").read_text())
    record = json.loads((root / "policy_retrieval_eval_v1.freeze.json").read_text())
    reviewed_bytes = json.dumps(
        review, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    assert hashlib.sha256(reviewed_bytes).hexdigest() == record["reviewed_sha256"]
    frozen = json.loads(canonical_json(build_eval_set()))
    assert {key for key in frozen if frozen[key] != review[key]} == {
        "protocol_status",
        "labeler_provenance",
    }
    assert policy.validate_freeze() == record["frozen_sha256"]
    assert not record["independently_validated"]


def test_invalid_freeze_blocks_measurement(tmp_path: Path, monkeypatch):
    record = {"status": "PROPOSED", "frozen_sha256": "wrong", "approved_by": ""}
    (tmp_path / "policy_retrieval_eval_v1.freeze.json").write_text(json.dumps(record))
    monkeypatch.setattr(policy, "EVALUATION_DIR", tmp_path)
    with pytest.raises(ValueError, match="approved frozen"):
        policy.validate_freeze()


def test_pinned_tokenizer_reproduces_all_frozen_chunk_hashes():
    from meridian.agents.policy.chunking import chunk_document
    from meridian.loader.policy_corpus import POLICY_CORPUS_V1

    expected = {
        (r.title, r.version, r.chunk_index): r.text_sha256
        for r in build_eval_set().chunk_refs
    }
    actual = {
        (doc.title, doc.version, i): hashlib.sha256(chunk.encode()).hexdigest()
        for doc in POLICY_CORPUS_V1
        for i, chunk in enumerate(chunk_document(doc.text))
    }
    assert actual == expected


def test_heldout_receipt_prevents_second_measurement(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "EVALUATION_DIR", tmp_path)
    receipt = policy.claim_heldout("test-digest")
    assert json.loads(receipt.read_text())["status"] == "STARTED"
    with pytest.raises(FileExistsError):
        policy.claim_heldout("test-digest")
