"""
Deterministic synthetic candidate-generation-fidelity baseline for F11 sanctions.

Measures the candidate generation implementation against the frozen synthetic
evaluation corpus, manually reviewed candidate table, and frozen expected counts.

All claims are restricted to synthetic fixture fidelity.
Does NOT measure real-world effectiveness, production performance, or regulatory
compliance. Output schemas strictly avoid forbidden benchmarking terms.
"""

import json
import sys
from typing import Any, Sequence, Union

from sqlalchemy import Connection, Engine

from meridian.agents.sanctions.matching import match_customer_against_watchlist
from meridian.agents.sanctions.reader import read_watchlist_version
from meridian.agents.sanctions.types import (
    MATCHING_RULE_ID,
    WatchlistEntry,
)
from meridian.fixtures.sanctions_eval_corpus import (
    EVAL_SUBJECT_KEYS,
    FROZEN_EXPECTED_COUNTS,
    CandidateReviewRecord,
    GroundTruth,
    SanctionsEvalCase,
    get_candidate_review_table,
    get_sanctions_eval_cases,
)
from meridian.loader.watchlist_corpus import (
    SYNTHETIC_WATCHLIST_NAME,
    SYNTHETIC_WATCHLIST_VERSION,
    get_synthetic_watchlist_corpus,
)

BASELINE_PROTOCOL: str = "synthetic_candidate_generation_fidelity_v1"

# Prohibited keys per Task 23 specification Section I
FORBIDDEN_OUTPUT_KEYS: frozenset[str] = frozenset(
    {
        "accuracy",
        "auc",
        "roc_auc",
        "f1",
        "effectiveness",
        "detection_rate",
        "coverage",
        "threshold",
        "score",
        "risk_level",
    }
)


def canonical_json(data: Any) -> str:
    """Format data as deterministic canonical JSON string."""
    return json.dumps(data, indent=2, sort_keys=True)


