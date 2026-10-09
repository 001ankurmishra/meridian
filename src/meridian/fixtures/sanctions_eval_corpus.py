"""
Deterministic synthetic evaluation corpus for F11 sanctions screening.

Defines the frozen evaluation cases, the Cartesian product review universe,
the manually authored CANDIDATE_REVIEW_TABLE, and frozen expected aggregate counts.

All cases and subjects are synthetic constructs created exclusively for
automated evaluation and regression testing. No real personal data is present.
"""

import datetime
from dataclasses import dataclass
from enum import Enum

from meridian.agents.sanctions.types import AbstentionReason


class GroundTruth(str, Enum):
    """Ground-truth label for a candidate review pair."""

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


class EqualityDecision(str, Enum):
    """Decision on whether customer name equals subject listed name."""

    EQUAL = "EQUAL"
    NOT_EQUAL = "NOT_EQUAL"
    NO_CANDIDATE_ABSTENTION = "NO_CANDIDATE_ABSTENTION"


@dataclass(frozen=True)
class SanctionsEvalCase:
    """A hand-declared synthetic evaluation case."""

    case_id: str
    customer_name: str | None
    customer_dob: datetime.date | None
    planted_subject_key: str | None
    expected_candidate_subject_keys: frozenset[str]
    is_abstention: bool
    abstention_reason: AbstentionReason | None
    case_type: str
    case_rationale: str


@dataclass(frozen=True)
class CandidateReviewRecord:
    """
    Manually authored review record for a single (case_id, subject_key) pair.
    """

    case_id: str
    subject_key: str
    ground_truth: GroundTruth
    in_expected_candidates: bool
    customer_name_literal: str | None
    subject_listed_names: tuple[str, ...]
    matching_listed_name_literals: tuple[str, ...]
    normalization_reasoning: str
    equality_decision: EqualityDecision
    decision_rationale: str
    reviewed: bool = True


# =====================================================================
# 1. EVALUATION CASES
# =====================================================================

