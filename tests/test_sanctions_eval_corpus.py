"""
Structural consistency tests for frozen synthetic evaluation corpus.

IMPORTANT VERIFICATION BOUNDARY:
Automated structural tests establish table completeness, field integrity, and
internal consistency between the review table, hand-declared candidate sets,
and frozen expected counts.
Structural tests DO NOT calculate normalized equality or prove that a manually
declared expected candidate set or matching-literal subset is semantically correct.
Semantic correctness is established exclusively by manual human review of the
original literals and documented normalization steps.
"""

from meridian.fixtures.sanctions_eval_corpus import (
    CANDIDATE_REVIEW_TABLE,
    EVAL_SUBJECT_KEYS,
    EVAL_SUBJECT_LISTED_NAMES,
    FROZEN_EXPECTED_COUNTS,
    SANCTIONS_EVAL_CASES,
    EqualityDecision,
    GroundTruth,
    get_candidate_review_table,
    get_sanctions_eval_cases,
)
from meridian.loader.watchlist_corpus import SYNTHETIC_WATCHLIST_CORPUS


def test_cartesian_product_completeness() -> None:
    """Verify table covers full Cartesian product of cases and subjects exactly once."""
    table = get_candidate_review_table()
    cases = get_sanctions_eval_cases()

    assert len(cases) == FROZEN_EXPECTED_COUNTS.total_evaluation_cases
    assert len(EVAL_SUBJECT_KEYS) == FROZEN_EXPECTED_COUNTS.total_subjects
    assert len(table) == FROZEN_EXPECTED_COUNTS.total_review_pairs

    expected_pairs = {(c.case_id, s_key) for c in cases for s_key in EVAL_SUBJECT_KEYS}
    actual_pairs = [(r.case_id, r.subject_key) for r in table]

    assert len(actual_pairs) == len(set(actual_pairs)), (
        "Duplicate pairs in review table"
    )
    assert set(actual_pairs) == expected_pairs, (
        "Review table does not match Cartesian product"
    )


def test_valid_ids_and_keys() -> None:
    """Verify all case_ids and subject_keys in review table are valid."""
    cases_by_id = {c.case_id: c for c in SANCTIONS_EVAL_CASES}
    watchlist_subject_keys = {e.subject_key for e in SYNTHETIC_WATCHLIST_CORPUS}

    for record in CANDIDATE_REVIEW_TABLE:
        assert record.case_id in cases_by_id, f"Invalid case_id: {record.case_id}"
        assert record.subject_key in watchlist_subject_keys, (
            f"Invalid subject_key: {record.subject_key}"
        )
        assert record.subject_key in EVAL_SUBJECT_KEYS


def test_ground_truth_consistency_with_planted_subjects() -> None:
    """Verify ground_truth is POSITIVE iff subject is the case's planted subject."""
    cases_by_id = {c.case_id: c for c in SANCTIONS_EVAL_CASES}

    for record in CANDIDATE_REVIEW_TABLE:
        case = cases_by_id[record.case_id]
        if case.planted_subject_key == record.subject_key:
            assert record.ground_truth == GroundTruth.POSITIVE, (
                f"Pair ({record.case_id}, {record.subject_key}) must have "
                "ground_truth=POSITIVE"
            )
        else:
            assert record.ground_truth == GroundTruth.NEGATIVE, (
                f"Pair ({record.case_id}, {record.subject_key}) must have "
                "ground_truth=NEGATIVE"
            )


def test_in_expected_candidates_consistency() -> None:
    """Verify in_expected_candidates matches case's expected candidate set."""
    cases_by_id = {c.case_id: c for c in SANCTIONS_EVAL_CASES}

    for record in CANDIDATE_REVIEW_TABLE:
        case = cases_by_id[record.case_id]
        expected_in = record.subject_key in case.expected_candidate_subject_keys
        assert record.in_expected_candidates is expected_in, (
            f"in_expected_candidates mismatch for "
            f"({record.case_id}, {record.subject_key})"
        )


def test_literals_preserve_original_declarations() -> None:
    """Verify customer literals and subject listed names match source declarations."""
    cases_by_id = {c.case_id: c for c in SANCTIONS_EVAL_CASES}

    for record in CANDIDATE_REVIEW_TABLE:
        case = cases_by_id[record.case_id]
        assert record.customer_name_literal == case.customer_name
        assert (
            record.subject_listed_names == EVAL_SUBJECT_LISTED_NAMES[record.subject_key]
        )


def test_matching_listed_name_literals_integrity() -> None:
    """
    Verify matching_listed_name_literals are valid original literals, contain
    no duplicates, and are empty for NOT_EQUAL and NO_CANDIDATE_ABSTENTION rows.
    """
    for record in CANDIDATE_REVIEW_TABLE:
        matching = record.matching_listed_name_literals
        # No duplicates
        assert len(matching) == len(set(matching)), (
            f"Duplicate matching literals in ({record.case_id}, {record.subject_key})"
        )
        # All entries must be genuine listed names for the subject
        for lit in matching:
            assert lit in record.subject_listed_names, (
                f"Literal '{lit}' is not a listed name for {record.subject_key}"
            )
        # For non-equal or abstention, matching literals must be empty
        if record.equality_decision in (
            EqualityDecision.NOT_EQUAL,
            EqualityDecision.NO_CANDIDATE_ABSTENTION,
        ):
            assert len(matching) == 0, (
                f"Matching literals must be empty for {record.equality_decision} in "
                f"({record.case_id}, {record.subject_key})"
            )
        elif record.equality_decision == EqualityDecision.EQUAL:
            assert len(matching) > 0, (
                f"Matching literals must not be empty for EQUAL in "
                f"({record.case_id}, {record.subject_key})"
            )


