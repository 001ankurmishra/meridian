import asyncio
import json

import pytest

from meridian.copilot.budget import BudgetError, BudgetLedger
from meridian.copilot.explanations import assess_explanation
from meridian.copilot.synthetic import fixtures, identify_payload, synthetic_package
from meridian.evaluation.copilot_pilot import (
    MOCK_PILOT_ID,
    proposed_output,
    run_mock_suite,
)

pytestmark = pytest.mark.offline_guard_unit


def test_experimental_default_is_disabled_and_never_releases_unreviewed_claim():
    item = fixtures()[0]
    package = synthetic_package(item["id"])
    raw = proposed_output(item)
    assert assess_explanation(raw, package).reason == "EXPERIMENT_DISABLED"
    result = assess_explanation(raw, package, enabled=True)
    assert (
        result.status == "UNAVAILABLE" and result.reason == "SEMANTIC_REVIEW_REQUIRED"
    )
    assert result.semantic_support is None
    assert (
        result.schema_compliant and result.citations_valid and result.numeric_fidelity
    )


def test_numbers_and_citations_do_not_validate_semantics():
    item = next(f for f in fixtures() if f["id"] == "semantic_trap")
    result = assess_explanation(
        proposed_output(item), synthetic_package(item["id"]), True
    )
    assert result.numeric_fidelity and result.citations_valid
    assert result.status == "UNAVAILABLE" and result.semantic_support is None


@pytest.mark.parametrize(
    "fixture_id",
    [
        "contradictory",
        "incorrect_numbers",
        "fabricated_citation",
        "prompt_injection",
        "regulatory",
        "sanctions",
        "cross_investigation",
        "omission",
    ],
)
def test_security_and_grounding_failures_remain_unavailable(fixture_id):
    item = next(f for f in fixtures() if f["id"] == fixture_id)
    result = assess_explanation(
        proposed_output(item), synthetic_package(fixture_id), True
    )
    assert result.status == "UNAVAILABLE" and result.reason == "MECHANICAL_REJECTION"


def test_model_cannot_certify_its_own_faithfulness():
    item = fixtures()[0]
    payload = json.loads(proposed_output(item))
    payload["independently_verified"] = True
    result = assess_explanation(
        json.dumps(payload), synthetic_package(item["id"]), True
    )
    assert result.reason == "INVALID_SCHEMA"


def test_synthetic_identity_and_registry_hash(tmp_path, monkeypatch):
    package = synthetic_package("supported")
    assert identify_payload(package.payload()) == "supported"
    with pytest.raises(ValueError, match="SYNTHETIC_ONLY"):
        identify_payload(package.payload().replace("100.00", "200.00"))
    damaged = tmp_path / "fixtures.json"
    damaged.write_text('{"is_synthetic":true}')
    monkeypatch.setattr("meridian.copilot.synthetic.FIXTURE_PATH", damaged)
    with pytest.raises(ValueError, match="SYNTHETIC_FIXTURE_CHANGED"):
        fixtures()


def test_complete_mock_suite_separates_mechanics_from_real_model_metrics(tmp_path):
    path = tmp_path / "ledger.json"
    BudgetLedger(path, pilot_id=MOCK_PILOT_ID).initialize()
    result = asyncio.run(run_mock_suite(path))
    assert result["expectations_met"] == len(result["records"]) == 13
    assert result["live_requests"] == 0 and result["model_executed"] is None
    assert all(row["actual_token_usage"] is None for row in result["records"])
    assert all(row["semantic_claim_support"] is None for row in result["records"])
    with pytest.raises(ValueError, match="NEW_BENCHMARK_LEDGER"):
        asyncio.run(run_mock_suite(path))


def test_mock_runner_fails_closed_without_initialized_budget(tmp_path):
    path = tmp_path / "missing-ledger.json"
    with pytest.raises(BudgetError, match="LEDGER_MISSING_OR_UNINITIALIZED"):
        asyncio.run(run_mock_suite(path))
    assert not path.exists()
    assert not path.with_suffix(".json.lock").exists()
