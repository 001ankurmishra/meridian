import pytest

from meridian.evaluation.external.comparison import ineligible_request, paired_intervals

pytestmark = pytest.mark.offline_guard_unit


@pytest.mark.parametrize(
    "query",
    [
        "What does current Indian statutory law require?",
        "Give the binding UK reporting deadline.",
        "Provide the 2025 edition of the Basel Core Principles.",
        "What is Meridian internal training budget?",
    ],
)
def test_explicit_unavailable_source_request(query):
    assert ineligible_request(query) is not None


@pytest.mark.parametrize(
    "query",
    [
        "What does the 2020 Basel AML reference recommend?",
        "What does the 2024 Core Principles document discuss?",
        "Which risk factors affect transaction monitoring?",
        "What nonbinding international guidance might inform an Indian bank?",
    ],
)
def test_reference_requests_are_not_domestic_law_claims(query):
    assert ineligible_request(query) is None


def test_paired_bootstrap_identical_results_have_zero_delta():
    rows = [
        dict(
            id=str(i),
            family="p" if i < 2 else "n",
            expectation="RETRIEVE" if i < 2 else "ABSTAIN",
            ndcg_at_5=0.5,
            abstained=i >= 2,
        )
        for i in range(4)
    ]
    result = paired_intervals(rows, rows)
    assert result["ndcg_at_5"]["percentile_95"] == [0, 0]
    assert result["abstained"]["delta"] == 0