SANCTIONS_EVAL_CASES: tuple[SanctionsEvalCase, ...] = (
    SanctionsEvalCase(
        case_id="CASE-SYNTH-001",
        customer_name="Aurelius Vance",
        customer_dob=datetime.date(1980, 5, 15),
        planted_subject_key="SUBJ-SYNTH-001",
        expected_candidate_subject_keys=frozenset({"SUBJ-SYNTH-001"}),
        is_abstention=False,
        abstention_reason=None,
        case_type="IN_SCOPE_PRIMARY_POSITIVE",
        case_rationale=(
            "Exact match against primary listed name of SUBJ-SYNTH-001. "
            "Customer DOB matches subject DOB."
        ),
    ),
    SanctionsEvalCase(
        case_id="CASE-SYNTH-002",
        customer_name="  kaz   drake  ",
        customer_dob=datetime.date(1992, 8, 4),
        planted_subject_key="SUBJ-SYNTH-004",
        expected_candidate_subject_keys=frozenset({"SUBJ-SYNTH-004"}),
        is_abstention=False,
        abstention_reason=None,
        case_type="IN_SCOPE_ALIAS_POSITIVE",
        case_rationale=(
            "Exact match against alias 'Kaz Drake' of SUBJ-SYNTH-004 after "
            "case-folding and collapsing whitespace runs."
        ),
    ),
    SanctionsEvalCase(
        case_id="CASE-SYNTH-003",
        customer_name="Elena Rostova",
        customer_dob=datetime.date(1985, 3, 20),
        planted_subject_key="SUBJ-SYNTH-002",
        expected_candidate_subject_keys=frozenset({"SUBJ-SYNTH-002", "SUBJ-SYNTH-003"}),
        is_abstention=False,
        abstention_reason=None,
        case_type="HOMONYM_POSITIVE_AND_FALSE_POSITIVE",
        case_rationale=(
            "Planted target is SUBJ-SYNTH-002 (DOB 1985-03-20). Homonym subject "
            "SUBJ-SYNTH-003 (DOB 1972-11-10) shares the exact primary name "
            "Elena Rostova and is also generated as a candidate (false positive "
            "in fidelity)."
        ),
    ),
    SanctionsEvalCase(
        case_id="CASE-SYNTH-004",
        customer_name="Zephyr Nightingale",
        customer_dob=datetime.date(1990, 1, 1),
        planted_subject_key=None,
        expected_candidate_subject_keys=frozenset(),
        is_abstention=False,
        abstention_reason=None,
        case_type="UNRELATED_NEGATIVE",
        case_rationale=(
            "Fictional benign name that has zero overlap with any watchlist "
            "listed name."
        ),
    ),
    SanctionsEvalCase(
        case_id="CASE-SYNTH-005",
        customer_name="Marcus Thorne",
        customer_dob=datetime.date(1980, 5, 15),
        planted_subject_key=None,
        expected_candidate_subject_keys=frozenset(),
        is_abstention=False,
        abstention_reason=None,
        case_type="DOB_ONLY_OVERLAP_NEGATIVE",
        case_rationale=(
            "Customer shares DOB 1980-05-15 with SUBJ-SYNTH-001, but customer name "
            "'Marcus Thorne' does not match any listed name. Demonstrates that DOB "
            "never gates or generates candidates when normalized names differ."
        ),
    ),
    SanctionsEvalCase(
        case_id="CASE-SYNTH-006",
        customer_name=None,
        customer_dob=datetime.date(1980, 5, 15),
        planted_subject_key="SUBJ-SYNTH-001",
        expected_candidate_subject_keys=frozenset(),
        is_abstention=True,
        abstention_reason=AbstentionReason.CUSTOMER_NAME_MISSING,
        case_type="PLANTED_POSITIVE_ABSTENTION_OUTSIDE_MATCHER_SCOPE",
        case_rationale=(
            "Planted target is SUBJ-SYNTH-001, but customer name is missing (None). "
            "Yields controlled abstention NOT_PERFORMED with 0 candidates. "
            "Ground truth remains POSITIVE, representing an out-of-scope false "
            "negative."
        ),
    ),
    SanctionsEvalCase(
        case_id="CASE-SYNTH-007",
        customer_name="\u00a0\u00a0",
        customer_dob=None,
        planted_subject_key=None,
        expected_candidate_subject_keys=frozenset(),
        is_abstention=True,
        abstention_reason=AbstentionReason.CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION,
        case_type="ABSTENTION_EMPTY_AFTER_NORMALIZATION_NEGATIVE",
        case_rationale=(
            "Customer name consists entirely of non-breaking spaces (U+00A0 U+00A0). "
            "Becomes empty string after NFKC and whitespace stripping, triggering "
            "controlled abstention NOT_PERFORMED."
        ),
    ),
    SanctionsEvalCase(
        case_id="CASE-SYNTH-008",
        customer_name="Aurelius Vancx",
        customer_dob=datetime.date(1980, 5, 15),
        planted_subject_key=None,
        expected_candidate_subject_keys=frozenset(),
        is_abstention=False,
        abstention_reason=None,
        case_type="EXCLUDED_TYPO_NEAR_MISS_NEGATIVE",
        case_rationale=(
            "Single-character typo edit ('Vancx' vs 'Vance'). F11 exact normalized "
            "equality rule excludes fuzzy/typo matches."
        ),
    ),
)


# =====================================================================
# 2. WATCHLIST SUBJECT SPECIFICATIONS (5 SUBJECTS)
# =====================================================================

EVAL_SUBJECT_KEYS: tuple[str, ...] = (
    "SUBJ-SYNTH-001",
    "SUBJ-SYNTH-002",
    "SUBJ-SYNTH-003",
    "SUBJ-SYNTH-004",
    "SUBJ-SYNTH-005",
)

