"""Approved gate boundary checks and preserved ranking."""

import uuid
from unittest.mock import Mock, patch

import pytest

from meridian.agents.policy.policy_agent import (
    PolicyEvidenceFound,
    PolicyEvidenceInsufficient,
    retrieve_policy_evidence,
)


@pytest.mark.parametrize(
    "maximum,accept",
    [
        (0.620312, False),
        (0.620313, True),
        (0.9, True),
        (None, False),
        (float("nan"), False),
        (float("inf"), False),
    ],
)
def test_query_gate_and_ranking(maximum, accept):
    candidates = [
        {
            "chunk_id": uuid.uuid4(),
            "document_id": uuid.uuid4(),
            "title": "Synthetic",
            "document_type": "internal_policy",
            "version": "v1",
            "is_synthetic": True,
            "chunk_index": i,
            "chunk_text": "Synthetic policy",
            "rrf_score": 0.02,
            "query_max_cosine_similarity": maximum,
        }
        for i in range(3)
    ]
    with patch(
        "meridian.agents.policy.policy_agent.retrieve_candidates",
        return_value=candidates,
    ):
        result = retrieve_policy_evidence(
            Mock(), "query", absolute_similarity_threshold=0.620313
        )
        if accept:
            assert isinstance(result, PolicyEvidenceFound)
            assert [c.chunk_id for c in result.citations] == [
                c["chunk_id"] for c in candidates
            ]
        else:
            assert isinstance(result, PolicyEvidenceInsufficient)
        baseline = retrieve_policy_evidence(
            Mock(), "query", absolute_similarity_threshold=None
        )
        assert isinstance(baseline, PolicyEvidenceFound)


@pytest.mark.parametrize("threshold", [-2, 2, float("nan"), float("inf")])
def test_invalid_threshold_rejected(threshold):
    with patch(
        "meridian.agents.policy.policy_agent.retrieve_candidates", return_value=[]
    ):
        with pytest.raises(ValueError):
            retrieve_policy_evidence(
                Mock(), "query", absolute_similarity_threshold=threshold
            )
