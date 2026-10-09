"""
Tests for exact-name candidate matching rule exact_norm_name_v1.

Verifies:
- Exact normalized name equality (primary and alias)
- Excluded fuzzy/typo/token-reorder patterns do not match
- DOB comparison as an attribute only (never a candidate gate)
- Controlled abstention (NOT_PERFORMED)
- Homonym separation (distinct candidates per subject_key)
- Deterministic ordering and literal preservation
"""

import datetime

from meridian.agents.sanctions.matching import (
    compare_dob,
    match_customer_against_watchlist,
)
from meridian.agents.sanctions.types import (
    AbstentionReason,
    DobComparison,
    NameType,
    ScreeningOutcome,
)
from meridian.loader.watchlist_corpus import (
    SYNTHETIC_WATCHLIST_CORPUS,
)


def test_matching_primary_exact_equality() -> None:
    """Customer matching primary name produces candidate."""
    res = match_customer_against_watchlist(
        customer_name="Aurelius Vance",
        customer_dob=datetime.date(1980, 5, 15),
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res.outcome == ScreeningOutcome.CANDIDATE_MATCHES_FOUND
    assert res.reason_code is None
    assert len(res.candidates) == 1
    cand = res.candidates[0]
    assert cand.subject_key == "SUBJ-SYNTH-001"
    assert cand.dob_comparison == DobComparison.EQUAL
    assert len(cand.matched_entries) == 1
    assert cand.matched_entries[0].listed_name == "Aurelius Vance"


def test_matching_alias_exact_equality() -> None:
    """Customer matching alias name produces candidate."""
    res = match_customer_against_watchlist(
        customer_name="Kaz Drake",
        customer_dob=datetime.date(1992, 8, 4),
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res.outcome == ScreeningOutcome.CANDIDATE_MATCHES_FOUND
    assert len(res.candidates) == 1
    cand = res.candidates[0]
    assert cand.subject_key == "SUBJ-SYNTH-004"
    assert cand.matched_entries[0].name_type == NameType.ALIAS
    assert cand.matched_entries[0].listed_name == "Kaz Drake"


def test_matching_normalization_equivalence() -> None:
    """Normalization covers case, whitespace collapse, and NFKC fullwidth."""
    # Fullwidth with extra spaces
    res = match_customer_against_watchlist(
        customer_name="  Ａｕｒｅｌｉｕｓ    Ｖａｎｃｅ  ",
        customer_dob=datetime.date(1980, 5, 15),
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res.outcome == ScreeningOutcome.CANDIDATE_MATCHES_FOUND
    assert len(res.candidates) == 1
    assert res.candidates[0].subject_key == "SUBJ-SYNTH-001"


def test_matching_unrelated_negative() -> None:
    """Unrelated customer name produces NO_CANDIDATE_MATCH."""
    res = match_customer_against_watchlist(
        customer_name="Zephyr Nightingale",
        customer_dob=datetime.date(1990, 1, 1),
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res.outcome == ScreeningOutcome.NO_CANDIDATE_MATCH
    assert res.reason_code is None
    assert len(res.candidates) == 0


def test_matching_excluded_mechanisms_do_not_match() -> None:
    """
    Verifies that typos, token reordering, and substrings do NOT match.
    F11 strictly implements exact normalized equality.
    """
    # Typo: Aurelius Vancx
    res_typo = match_customer_against_watchlist(
        customer_name="Aurelius Vancx",
        customer_dob=None,
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res_typo.outcome == ScreeningOutcome.NO_CANDIDATE_MATCH

    # Token reorder: Vance Aurelius
    res_reorder = match_customer_against_watchlist(
        customer_name="Vance Aurelius",
        customer_dob=None,
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res_reorder.outcome == ScreeningOutcome.NO_CANDIDATE_MATCH

    # Substring: Aurelius
    res_sub = match_customer_against_watchlist(
        customer_name="Aurelius",
        customer_dob=None,
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res_sub.outcome == ScreeningOutcome.NO_CANDIDATE_MATCH


def test_matching_homonym_generates_distinct_candidates() -> None:
    """
    Homonym: Two distinct subjects sharing a normalized listed name ('Elena Rostova')
    generate two distinct candidates and are NEVER merged.
    """
    res = match_customer_against_watchlist(
        customer_name="Elena Rostova",
        customer_dob=datetime.date(1985, 3, 20),
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res.outcome == ScreeningOutcome.CANDIDATE_MATCHES_FOUND
    assert len(res.candidates) == 2

    # Candidates sorted deterministically by subject_key
    cand0, cand1 = res.candidates
    assert cand0.subject_key == "SUBJ-SYNTH-002"
    assert cand0.dob_comparison == DobComparison.EQUAL
    assert cand0.subject_dob == datetime.date(1985, 3, 20)

    assert cand1.subject_key == "SUBJ-SYNTH-003"
    assert cand1.dob_comparison == DobComparison.DIFFERENT
    assert cand1.subject_dob == datetime.date(1972, 11, 10)


def test_matching_dob_only_overlap_does_not_generate_candidate() -> None:
    """
    DOB agreement without name match must NEVER generate a candidate.
    DOB is an attribute, not a candidate generator.
    """
    # Customer shares DOB with Aurelius Vance (1980-05-15) but different name
    res = match_customer_against_watchlist(
        customer_name="Marcus Thorne",
        customer_dob=datetime.date(1980, 5, 15),
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res.outcome == ScreeningOutcome.NO_CANDIDATE_MATCH
    assert len(res.candidates) == 0


def test_matching_dob_does_not_suppress_candidate() -> None:
    """
    Different DOB or null DOB must NOT suppress a candidate when names match.
    """
    # Different DOB
    res_diff = match_customer_against_watchlist(
        customer_name="Aurelius Vance",
        customer_dob=datetime.date(1955, 1, 1),
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res_diff.outcome == ScreeningOutcome.CANDIDATE_MATCHES_FOUND
    assert res_diff.candidates[0].dob_comparison == DobComparison.DIFFERENT

    # Customer DOB is None
    res_null_cust = match_customer_against_watchlist(
        customer_name="Aurelius Vance",
        customer_dob=None,
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res_null_cust.outcome == ScreeningOutcome.CANDIDATE_MATCHES_FOUND
    assert res_null_cust.candidates[0].dob_comparison == DobComparison.NOT_COMPARABLE

    # Subject DOB is None (Tariq Mansoor)
    res_null_subj = match_customer_against_watchlist(
        customer_name="Tariq Mansoor",
        customer_dob=datetime.date(1990, 1, 1),
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res_null_subj.outcome == ScreeningOutcome.CANDIDATE_MATCHES_FOUND
    assert res_null_subj.candidates[0].dob_comparison == DobComparison.NOT_COMPARABLE


def test_matching_controlled_abstention_missing_name() -> None:
    """Null customer name yields controlled abstention NOT_PERFORMED."""
    res = match_customer_against_watchlist(
        customer_name=None,
        customer_dob=datetime.date(1980, 5, 15),
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res.outcome == ScreeningOutcome.NOT_PERFORMED
    assert res.reason_code == AbstentionReason.CUSTOMER_NAME_MISSING
    assert len(res.candidates) == 0


def test_matching_controlled_abstention_empty_after_normalization() -> None:
    """
    Customer name empty after normalization yields controlled abstention
    NOT_PERFORMED.
    """
    res = match_customer_against_watchlist(
        customer_name="   \u00a0 \t\n ",
        customer_dob=datetime.date(1980, 5, 15),
        watchlist_entries=SYNTHETIC_WATCHLIST_CORPUS,
    )
    assert res.outcome == ScreeningOutcome.NOT_PERFORMED
    assert (
        res.reason_code
        == AbstentionReason.CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION
    )
    assert len(res.candidates) == 0


def test_dob_comparison_semantics() -> None:
    """Direct verification of compare_dob helper."""
    d1 = datetime.date(1980, 1, 1)
    d2 = datetime.date(1980, 1, 1)
    d3 = datetime.date(1990, 5, 5)

    assert compare_dob(d1, d2) == DobComparison.EQUAL
    assert compare_dob(d1, d3) == DobComparison.DIFFERENT
    assert compare_dob(d1, None) == DobComparison.NOT_COMPARABLE
    assert compare_dob(None, d1) == DobComparison.NOT_COMPARABLE
    assert compare_dob(None, None) == DobComparison.NOT_COMPARABLE