def test_equality_decision_rules_compliance() -> None:
    """
    Verify Section F4 equality decision rules:
    - Non-abstention case: EQUAL iff in_expected_candidates, else NOT_EQUAL
    - Abstention case: NO_CANDIDATE_ABSTENTION and in_expected_candidates is False
    - NO_CANDIDATE_ABSTENTION only appears in abstention cases
    """
    cases_by_id = {c.case_id: c for c in SANCTIONS_EVAL_CASES}

    for record in CANDIDATE_REVIEW_TABLE:
        case = cases_by_id[record.case_id]
        if case.is_abstention:
            assert record.equality_decision == EqualityDecision.NO_CANDIDATE_ABSTENTION
            assert record.in_expected_candidates is False
        else:
            assert record.equality_decision != EqualityDecision.NO_CANDIDATE_ABSTENTION
            if record.in_expected_candidates:
                assert record.equality_decision == EqualityDecision.EQUAL
            else:
                assert record.equality_decision == EqualityDecision.NOT_EQUAL


def test_manual_review_fields_and_reasoning_present() -> None:
    """Verify all rows are marked reviewed and have non-empty reasoning."""
    for record in CANDIDATE_REVIEW_TABLE:
        assert record.reviewed is True
        assert bool(record.normalization_reasoning.strip())
        assert bool(record.decision_rationale.strip())


def test_required_scenario_rationales() -> None:
    """Verify presence of specific scenario rationales."""
    table = get_candidate_review_table()

    # 1. Homonym case: CASE-SYNTH-003 has two candidate subjects, one positive,
    # one negative
    homonym_records = [
        r for r in table if r.case_id == "CASE-SYNTH-003" and r.in_expected_candidates
    ]
    assert len(homonym_records) == 2
    gt_labels = {r.ground_truth for r in homonym_records}
    assert gt_labels == {GroundTruth.POSITIVE, GroundTruth.NEGATIVE}

    # 2. DOB-only overlap: CASE-SYNTH-005 with SUBJ-SYNTH-001 explains DOB
    # agreement != candidate
    dob_record = next(
        r
        for r in table
        if r.case_id == "CASE-SYNTH-005" and r.subject_key == "SUBJ-SYNTH-001"
    )
    assert dob_record.equality_decision == EqualityDecision.NOT_EQUAL
    assert (
        "dob" in dob_record.normalization_reasoning.lower()
        or "dob" in dob_record.decision_rationale.lower()
    )

    # 3. Abstention with planted positive: CASE-SYNTH-006 with SUBJ-SYNTH-001 has
    # positive GT
    ab_record = next(
        r
        for r in table
        if r.case_id == "CASE-SYNTH-006" and r.subject_key == "SUBJ-SYNTH-001"
    )
    assert ab_record.ground_truth == GroundTruth.POSITIVE
    assert ab_record.in_expected_candidates is False
    assert ab_record.equality_decision == EqualityDecision.NO_CANDIDATE_ABSTENTION


def test_frozen_aggregate_counts_consistency() -> None:
    """Verify frozen expected aggregate counts match exact derivations from table."""
    table = get_candidate_review_table()
    cases = get_sanctions_eval_cases()
    counts = FROZEN_EXPECTED_COUNTS

    assert len(cases) == counts.total_evaluation_cases
    assert len(EVAL_SUBJECT_KEYS) == counts.total_subjects
    assert len(table) == counts.total_review_pairs

    # Ground truth
    positives = sum(1 for r in table if r.ground_truth == GroundTruth.POSITIVE)
    negatives = sum(1 for r in table if r.ground_truth == GroundTruth.NEGATIVE)
    assert positives == counts.ground_truth_positives
    assert negatives == counts.ground_truth_negatives

    # Candidates
    candidates = sum(1 for r in table if r.in_expected_candidates)
    non_candidates = sum(1 for r in table if not r.in_expected_candidates)
    assert candidates == counts.expected_candidates
    assert non_candidates == counts.expected_non_candidates

    # Decisions
    equals = sum(1 for r in table if r.equality_decision == EqualityDecision.EQUAL)
    not_equals = sum(
        1 for r in table if r.equality_decision == EqualityDecision.NOT_EQUAL
    )
    abstentions = sum(
        1
        for r in table
        if r.equality_decision == EqualityDecision.NO_CANDIDATE_ABSTENTION
    )
    assert equals == counts.decision_equal
    assert not_equals == counts.decision_not_equal
    assert abstentions == counts.decision_no_candidate_abstention

    # Candidate fidelity confusion matrix
    tp = sum(
        1
        for r in table
        if r.ground_truth == GroundTruth.POSITIVE and r.in_expected_candidates
    )
    fp = sum(
        1
        for r in table
        if r.ground_truth == GroundTruth.NEGATIVE and r.in_expected_candidates
    )
    fn = sum(
        1
        for r in table
        if r.ground_truth == GroundTruth.POSITIVE and not r.in_expected_candidates
    )
    tn = sum(
        1
        for r in table
        if r.ground_truth == GroundTruth.NEGATIVE and not r.in_expected_candidates
    )
    assert tp == counts.fidelity_true_positives
    assert fp == counts.fidelity_false_positives
    assert fn == counts.fidelity_false_negatives
    assert tn == counts.fidelity_true_negatives
