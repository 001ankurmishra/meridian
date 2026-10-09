"""
Tests for deterministic synthetic sanctions evaluation baseline.

Verifies:
- In-memory measurement matches frozen expected counts with zero mismatches.
- Database-backed measurement (app-role read) matches in-memory measurement.
- Prohibition of forbidden benchmarking keys (accuracy, auc, f1, etc.).
- Robust detection and reporting of candidate mismatches.
- Determinism and CLI runner behavior.
"""

import json
import os
import subprocess
import sys

import pytest
from sqlalchemy import Engine, text

from meridian.fixtures.sanctions_baseline import (
    FORBIDDEN_OUTPUT_KEYS,
    _check_no_forbidden_keys,
    canonical_json,
    measure_sanctions_baseline,
)
from meridian.fixtures.sanctions_eval_corpus import (
    FROZEN_EXPECTED_COUNTS,
    SANCTIONS_EVAL_CASES,
    SanctionsEvalCase,
)
from meridian.loader.watchlist_corpus import get_synthetic_watchlist_corpus
from meridian.loader.watchlist_ingest import ingest_watchlist_version


def test_baseline_in_memory_agreement() -> None:
    """
    Verify in-memory measurement matches frozen expected counts with zero mismatches.
    """
    res = measure_sanctions_baseline()

    assert res["frozen_counts_match"] is True
    assert len(res["mismatches"]) == 0
    assert res["total_evaluation_cases"] == 8
    assert res["total_subjects"] == 5
    assert res["total_review_pairs"] == 40

    matrix = res["fidelity_confusion_matrix"]
    assert matrix["true_positives"] == FROZEN_EXPECTED_COUNTS.fidelity_true_positives
    assert matrix["false_positives"] == FROZEN_EXPECTED_COUNTS.fidelity_false_positives
    assert matrix["false_negatives"] == FROZEN_EXPECTED_COUNTS.fidelity_false_negatives
    assert matrix["true_negatives"] == FROZEN_EXPECTED_COUNTS.fidelity_true_negatives

    assert matrix["true_positives"] == 3
    assert matrix["false_positives"] == 1
    assert matrix["false_negatives"] == 1
    assert matrix["true_negatives"] == 35


def test_baseline_db_backed_integration(
    loader_role_engine: Engine,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """
    Verify DB-backed reader measurement matches frozen counts and in-memory results.
    """
    # Clean and seed watchlist
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM watchlist_entries"))

    corpus = get_synthetic_watchlist_corpus()
    ingest_watchlist_version(loader_role_engine, corpus)

    try:
        # Measure using read-only application role
        res_db = measure_sanctions_baseline(engine=app_role_engine)
        res_mem = measure_sanctions_baseline()

        assert res_db["frozen_counts_match"] is True
        assert len(res_db["mismatches"]) == 0

        # Assert canonical JSON equivalence
        assert canonical_json(res_db) == canonical_json(res_mem)
    finally:
        with superuser_engine.begin() as conn:
            conn.execute(text("DELETE FROM watchlist_entries"))


def test_baseline_forbidden_output_keys_prohibited() -> None:
    """
    Architecture and specification guard:
    Ensure no forbidden benchmarking keys appear in the baseline output dictionary.
    """
    res = measure_sanctions_baseline()

    def _collect_keys(data: object) -> set[str]:
        keys = set()
        if isinstance(data, dict):
            for k, v in data.items():
                keys.add(k.lower())
                keys.update(_collect_keys(v))
        elif isinstance(data, list):
            for item in data:
                keys.update(_collect_keys(item))
        return keys

    found_keys = _collect_keys(res)
    intersection = found_keys.intersection(FORBIDDEN_OUTPUT_KEYS)
    assert not intersection, (
        f"Forbidden output keys present in baseline: {intersection}"
    )

    # Also verify helper raises when a forbidden key is injected
    with pytest.raises(ValueError, match="Forbidden key"):
        _check_no_forbidden_keys({"accuracy": 0.95})

    with pytest.raises(ValueError, match="Forbidden key"):
        _check_no_forbidden_keys({"nested": [{"threshold": 0.5}]})


def test_baseline_mismatch_detection() -> None:
    """
    Verify that an unexpected candidate result is detected and flagged in mismatches.
    """
    # Create altered evaluation case expecting wrong candidates
    altered_case = SanctionsEvalCase(
        case_id="CASE-SYNTH-001",
        customer_name="Aurelius Vance",
        customer_dob=None,
        planted_subject_key="SUBJ-SYNTH-001",
        expected_candidate_subject_keys=frozenset({"SUBJ-SYNTH-002"}),  # WRONG
        is_abstention=False,
        abstention_reason=None,
        case_type="TEST_ALTERED",
        case_rationale="Test mismatch detection",
    )

    cases = [
        altered_case if c.case_id == "CASE-SYNTH-001" else c
        for c in SANCTIONS_EVAL_CASES
    ]
    res = measure_sanctions_baseline(eval_cases=cases)

    assert res["frozen_counts_match"] is False
    assert len(res["mismatches"]) > 0
    mismatch_types = {m["mismatch_type"] for m in res["mismatches"]}
    assert "CANDIDATE_SET_MISMATCH" in mismatch_types


def test_baseline_cli_execution() -> None:
    """Verify running sanctions_baseline as module via python -m exits 0."""
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    cmd = [sys.executable, "-m", "meridian.fixtures.sanctions_baseline"]
    sub = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)

    assert sub.returncode == 0
    data = json.loads(sub.stdout)
    assert data["frozen_counts_match"] is True
    assert data["fidelity_confusion_matrix"]["true_positives"] == 3