EVAL_SUBJECT_LISTED_NAMES: dict[str, tuple[str, ...]] = {
    "SUBJ-SYNTH-001": ("Aurelius Vance", "A. Vance", "Aurel Vance"),
    "SUBJ-SYNTH-002": ("Elena Rostova", "Elena Rostoff"),
    "SUBJ-SYNTH-003": ("Elena Rostova", "E. Rostova"),
    "SUBJ-SYNTH-004": ("Kasimir Drake", "Kaz Drake"),
    "SUBJ-SYNTH-005": ("Tariq Mansoor",),
}


# =====================================================================
# 3. MANUALLY AUTHORED COMPLETE CANDIDATE REVIEW TABLE (40 PAIRS)
# =====================================================================

CANDIDATE_REVIEW_TABLE: tuple[CandidateReviewRecord, ...] = (
    # -----------------------------------------------------------------
    # CASE-SYNTH-001 (Customer: 'Aurelius Vance')
    # -----------------------------------------------------------------
    CandidateReviewRecord(
        case_id="CASE-SYNTH-001",
        subject_key="SUBJ-SYNTH-001",
        ground_truth=GroundTruth.POSITIVE,
        in_expected_candidates=True,
        customer_name_literal="Aurelius Vance",
        subject_listed_names=("Aurelius Vance", "A. Vance", "Aurel Vance"),
        matching_listed_name_literals=("Aurelius Vance",),
        normalization_reasoning=(
            "Customer: 'Aurelius Vance' -> NFKC: 'Aurelius Vance' -> casefold: "
            "'aurelius vance' "
            "-> collapse: 'aurelius vance'.\n"
            "Subject primary: 'Aurelius Vance' -> NFKC: 'Aurelius Vance' -> "
            "casefold: 'aurelius vance' "
            "-> collapse: 'aurelius vance'. Matches customer.\n"
            "Subject alias 1: 'A. Vance' -> 'a. vance' != 'aurelius vance'.\n"
            "Subject alias 2: 'Aurel Vance' -> 'aurel vance' != 'aurelius vance'."
        ),
        equality_decision=EqualityDecision.EQUAL,
        decision_rationale=(
            "Customer matches primary listed name 'Aurelius Vance'. Subject is "
            "the planted positive."
        ),
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-001",
        subject_key="SUBJ-SYNTH-002",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Aurelius Vance",
        subject_listed_names=("Elena Rostova", "Elena Rostoff"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'aurelius vance'.\n"
            "Subject names: 'Elena Rostova' -> 'elena rostova'; 'Elena Rostoff' "
            "-> 'elena rostoff'. "
            "Neither equals 'aurelius vance'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-001",
        subject_key="SUBJ-SYNTH-003",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Aurelius Vance",
        subject_listed_names=("Elena Rostova", "E. Rostova"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'aurelius vance'.\n"
            "Subject names: 'Elena Rostova' -> 'elena rostova'; 'E. Rostova' -> "
            "'e. rostova'. "
            "Neither equals 'aurelius vance'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-001",
        subject_key="SUBJ-SYNTH-004",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Aurelius Vance",
        subject_listed_names=("Kasimir Drake", "Kaz Drake"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'aurelius vance'.\n"
            "Subject names: 'Kasimir Drake' -> 'kasimir drake'; 'Kaz Drake' -> "
            "'kaz drake'. "
            "Neither equals 'aurelius vance'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-001",
        subject_key="SUBJ-SYNTH-005",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Aurelius Vance",
        subject_listed_names=("Tariq Mansoor",),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'aurelius vance'.\n"
            "Subject name: 'Tariq Mansoor' -> 'tariq mansoor'. Does not equal "
            "'aurelius vance'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    # -----------------------------------------------------------------
    # CASE-SYNTH-002 (Customer: '  kaz   drake  ')
    # -----------------------------------------------------------------
    CandidateReviewRecord(
        case_id="CASE-SYNTH-002",
        subject_key="SUBJ-SYNTH-001",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="  kaz   drake  ",
        subject_listed_names=("Aurelius Vance", "A. Vance", "Aurel Vance"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer: '  kaz   drake  ' (leading/trailing U+0020, triple "
            "internal U+0020) "
            "-> NFKC: '  kaz   drake  ' -> casefold: '  kaz   drake  ' -> "
            "collapse: 'kaz drake'.\n"
            "Subject names: 'aurelius vance', 'a. vance', 'aurel vance'. None "
            "equal 'kaz drake'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-002",
        subject_key="SUBJ-SYNTH-002",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="  kaz   drake  ",
        subject_listed_names=("Elena Rostova", "Elena Rostoff"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'kaz drake'.\n"
            "Subject names: 'elena rostova', 'elena rostoff'. Neither equals "
            "'kaz drake'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-002",
        subject_key="SUBJ-SYNTH-003",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="  kaz   drake  ",
        subject_listed_names=("Elena Rostova", "E. Rostova"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'kaz drake'.\n"
            "Subject names: 'elena rostova', 'e. rostova'. Neither equals 'kaz drake'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-002",
        subject_key="SUBJ-SYNTH-004",
        ground_truth=GroundTruth.POSITIVE,
        in_expected_candidates=True,
        customer_name_literal="  kaz   drake  ",
        subject_listed_names=("Kasimir Drake", "Kaz Drake"),
        matching_listed_name_literals=("Kaz Drake",),
        normalization_reasoning=(
            "Customer: '  kaz   drake  ' -> NFKC: '  kaz   drake  ' -> casefold: "
            "'  kaz   drake  ' "
            "-> collapse: 'kaz drake'.\n"
            "Subject primary: 'Kasimir Drake' -> 'kasimir drake' != 'kaz drake'.\n"
            "Subject alias: 'Kaz Drake' -> NFKC: 'Kaz Drake' -> casefold: 'kaz drake' "
            "-> collapse: 'kaz drake'. Matches customer normalized name exactly."
        ),
        equality_decision=EqualityDecision.EQUAL,
        decision_rationale=(
            "Customer matches alias 'Kaz Drake' after whitespace collapse and "
            "casefold. "
            "Subject is the planted positive."
        ),
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-002",
        subject_key="SUBJ-SYNTH-005",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="  kaz   drake  ",
        subject_listed_names=("Tariq Mansoor",),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'kaz drake'.\n"
            "Subject name: 'tariq mansoor' != 'kaz drake'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    # -----------------------------------------------------------------
    # CASE-SYNTH-003 (Customer: 'Elena Rostova')
    # -----------------------------------------------------------------
    CandidateReviewRecord(
        case_id="CASE-SYNTH-003",
        subject_key="SUBJ-SYNTH-001",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Elena Rostova",
        subject_listed_names=("Aurelius Vance", "A. Vance", "Aurel Vance"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer: 'Elena Rostova' -> NFKC: 'Elena Rostova' -> casefold: "
            "'elena rostova' "
            "-> collapse: 'elena rostova'.\n"
            "Subject names: 'aurelius vance', 'a. vance', 'aurel vance'. None "
            "equal 'elena rostova'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-003",
        subject_key="SUBJ-SYNTH-002",
        ground_truth=GroundTruth.POSITIVE,
        in_expected_candidates=True,
        customer_name_literal="Elena Rostova",
        subject_listed_names=("Elena Rostova", "Elena Rostoff"),
        matching_listed_name_literals=("Elena Rostova",),
        normalization_reasoning=(
            "Customer normalized: 'elena rostova'.\n"
            "Subject primary: 'Elena Rostova' -> NFKC: 'Elena Rostova' -> "
            "casefold: 'elena rostova' "
            "-> collapse: 'elena rostova'. Matches customer.\n"
            "Subject alias: 'Elena Rostoff' -> 'elena rostoff' != 'elena rostova'."
        ),
        equality_decision=EqualityDecision.EQUAL,
        decision_rationale=(
            "Customer matches primary name 'Elena Rostova'. This is the planted "
            "positive "
            "(DOB 1985-03-20)."
        ),
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-003",
        subject_key="SUBJ-SYNTH-003",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=True,
        customer_name_literal="Elena Rostova",
        subject_listed_names=("Elena Rostova", "E. Rostova"),
        matching_listed_name_literals=("Elena Rostova",),
        normalization_reasoning=(
            "Customer normalized: 'elena rostova'.\n"
            "Subject primary: 'Elena Rostova' -> NFKC: 'Elena Rostova' -> "
            "casefold: 'elena rostova' "
            "-> collapse: 'elena rostova'. Matches customer.\n"
            "Subject alias: 'E. Rostova' -> 'e. rostova' != 'elena rostova'."
        ),
        equality_decision=EqualityDecision.EQUAL,
        decision_rationale=(
            "Customer matches primary name 'Elena Rostova'. However, this "
            "subject is a homonym "
            "(born 1972-11-10) and is NOT the planted target (born 1985-03-20). "
            "Generates a candidate match, representing a false positive in "
            "fidelity accounting."
        ),
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-003",
        subject_key="SUBJ-SYNTH-004",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Elena Rostova",
        subject_listed_names=("Kasimir Drake", "Kaz Drake"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'elena rostova'.\n"
            "Subject names: 'kasimir drake', 'kaz drake'. Neither equals 'elena "
            "rostova'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-003",
        subject_key="SUBJ-SYNTH-005",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Elena Rostova",
        subject_listed_names=("Tariq Mansoor",),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'elena rostova'.\n"
            "Subject name: 'tariq mansoor' != 'elena rostova'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    # -----------------------------------------------------------------
    # CASE-SYNTH-004 (Customer: 'Zephyr Nightingale')
    # -----------------------------------------------------------------
    CandidateReviewRecord(
        case_id="CASE-SYNTH-004",
        subject_key="SUBJ-SYNTH-001",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Zephyr Nightingale",
        subject_listed_names=("Aurelius Vance", "A. Vance", "Aurel Vance"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer: 'Zephyr Nightingale' -> NFKC: 'Zephyr Nightingale' -> casefold: "
            "'zephyr nightingale' -> collapse: 'zephyr nightingale'.\n"
            "Subject names: 'aurelius vance', 'a. vance', 'aurel vance'. None "
            "equal 'zephyr nightingale'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Unrelated benign customer with no watchlist overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-004",
        subject_key="SUBJ-SYNTH-002",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Zephyr Nightingale",
        subject_listed_names=("Elena Rostova", "Elena Rostoff"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'zephyr nightingale'.\n"
            "Subject names: 'elena rostova', 'elena rostoff'. Neither equals "
            "'zephyr nightingale'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Unrelated benign customer with no watchlist overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-004",
        subject_key="SUBJ-SYNTH-003",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Zephyr Nightingale",
        subject_listed_names=("Elena Rostova", "E. Rostova"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'zephyr nightingale'.\n"
            "Subject names: 'elena rostova', 'e. rostova'. Neither equals "
            "'zephyr nightingale'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Unrelated benign customer with no watchlist overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-004",
        subject_key="SUBJ-SYNTH-004",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Zephyr Nightingale",
        subject_listed_names=("Kasimir Drake", "Kaz Drake"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'zephyr nightingale'.\n"
            "Subject names: 'kasimir drake', 'kaz drake'. Neither equals 'zephyr "
            "nightingale'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Unrelated benign customer with no watchlist overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-004",
        subject_key="SUBJ-SYNTH-005",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Zephyr Nightingale",
        subject_listed_names=("Tariq Mansoor",),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'zephyr nightingale'.\n"
            "Subject name: 'tariq mansoor' != 'zephyr nightingale'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Unrelated benign customer with no watchlist overlap.",
    ),
    # -----------------------------------------------------------------
    # CASE-SYNTH-005 (Customer: 'Marcus Thorne', DOB: 1980-05-15)
    # -----------------------------------------------------------------
    CandidateReviewRecord(
        case_id="CASE-SYNTH-005",
        subject_key="SUBJ-SYNTH-001",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Marcus Thorne",
        subject_listed_names=("Aurelius Vance", "A. Vance", "Aurel Vance"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer: 'Marcus Thorne' -> NFKC: 'Marcus Thorne' -> casefold: "
            "'marcus thorne' "
            "-> collapse: 'marcus thorne'.\n"
            "Customer DOB 1980-05-15 matches SUBJ-SYNTH-001 DOB 1980-05-15 exactly. "
            "However, subject names ('aurelius vance', 'a. vance', 'aurel "
            "vance') do not equal "
            "'marcus thorne'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale=(
            "DOB matches subject DOB (1980-05-15), but names differ completely. "
            "Under ADR-0008, DOB is an attribute and never generates candidates."
        ),
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-005",
        subject_key="SUBJ-SYNTH-002",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Marcus Thorne",
        subject_listed_names=("Elena Rostova", "Elena Rostoff"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'marcus thorne'.\n"
            "Subject names: 'elena rostova', 'elena rostoff'. Neither equals "
            "'marcus thorne'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-005",
        subject_key="SUBJ-SYNTH-003",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Marcus Thorne",
        subject_listed_names=("Elena Rostova", "E. Rostova"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'marcus thorne'.\n"
            "Subject names: 'elena rostova', 'e. rostova'. Neither equals "
            "'marcus thorne'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-005",
        subject_key="SUBJ-SYNTH-004",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Marcus Thorne",
        subject_listed_names=("Kasimir Drake", "Kaz Drake"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'marcus thorne'.\n"
            "Subject names: 'kasimir drake', 'kaz drake'. Neither equals 'marcus "
            "thorne'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-005",
        subject_key="SUBJ-SYNTH-005",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Marcus Thorne",
        subject_listed_names=("Tariq Mansoor",),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'marcus thorne'.\n"
            "Subject name: 'tariq mansoor' != 'marcus thorne'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    # -----------------------------------------------------------------
    # CASE-SYNTH-006 (Customer: None - Abstention with planted positive)
    # -----------------------------------------------------------------
    CandidateReviewRecord(
        case_id="CASE-SYNTH-006",
        subject_key="SUBJ-SYNTH-001",
        ground_truth=GroundTruth.POSITIVE,
        in_expected_candidates=False,
        customer_name_literal=None,
        subject_listed_names=("Aurelius Vance", "A. Vance", "Aurel Vance"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer name is missing (None). Rule ADR-0008 D8 mandates "
            "controlled abstention "
            "CUSTOMER_NAME_MISSING. No normalization performed. No candidates "
            "generated."
        ),
        equality_decision=EqualityDecision.NO_CANDIDATE_ABSTENTION,
        decision_rationale=(
            "Planted target is SUBJ-SYNTH-001, but customer name is missing. "
            "Controlled abstention generates zero candidates. "
            "Ground truth remains POSITIVE, resulting in a false negative."
        ),
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-006",
        subject_key="SUBJ-SYNTH-002",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal=None,
        subject_listed_names=("Elena Rostova", "Elena Rostoff"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer name is None. Controlled abstention CUSTOMER_NAME_MISSING. "
            "No normalization performed."
        ),
        equality_decision=EqualityDecision.NO_CANDIDATE_ABSTENTION,
        decision_rationale="Controlled abstention on missing customer name.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-006",
        subject_key="SUBJ-SYNTH-003",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal=None,
        subject_listed_names=("Elena Rostova", "E. Rostova"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer name is None. Controlled abstention CUSTOMER_NAME_MISSING. "
            "No normalization performed."
        ),
        equality_decision=EqualityDecision.NO_CANDIDATE_ABSTENTION,
        decision_rationale="Controlled abstention on missing customer name.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-006",
        subject_key="SUBJ-SYNTH-004",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal=None,
        subject_listed_names=("Kasimir Drake", "Kaz Drake"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer name is None. Controlled abstention CUSTOMER_NAME_MISSING. "
            "No normalization performed."
        ),
        equality_decision=EqualityDecision.NO_CANDIDATE_ABSTENTION,
        decision_rationale="Controlled abstention on missing customer name.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-006",
        subject_key="SUBJ-SYNTH-005",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal=None,
        subject_listed_names=("Tariq Mansoor",),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer name is None. Controlled abstention CUSTOMER_NAME_MISSING. "
            "No normalization performed."
        ),
        equality_decision=EqualityDecision.NO_CANDIDATE_ABSTENTION,
        decision_rationale="Controlled abstention on missing customer name.",
    ),
    # -----------------------------------------------------------------
    # CASE-SYNTH-007 (Customer: '\u00a0\u00a0' - Abstention empty-after-norm)
    # -----------------------------------------------------------------
    CandidateReviewRecord(
        case_id="CASE-SYNTH-007",
        subject_key="SUBJ-SYNTH-001",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="\u00a0\u00a0",
        subject_listed_names=("Aurelius Vance", "A. Vance", "Aurel Vance"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer literal consists of two NO-BREAK SPACE code points: U+00A0 "
            "U+00A0.\n"
            "NFKC replaces U+00A0 with standard ASCII space U+0020 U+0020 ('  ').\n"
            "Casefold: '  '.\n"
            "Whitespace collapse and trim yields empty string: ''.\n"
            "Triggers controlled abstention CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION."
        ),
        equality_decision=EqualityDecision.NO_CANDIDATE_ABSTENTION,
        decision_rationale=(
            "Controlled abstention on empty-after-normalization customer name."
        ),
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-007",
        subject_key="SUBJ-SYNTH-002",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="\u00a0\u00a0",
        subject_listed_names=("Elena Rostova", "Elena Rostoff"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer literal U+00A0 U+00A0 normalizes to empty string ''. "
            "Controlled abstention CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION."
        ),
        equality_decision=EqualityDecision.NO_CANDIDATE_ABSTENTION,
        decision_rationale=(
            "Controlled abstention on empty-after-normalization customer name."
        ),
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-007",
        subject_key="SUBJ-SYNTH-003",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="\u00a0\u00a0",
        subject_listed_names=("Elena Rostova", "E. Rostova"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer literal U+00A0 U+00A0 normalizes to empty string ''. "
            "Controlled abstention CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION."
        ),
        equality_decision=EqualityDecision.NO_CANDIDATE_ABSTENTION,
        decision_rationale=(
            "Controlled abstention on empty-after-normalization customer name."
        ),
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-007",
        subject_key="SUBJ-SYNTH-004",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="\u00a0\u00a0",
        subject_listed_names=("Kasimir Drake", "Kaz Drake"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer literal U+00A0 U+00A0 normalizes to empty string ''. "
            "Controlled abstention CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION."
        ),
        equality_decision=EqualityDecision.NO_CANDIDATE_ABSTENTION,
        decision_rationale=(
            "Controlled abstention on empty-after-normalization customer name."
        ),
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-007",
        subject_key="SUBJ-SYNTH-005",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="\u00a0\u00a0",
        subject_listed_names=("Tariq Mansoor",),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer literal U+00A0 U+00A0 normalizes to empty string ''. "
            "Controlled abstention CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION."
        ),
        equality_decision=EqualityDecision.NO_CANDIDATE_ABSTENTION,
        decision_rationale=(
            "Controlled abstention on empty-after-normalization customer name."
        ),
    ),
    # -----------------------------------------------------------------
    # CASE-SYNTH-008 (Customer: 'Aurelius Vancx' - Excluded typo)
    # -----------------------------------------------------------------
    CandidateReviewRecord(
        case_id="CASE-SYNTH-008",
        subject_key="SUBJ-SYNTH-001",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Aurelius Vancx",
        subject_listed_names=("Aurelius Vance", "A. Vance", "Aurel Vance"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer: 'Aurelius Vancx' -> NFKC: 'Aurelius Vancx' -> casefold: "
            "'aurelius vancx' "
            "-> collapse: 'aurelius vancx'.\n"
            "Subject primary: 'Aurelius Vance' -> 'aurelius vance'.\n"
            "Comparison: 'aurelius vancx' != 'aurelius vance' (terminal "
            "character differs: 'x' vs 'e'). "
            "Rule exact_norm_name_v1 excludes fuzzy matching."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale=(
            "Near-miss typo ('Vancx' vs 'Vance'). Excluded by exact normalized "
            "name rule."
        ),
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-008",
        subject_key="SUBJ-SYNTH-002",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Aurelius Vancx",
        subject_listed_names=("Elena Rostova", "Elena Rostoff"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'aurelius vancx'.\n"
            "Subject names: 'elena rostova', 'elena rostoff'. Neither equals "
            "'aurelius vancx'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-008",
        subject_key="SUBJ-SYNTH-003",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Aurelius Vancx",
        subject_listed_names=("Elena Rostova", "E. Rostova"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'aurelius vancx'.\n"
            "Subject names: 'elena rostova', 'e. rostova'. Neither equals "
            "'aurelius vancx'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-008",
        subject_key="SUBJ-SYNTH-004",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Aurelius Vancx",
        subject_listed_names=("Kasimir Drake", "Kaz Drake"),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'aurelius vancx'.\n"
            "Subject names: 'kasimir drake', 'kaz drake'. Neither equals "
            "'aurelius vancx'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
    CandidateReviewRecord(
        case_id="CASE-SYNTH-008",
        subject_key="SUBJ-SYNTH-005",
        ground_truth=GroundTruth.NEGATIVE,
        in_expected_candidates=False,
        customer_name_literal="Aurelius Vancx",
        subject_listed_names=("Tariq Mansoor",),
        matching_listed_name_literals=(),
        normalization_reasoning=(
            "Customer normalized: 'aurelius vancx'.\n"
            "Subject name: 'tariq mansoor' != 'aurelius vancx'."
        ),
        equality_decision=EqualityDecision.NOT_EQUAL,
        decision_rationale="Distinct individual with no name overlap.",
    ),
)


# =====================================================================
# 4. FROZEN EXPECTED AGGREGATE COUNTS
# =====================================================================


@dataclass(frozen=True)
class FrozenExpectedCounts:
    """Literal counts frozen after manual review of the complete table."""

    total_evaluation_cases: int = 8
    total_subjects: int = 5
    total_review_pairs: int = 40

    # Ground truth labels
    ground_truth_positives: int = 4
    ground_truth_negatives: int = 36

    # Expected candidate decisions
    expected_candidates: int = 4
    expected_non_candidates: int = 36

    # Equality decision breakdown
    decision_equal: int = 4
    decision_not_equal: int = 26
    decision_no_candidate_abstention: int = 10

    # Candidate-generation fidelity classification
    fidelity_true_positives: int = 3
    fidelity_false_positives: int = 1
    fidelity_false_negatives: int = 1
    fidelity_true_negatives: int = 35


FROZEN_EXPECTED_COUNTS: FrozenExpectedCounts = FrozenExpectedCounts()


def get_sanctions_eval_cases() -> tuple[SanctionsEvalCase, ...]:
    """Return immutable tuple of synthetic evaluation cases."""
    return SANCTIONS_EVAL_CASES


def get_candidate_review_table() -> tuple[CandidateReviewRecord, ...]:
    """Return immutable tuple of all 40 manually reviewed records."""
    return CANDIDATE_REVIEW_TABLE
