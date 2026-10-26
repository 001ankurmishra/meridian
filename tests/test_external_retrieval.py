import hashlib
import json
from pathlib import Path

import pytest

from meridian.evaluation.external.retrieval import approved_protocol, query_metrics

pytestmark = pytest.mark.offline_guard_unit


def test_ranking_metrics_use_fixed_denominator_and_positions() -> None:
    result = query_metrics(["wrong", "right"], ["right"])
    assert result["precision_at_5"] == 0.2
    assert result["recall_at_5"] == 1
    assert result["mrr_at_5"] == 0.5
    assert 0.63 < result["ndcg_at_5"] < 0.64
    abstention = query_metrics([], ["right"])
    assert abstention["abstained"]
    assert abstention["recall_at_5"] == 0
    assert query_metrics([], [])["recall_at_5"] is None


def test_freeze_rejects_changed_corpus_or_protocol(tmp_path: Path) -> None:
    corpus = tmp_path / "chunks"
    corpus.write_text("fixed")
    digest = hashlib.sha256(corpus.read_bytes()).hexdigest()
    protocol = {"corpus_sha256": digest}
    review_hash = hashlib.sha256(
        json.dumps(
            protocol,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    (tmp_path / "retrieval-review.json").write_text(json.dumps(protocol))
    (tmp_path / "retrieval-freeze.json").write_text(
        json.dumps(
            {
                "status": "FROZEN",
                "approved_review_sha256": review_hash,
                "corpus_sha256": digest,
            }
        )
    )
    assert approved_protocol(tmp_path, corpus) == protocol
    corpus.write_text("modified")
    with pytest.raises(ValueError, match="freeze mismatch"):
        approved_protocol(tmp_path, corpus)
    corpus.write_text("fixed")
    (tmp_path / "retrieval-review.json").write_text(
        json.dumps({**protocol, "extra": 1})
    )
    with pytest.raises(ValueError, match="freeze mismatch"):
        approved_protocol(tmp_path, corpus)


def test_maintainer_approved_hash_is_unchanged() -> None:
    protocol = json.loads(Path("docs/evaluation/v2/retrieval-review.json").read_text())
    digest = hashlib.sha256(
        json.dumps(
            protocol,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert digest == "d6d9a3363545c0cd6c820a3ea2367155860e2152a4d9d06828d55b91e98d1c37"