def measure_sanctions_baseline(
    watchlist_entries: Sequence[WatchlistEntry] | None = None,
    engine: Union[Engine, Connection, None] = None,
    eval_cases: Sequence[SanctionsEvalCase] | None = None,
    review_table: Sequence[CandidateReviewRecord] | None = None,
) -> dict[str, Any]:
    """
    Measures the exact-name matching rule against the frozen evaluation corpus.

    Args:
        watchlist_entries: Optional pre-loaded WatchlistEntry sequence.
            If None and engine is provided, reads from database via reader.
            If None and engine is None, uses in-memory synthetic corpus.
        engine: Optional SQLAlchemy Engine or Connection.
        eval_cases: Optional evaluation cases (defaults to frozen corpus).
        review_table: Optional review records (defaults to frozen table).

    Returns:
        Structured fidelity dictionary with per-case and aggregate metrics.
    """
    w_name = SYNTHETIC_WATCHLIST_NAME
    w_ver = SYNTHETIC_WATCHLIST_VERSION

    # Resolve entries source
    if watchlist_entries is None:
        if engine is not None:
            entries_to_screen = read_watchlist_version(
                engine, watchlist_name=w_name, watchlist_version=w_ver
            )
        else:
            entries_to_screen = get_synthetic_watchlist_corpus()
    else:
        entries_to_screen = tuple(watchlist_entries)

    cases = tuple(eval_cases or get_sanctions_eval_cases())
    table = tuple(review_table or get_candidate_review_table())

    review_by_pair: dict[tuple[str, str], CandidateReviewRecord] = {
        (r.case_id, r.subject_key): r for r in table
    }

    per_case_results: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []

    # Fidelity confusion matrix counters across all (case_id, subject_key) pairs
    tp_count = 0
    fp_count = 0
    fn_count = 0
    tn_count = 0

    total_measured_candidates = 0

    for case in cases:
        match_result = match_customer_against_watchlist(
            customer_name=case.customer_name,
            customer_dob=case.customer_dob,
            watchlist_entries=entries_to_screen,
            watchlist_name=w_name,
            watchlist_version=w_ver,
        )

        measured_candidate_keys = frozenset(
            c.subject_key for c in match_result.candidates
        )
        total_measured_candidates += len(measured_candidate_keys)

        case_matches_expected = (
            measured_candidate_keys == case.expected_candidate_subject_keys
        )

        if not case_matches_expected:
            mismatches.append(
                {
                    "case_id": case.case_id,
                    "mismatch_type": "CANDIDATE_SET_MISMATCH",
                    "expected": sorted(case.expected_candidate_subject_keys),
                    "measured": sorted(measured_candidate_keys),
                }
            )

        per_subject_pairs: list[dict[str, Any]] = []

        for subject_key in EVAL_SUBJECT_KEYS:
            pair_key = (case.case_id, subject_key)
            record = review_by_pair.get(pair_key)
            if record is None:
                raise ValueError(f"Missing review record for Cartesian pair {pair_key}")

            is_measured_candidate = subject_key in measured_candidate_keys
            is_expected_candidate = record.in_expected_candidates
            gt = record.ground_truth

            if is_measured_candidate != is_expected_candidate:
                mismatches.append(
                    {
                        "case_id": case.case_id,
                        "subject_key": subject_key,
                        "mismatch_type": "PAIR_DECISION_MISMATCH",
                        "expected_candidate": is_expected_candidate,
                        "measured_candidate": is_measured_candidate,
                    }
                )

            # Classify candidate fidelity
            if is_measured_candidate and gt == GroundTruth.POSITIVE:
                fidelity_class = "TRUE_POSITIVE"
                tp_count += 1
            elif is_measured_candidate and gt == GroundTruth.NEGATIVE:
                fidelity_class = "FALSE_POSITIVE"
                fp_count += 1
            elif not is_measured_candidate and gt == GroundTruth.POSITIVE:
                fidelity_class = "FALSE_NEGATIVE"
                fn_count += 1
            else:
                fidelity_class = "TRUE_NEGATIVE"
                tn_count += 1

            per_subject_pairs.append(
                {
                    "subject_key": subject_key,
                    "ground_truth": gt.value,
                    "expected_candidate": is_expected_candidate,
                    "measured_candidate": is_measured_candidate,
                    "equality_decision": record.equality_decision.value,
                    "fidelity_classification": fidelity_class,
                }
            )

        per_case_results.append(
            {
                "case_id": case.case_id,
                "case_type": case.case_type,
                "customer_name": case.customer_name,
                "customer_dob": (
                    case.customer_dob.isoformat()
                    if case.customer_dob is not None
                    else None
                ),
                "outcome": match_result.outcome.value,
                "reason_code": (
                    match_result.reason_code.value
                    if match_result.reason_code is not None
                    else None
                ),
                "planted_subject_key": case.planted_subject_key,
                "expected_candidate_subject_keys": sorted(
                    case.expected_candidate_subject_keys
                ),
                "measured_candidate_subject_keys": sorted(measured_candidate_keys),
                "case_matches_expected": case_matches_expected,
                "per_subject_pairs": per_subject_pairs,
            }
        )

    counts = FROZEN_EXPECTED_COUNTS
    frozen_counts_match = (
        len(cases) == counts.total_evaluation_cases
        and len(EVAL_SUBJECT_KEYS) == counts.total_subjects
        and (len(cases) * len(EVAL_SUBJECT_KEYS)) == counts.total_review_pairs
        and total_measured_candidates == counts.expected_candidates
        and tp_count == counts.fidelity_true_positives
        and fp_count == counts.fidelity_false_positives
        and fn_count == counts.fidelity_false_negatives
        and tn_count == counts.fidelity_true_negatives
        and len(mismatches) == 0
    )

    baseline_metrics: dict[str, Any] = {
        "baseline_protocol": BASELINE_PROTOCOL,
        "matching_rule_id": MATCHING_RULE_ID,
        "normalization_version": "v1",
        "watchlist_name": w_name,
        "watchlist_version": w_ver,
        "total_evaluation_cases": len(cases),
        "total_subjects": len(EVAL_SUBJECT_KEYS),
        "total_review_pairs": len(cases) * len(EVAL_SUBJECT_KEYS),
        "ground_truth_positives": counts.ground_truth_positives,
        "ground_truth_negatives": counts.ground_truth_negatives,
        "expected_candidates": counts.expected_candidates,
        "measured_candidates": total_measured_candidates,
        "fidelity_confusion_matrix": {
            "true_positives": tp_count,
            "false_positives": fp_count,
            "false_negatives": fn_count,
            "true_negatives": tn_count,
        },
        "mismatches": mismatches,
        "frozen_counts_match": frozen_counts_match,
        "per_case_results": per_case_results,
    }

    # Verify absence of forbidden keys
    _check_no_forbidden_keys(baseline_metrics)

    return baseline_metrics


def _check_no_forbidden_keys(data: Any, path: str = "") -> None:
    """Recursively ensure no forbidden output keys appear in baseline dictionary."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k.lower() in FORBIDDEN_OUTPUT_KEYS:
                raise ValueError(
                    f"Forbidden key '{k}' found at path '{path}.{k}' "
                    "violates Task 23 Section I specification."
                )
            _check_no_forbidden_keys(v, f"{path}.{k}" if path else k)
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            _check_no_forbidden_keys(item, f"{path}[{idx}]")


def main() -> None:
    """CLI runner for sanctions baseline."""
    res = measure_sanctions_baseline()
    print(canonical_json(res))
    if not res["frozen_counts_match"] or len(res["mismatches"]) > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
