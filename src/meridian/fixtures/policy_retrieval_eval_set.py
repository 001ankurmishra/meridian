# ruff: noqa: E501
"""
RAG Evaluation Set Fixture — Policy Retrieval Evaluation v1.

Status: PROPOSED_NOT_FROZEN.
This module defines a proposed evaluation set, rubric, and integrity validator
for policy retrieval evaluation against POLICY_CORPUS_V1.
Labels and protocol are pending human maintainer review and approval.

PROHIBITED VOCABULARY SCAN:
This module contains pure data and validation logic.
Strict neutrality: prohibited domain terminology is excluded.
"""

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

PROTOCOL_STATUS = "PROPOSED_NOT_FROZEN"
EVAL_SET_VERSION = "policy_retrieval_eval_v1"
SEED = "policy_retrieval_eval_v1"
CORPUS_ID = "POLICY_CORPUS_V1"
MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_SNAPSHOT = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
RETRIEVAL_K = 60
RETRIEVAL_TOP_K = 5
LABELER_PROVENANCE = "AI-assisted authoring (Antigravity); maintainer review PENDING"

COHORT_STATUS: Dict[str, str] = {
    "C1": "PRIMARY",
    "C2": "PROVISIONAL",
    "C3": "ROBUSTNESS",
    "C4": "EXPLORATORY",
}


class PolicyApplicability(str, Enum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE_OUT_OF_DOMAIN = "NOT_APPLICABLE_OUT_OF_DOMAIN"
    UNDETERMINED = "UNDETERMINED"


class CorpusCoverage(str, Enum):
    COVERED = "COVERED"
    PARTIALLY_COVERED = "PARTIALLY_COVERED"
    NOT_COVERED = "NOT_COVERED"
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN"


class AbstentionGroundTruth(str, Enum):
    SHOULD_RETRIEVE = "SHOULD_RETRIEVE"
    SHOULD_ABSTAIN = "SHOULD_ABSTAIN"
    NOT_ASSESSED = "NOT_ASSESSED"


@dataclass(frozen=True)
class ChunkRef:
    title: str
    version: str
    chunk_index: int
    text_sha256: str


@dataclass(frozen=True)
class Judgment:
    chunk_ref: ChunkRef
    grade: int
    note: Optional[str] = None
    borderline: bool = False


@dataclass(frozen=True)
class EvalQuery:
    query_id: str
    cohort: str
    query_text: str
    split: str
    policy_applicability: PolicyApplicability
    corpus_coverage: CorpusCoverage
    abstention_ground_truth: AbstentionGroundTruth
    judgments: Tuple[Judgment, ...]
    rationale: str


@dataclass(frozen=True)
class EvalSet:
    version: str
    seed: str
    corpus_id: str
    model_name: str
    model_snapshot: str
    retrieval_k: int
    retrieval_top_k: int
    labeler_provenance: str
    cohort_status: Dict[str, str]
    protocol_status: str
    chunk_refs: Tuple[ChunkRef, ...]
    queries: Tuple[EvalQuery, ...]


# Literals representing the 10 chunks from POLICY_CORPUS_V1.
# The fixture module does not import the corpus directly to avoid runtime dependencies.
CORPUS_CHUNK_REFS: Tuple[ChunkRef, ...] = (
    ChunkRef(
        title="Synthetic Internal Policy — Large / unusual transaction review procedure",
        version="v1",
        chunk_index=0,
        text_sha256="4edf7bcff4c595a7ce21484092663cae6d04cb74c57f70adfed2a39ca770a0e2",
    ),
    ChunkRef(
        title="Synthetic Internal Policy — Large / unusual transaction review procedure",
        version="v1",
        chunk_index=1,
        text_sha256="14be7f1bfe173dad266c7b6a09bcf6660d551de834f127ef26d0066173d14ad2",
    ),
    ChunkRef(
        title="Synthetic Internal Policy — New beneficiary review procedure",
        version="v1",
        chunk_index=0,
        text_sha256="2131201ecf063290bbcf18962bba53c9088bdf3e6c9d9bb9aa342d7afa5a9e38",
    ),
    ChunkRef(
        title="Synthetic Internal Policy — New beneficiary review procedure",
        version="v1",
        chunk_index=1,
        text_sha256="659ae529a06bfe30b924c3d2835783e7cecc346b2996e1f392de71ab39bd0060",
    ),
    ChunkRef(
        title="Synthetic Internal Policy — New beneficiary review procedure",
        version="v1",
        chunk_index=2,
        text_sha256="438ca83367f6ebc8739dfb6d4412b21d1da3b6fcce708b6c063ca6db2bdf53e0",
    ),
    ChunkRef(
        title="Synthetic Internal Policy — Rapid movement of funds review procedure",
        version="v1",
        chunk_index=0,
        text_sha256="d37010c738fd03fc7f3f4eb0e42059ab0e7cf6a4347ca33d5d5af00730588c8f",
    ),
    ChunkRef(
        title="Synthetic Internal Policy — Rapid movement of funds review procedure",
        version="v1",
        chunk_index=1,
        text_sha256="0431d7199be75c58f0c628ee5ef96d0e61d386a71ce5c106eb33b3c203d0a2b2",
    ),
    ChunkRef(
        title="Synthetic Internal Policy — Rapid movement of funds review procedure",
        version="v1",
        chunk_index=2,
        text_sha256="b385f79abee84f1890a81c15ac5653b0e7c23e91cb57a6e2834e0e08c0cc9818",
    ),
    ChunkRef(
        title="Synthetic Internal Policy — Investigation evidence and documentation standards",
        version="v1",
        chunk_index=0,
        text_sha256="949fca7a11aa1e5740f7d2890545f2a348ce3501e8d8c89e37f0e25aea404903",
    ),
    ChunkRef(
        title="Synthetic Internal Policy — Investigation evidence and documentation standards",
        version="v1",
        chunk_index=1,
        text_sha256="63e54a988c4ddf477b6a7f572b790f8a3a0feb44659d26301e9bba61fb545533",
    ),
)


def assign_split(seed: str, query_id: str) -> str:
    """
    Deterministic split assignment for evaluation queries.
    Parity of first byte of SHA-256(seed:query_id): even=DEV, odd=HELDOUT.
    """
    digest = hashlib.sha256(f"{seed}:{query_id}".encode("utf-8")).digest()
    return "DEV" if (digest[0] % 2 == 0) else "HELDOUT"


def validate_eval_set(eval_set: EvalSet) -> None:
    """
    Validates evaluation set invariants and label model rules V1-V8.
    Raises ValueError on any violation.
    Note: In accordance with the protocol, there is NO rule that derives
    applicability or abstention from chunk grades.
    """
    if eval_set.protocol_status != PROTOCOL_STATUS:
        raise ValueError(f"protocol_status must be {PROTOCOL_STATUS}, got {eval_set.protocol_status}")

    if len(eval_set.chunk_refs) != 10:
        raise ValueError(f"Expected exactly 10 chunk_refs, got {len(eval_set.chunk_refs)}")

    chunk_refs_tuple = tuple(eval_set.chunk_refs)
    seen_queries = set()

    c3_dev_count = 0
    c3_heldout_count = 0
    c4_dev_count = 0
    c4_heldout_count = 0

    for q in eval_set.queries:
        if q.query_id in seen_queries:
            raise ValueError(f"Duplicate query_id: {q.query_id}")
        seen_queries.add(q.query_id)

        if q.cohort not in COHORT_STATUS:
            raise ValueError(f"Invalid cohort {q.cohort} for query {q.query_id}")

        # Check split assignments
        if q.cohort in {"C1", "C2"}:
            if q.split != "NONE":
                raise ValueError(f"Cohort {q.cohort} queries must have split 'NONE', got {q.split} for {q.query_id}")
        elif q.cohort in {"C3", "C4"}:
            expected_split = assign_split(eval_set.seed, q.query_id)
            if q.split != expected_split:
                raise ValueError(
                    f"Cohort {q.cohort} query {q.query_id} split {q.split} does not match expected {expected_split}"
                )
            if q.cohort == "C3":
                if q.split == "DEV":
                    c3_dev_count += 1
                else:
                    c3_heldout_count += 1
            elif q.cohort == "C4":
                if q.split == "DEV":
                    c4_dev_count += 1
                else:
                    c4_heldout_count += 1

        # Check judgments completeness
        if len(q.judgments) != len(chunk_refs_tuple):
            raise ValueError(
                f"Query {q.query_id} has {len(q.judgments)} judgments, expected {len(chunk_refs_tuple)}"
            )

        judged_chunks = tuple(j.chunk_ref for j in q.judgments)
        if judged_chunks != chunk_refs_tuple:
            raise ValueError(f"Query {q.query_id} judgments do not match canonical chunk_refs order and identities")

        grades = []
        for j in q.judgments:
            if j.grade not in {0, 1, 2}:
                raise ValueError(f"Invalid grade {j.grade} in query {q.query_id}")
            grades.append(j.grade)

            if j.grade == 1:
                if not j.note or not j.note.strip():
                    raise ValueError(f"Grade 1 requires non-empty note in query {q.query_id}")

            if j.borderline:
                if not j.note or not j.note.strip():
                    raise ValueError(f"Borderline judgment requires non-empty note in query {q.query_id}")
                if len(j.note) > 200:
                    raise ValueError(
                        f"Borderline note exceeds 200 chars ({len(j.note)} chars) in query {q.query_id}"
                    )

        has_grade_2 = any(g == 2 for g in grades)
        has_grade_1 = any(g == 1 for g in grades)
        all_grades_zero = all(g == 0 for g in grades)

        # V1: applicability=NOT_APPLICABLE_OUT_OF_DOMAIN => coverage=OUT_OF_DOMAIN, all grades 0, cohort=C3.
        if q.policy_applicability == PolicyApplicability.NOT_APPLICABLE_OUT_OF_DOMAIN:
            if q.corpus_coverage != CorpusCoverage.OUT_OF_DOMAIN:
                raise ValueError(
                    f"V1 violation in {q.query_id}: NOT_APPLICABLE_OUT_OF_DOMAIN requires coverage OUT_OF_DOMAIN"
                )
            if not all_grades_zero:
                raise ValueError(
                    f"V1 violation in {q.query_id}: NOT_APPLICABLE_OUT_OF_DOMAIN requires all grades 0"
                )
            if q.cohort != "C3":
                raise ValueError(
                    f"V1 violation in {q.query_id}: NOT_APPLICABLE_OUT_OF_DOMAIN requires cohort C3"
                )

        # V2: coverage=OUT_OF_DOMAIN => applicability=NOT_APPLICABLE_OUT_OF_DOMAIN.
        if q.corpus_coverage == CorpusCoverage.OUT_OF_DOMAIN:
            if q.policy_applicability != PolicyApplicability.NOT_APPLICABLE_OUT_OF_DOMAIN:
                raise ValueError(
                    f"V2 violation in {q.query_id}: coverage OUT_OF_DOMAIN requires applicability NOT_APPLICABLE_OUT_OF_DOMAIN"
                )

        # V3: coverage=COVERED iff some grade==2; PARTIALLY_COVERED iff no grade 2 and some grade 1;
        #     NOT_COVERED => all grades 0 and applicability in {APPLICABLE, UNDETERMINED}.
        if q.corpus_coverage == CorpusCoverage.COVERED:
            if not has_grade_2:
                raise ValueError(f"V3 violation in {q.query_id}: coverage COVERED requires at least one grade 2")
        elif q.corpus_coverage == CorpusCoverage.PARTIALLY_COVERED:
            if has_grade_2 or not has_grade_1:
                raise ValueError(
                    f"V3 violation in {q.query_id}: coverage PARTIALLY_COVERED requires no grade 2 and at least one grade 1"
                )
        elif q.corpus_coverage == CorpusCoverage.NOT_COVERED:
            if not all_grades_zero:
                raise ValueError(f"V3 violation in {q.query_id}: coverage NOT_COVERED requires all grades 0")
            if q.policy_applicability not in {PolicyApplicability.APPLICABLE, PolicyApplicability.UNDETERMINED}:
                raise ValueError(
                    f"V3 violation in {q.query_id}: coverage NOT_COVERED requires applicability APPLICABLE or UNDETERMINED"
                )
        elif q.corpus_coverage == CorpusCoverage.OUT_OF_DOMAIN:
            if not all_grades_zero:
                raise ValueError(f"V3 violation in {q.query_id}: coverage OUT_OF_DOMAIN requires all grades 0")

        # Reverse check for V3 iff conditions
        if has_grade_2 and q.corpus_coverage != CorpusCoverage.COVERED:
            raise ValueError(
                f"V3 violation in {q.query_id}: presence of grade 2 requires coverage COVERED, got {q.corpus_coverage}"
            )
        if (not has_grade_2) and has_grade_1 and q.corpus_coverage != CorpusCoverage.PARTIALLY_COVERED:
            raise ValueError(
                f"V3 violation in {q.query_id}: grade 1 with no grade 2 requires coverage PARTIALLY_COVERED, got {q.corpus_coverage}"
            )

        # V4: SHOULD_ABSTAIN => applicability=NOT_APPLICABLE_OUT_OF_DOMAIN, coverage=OUT_OF_DOMAIN, cohort=C3.
        # A missing grade-2 chunk or coverage NOT_COVERED NEVER implies SHOULD_ABSTAIN or non-applicability.
        if q.abstention_ground_truth == AbstentionGroundTruth.SHOULD_ABSTAIN:
            if q.policy_applicability != PolicyApplicability.NOT_APPLICABLE_OUT_OF_DOMAIN:
                raise ValueError(
                    f"V4 violation in {q.query_id}: SHOULD_ABSTAIN requires applicability NOT_APPLICABLE_OUT_OF_DOMAIN"
                )
            if q.corpus_coverage != CorpusCoverage.OUT_OF_DOMAIN:
                raise ValueError(
                    f"V4 violation in {q.query_id}: SHOULD_ABSTAIN requires coverage OUT_OF_DOMAIN"
                )
            if q.cohort != "C3":
                raise ValueError(
                    f"V4 violation in {q.query_id}: SHOULD_ABSTAIN requires cohort C3"
                )

        # V5: SHOULD_RETRIEVE => applicability=APPLICABLE, coverage=COVERED, cohort in {C1, C4}.
        if q.abstention_ground_truth == AbstentionGroundTruth.SHOULD_RETRIEVE:
            if q.policy_applicability != PolicyApplicability.APPLICABLE:
                raise ValueError(
                    f"V5 violation in {q.query_id}: SHOULD_RETRIEVE requires applicability APPLICABLE"
                )
            if q.corpus_coverage != CorpusCoverage.COVERED:
                raise ValueError(
                    f"V5 violation in {q.query_id}: SHOULD_RETRIEVE requires coverage COVERED"
                )
            if q.cohort not in {"C1", "C4"}:
                raise ValueError(
                    f"V5 violation in {q.query_id}: SHOULD_RETRIEVE requires cohort in {{C1, C4}}"
                )

        # V6: applicability=APPLICABLE with coverage in {NOT_COVERED, PARTIALLY_COVERED} => abstention=NOT_ASSESSED.
        if q.policy_applicability == PolicyApplicability.APPLICABLE and q.corpus_coverage in {
            CorpusCoverage.NOT_COVERED,
            CorpusCoverage.PARTIALLY_COVERED,
        }:
            if q.abstention_ground_truth != AbstentionGroundTruth.NOT_ASSESSED:
                raise ValueError(
                    f"V6 violation in {q.query_id}: APPLICABLE with coverage {q.corpus_coverage} requires abstention NOT_ASSESSED"
                )

        # V7: applicability=UNDETERMINED => NOT_ASSESSED; every C2 query => NOT_ASSESSED.
        if q.policy_applicability == PolicyApplicability.UNDETERMINED:
            if q.abstention_ground_truth != AbstentionGroundTruth.NOT_ASSESSED:
                raise ValueError(
                    f"V7 violation in {q.query_id}: applicability UNDETERMINED requires abstention NOT_ASSESSED"
                )
        if q.cohort == "C2":
            if q.abstention_ground_truth != AbstentionGroundTruth.NOT_ASSESSED:
                raise ValueError(
                    f"V7 violation in {q.query_id}: cohort C2 query requires abstention NOT_ASSESSED"
                )

        # V8: every C3 query with NOT_APPLICABLE_OUT_OF_DOMAIN => SHOULD_ABSTAIN.
        if q.cohort == "C3" and q.policy_applicability == PolicyApplicability.NOT_APPLICABLE_OUT_OF_DOMAIN:
            if q.abstention_ground_truth != AbstentionGroundTruth.SHOULD_ABSTAIN:
                raise ValueError(
                    f"V8 violation in {q.query_id}: C3 query with NOT_APPLICABLE_OUT_OF_DOMAIN requires SHOULD_ABSTAIN"
                )

    # Check cohort counts
    if not (38 <= len(eval_set.queries) <= 50):
        raise ValueError(f"Total queries must be between 38 and 50, got {len(eval_set.queries)}")

    if c3_dev_count < 4 or c3_heldout_count < 4:
        raise ValueError(f"C3 requires >=4 DEV and >=4 HELDOUT, got DEV={c3_dev_count}, HELDOUT={c3_heldout_count}")

    if c4_dev_count < 4 or c4_heldout_count < 4:
        raise ValueError(f"C4 requires >=4 DEV and >=4 HELDOUT, got DEV={c4_dev_count}, HELDOUT={c4_heldout_count}")


def canonical_json(eval_set: EvalSet) -> str:
    """
    Serializes EvalSet to canonical JSON string:
    sorted keys, fixed separators (',', ':'), ensure_ascii=False, no timestamps.
    """
    def _to_json_ready(obj: Any) -> Any:
        if isinstance(obj, Enum):
            return obj.value
        elif isinstance(obj, (tuple, list)):
            return [_to_json_ready(x) for x in obj]
        elif isinstance(obj, dict):
            return {k: _to_json_ready(v) for k, v in obj.items()}
        elif hasattr(obj, "__dataclass_fields__"):
            return {k: _to_json_ready(getattr(obj, k)) for k in obj.__dataclass_fields__}
        return obj

    raw_dict = _to_json_ready(eval_set)
    return json.dumps(raw_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_sha256(eval_set: EvalSet) -> str:
    """Computes SHA-256 hex digest of canonical JSON serialization."""
    return hashlib.sha256(canonical_json(eval_set).encode("utf-8")).hexdigest()


def _make_judgments(
    grades: List[int],
    notes: Optional[Dict[int, str]] = None,
    borderlines: Optional[Dict[int, bool]] = None,
) -> Tuple[Judgment, ...]:
    notes = notes or {}
    borderlines = borderlines or {}
    judgments = []
    for idx, ref in enumerate(CORPUS_CHUNK_REFS):
        grade = grades[idx]
        note = notes.get(idx)
        borderline = borderlines.get(idx, False)
        judgments.append(
            Judgment(
                chunk_ref=ref,
                grade=grade,
                note=note,
                borderline=borderline,
            )
        )
    return tuple(judgments)


def build_eval_set() -> EvalSet:
    """Constructs and returns the proposed policy retrieval evaluation set."""
    queries: List[EvalQuery] = []

    # =========================================================================
    # COHORT C1: Production query path (3 queries)
    # alert_type passed verbatim. Descriptive only. Split is NONE.
    # =========================================================================
    queries.append(
        EvalQuery(
            query_id="c1_01",
            cohort="C1",
            query_text="large_transaction",
            split="NONE",
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [2, 2, 0, 0, 0, 0, 0, 0, 0, 0],
            ),
            rationale="Production query path for large transaction alert type. Procedure is directly and specifically governed by policy chunks 0 and 1.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c1_02",
            cohort="C1",
            query_text="new_beneficiary",
            split="NONE",
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [0, 0, 2, 2, 2, 0, 0, 0, 0, 0],
            ),
            rationale="Production query path for new beneficiary alert type. Procedure is directly and specifically governed by policy chunks 2, 3, and 4.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c1_03",
            cohort="C1",
            query_text="rapid_movement",
            split="NONE",
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [0, 0, 0, 0, 0, 2, 2, 2, 0, 0],
            ),
            rationale="Production query path for rapid movement alert type. Procedure is directly and specifically governed by policy chunks 5, 6, and 7.",
        )
    )

    # =========================================================================
    # COHORT C2: Legacy fixture generator strings (5 queries, PROVISIONAL)
    # Does not claim legacy workflow is supported. Split is NONE.
    # Abstention is NOT_ASSESSED for all C2 queries.
    # =========================================================================
    queries.append(
        EvalQuery(
            query_id="c2_01",
            cohort="C2",
            query_text="AML_GENERAL",
            split="NONE",
            policy_applicability=PolicyApplicability.UNDETERMINED,
            corpus_coverage=CorpusCoverage.NOT_COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            rationale="Legacy fixture string with no defined investigative procedure subject; generic prefix whose meaning is not established by the query text alone.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c2_02",
            cohort="C2",
            query_text="AML_STRUCTURING",
            split="NONE",
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.NOT_COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            rationale="Structuring is a recognized financial investigation subject, but the synthetic corpus contains no procedure specific to sub-threshold structuring patterns; general documentation chunks do not provide substantive structuring guidance.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c2_03",
            cohort="C2",
            query_text="AML_RAPID_MOVEMENT",
            split="NONE",
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments(
                [0, 0, 0, 0, 0, 2, 2, 2, 0, 0],
            ),
            rationale="Literal subject matches rapid movement procedure in chunks 5, 6, and 7, but legacy cohort status is provisional and abstention remains not assessed.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c2_04",
            cohort="C2",
            query_text="AML_CIRCULAR",
            split="NONE",
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.PARTIALLY_COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments(
                [0, 0, 0, 0, 0, 1, 1, 0, 0, 0],
                notes={
                    5: "Guidance on calculating elapsed time between deposits and transfers to assess pass-through layering flows.",
                    6: "Guidance on retaining screenshots of linked accounts when funds are shuttled between related entities.",
                },
                borderlines={5: True, 6: True},
            ),
            rationale="Circular fund flow is an applicable subject; corpus provides partial supporting guidance on conduit accounts and shuttling funds between linked entities in chunks 5 and 6 without a dedicated circular transaction procedure.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c2_05",
            cohort="C2",
            query_text="AML_MULE",
            split="NONE",
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.PARTIALLY_COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments(
                [0, 0, 0, 0, 0, 1, 1, 0, 0, 0],
                notes={
                    5: "Guidance on assessing why an account is used merely as a pass-through conduit without economic rationale.",
                    6: "Guidance on identifying severe volume mismatches where retail/student accounts exhibit pass-through flows.",
                },
                borderlines={5: True, 6: True},
            ),
            rationale="Mule account investigation is an applicable subject; corpus provides partial supporting guidance on conduit accounts and pass-through volume mismatches in chunks 5 and 6.",
        )
    )

    # =========================================================================
    # COHORT C3: Robustness probes (11 queries: 1 empty string + 10 out-of-domain)
    # Not production-reachable.
    # Empty string: UNDETERMINED, NOT_COVERED, NOT_ASSESSED.
    # Out-of-domain: NOT_APPLICABLE_OUT_OF_DOMAIN, OUT_OF_DOMAIN, SHOULD_ABSTAIN.
    # =========================================================================
    queries.append(
        EvalQuery(
            query_id="c3_01",
            cohort="C3",
            query_text="",
            split=assign_split(SEED, "c3_01"),
            policy_applicability=PolicyApplicability.UNDETERMINED,
            corpus_coverage=CorpusCoverage.NOT_COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            rationale="Alert intake rejects empty/whitespace alert_type so this query serves as a behavior probe only.",
        )
    )

    out_of_domain_probes = [
        ("c3_02", "zzzz qqqq", "Synthesized gibberish string with no semantic meaning in financial investigations or policy procedures."),
        ("c3_03", "weather forecast for tomorrow", "Meteorological inquiry entirely outside the domain of financial investigation procedures."),
        ("c3_04", "chocolate cake recipe", "Culinary preparation instructions entirely outside the domain of financial investigation procedures."),
        ("c3_05", "how to change a flat tire", "Automotive maintenance instructions entirely outside the domain of financial investigation procedures."),
        ("c3_06", "premier league football scores", "Sports entertainment results entirely outside the domain of financial investigation procedures."),
        ("c3_07", "quantum computing superposition principles", "Physics and computing theory entirely outside the domain of financial investigation procedures."),
        ("c3_08", "french vanilla ice cream ingredients", "Dessert culinary formula entirely outside the domain of financial investigation procedures."),
        ("c3_09", "history of the renaissance in florence", "Historical academic subject entirely outside the domain of financial investigation procedures."),
        ("c3_10", "mars rover perseverance latest images", "Space exploration telemetry entirely outside the domain of financial investigation procedures."),
        ("c3_11", "best hiking trails in the pacific northwest", "Outdoor recreation navigation entirely outside the domain of financial investigation procedures."),
    ]

    for qid, text, rationale in out_of_domain_probes:
        queries.append(
            EvalQuery(
                query_id=qid,
                cohort="C3",
                query_text=text,
                split=assign_split(SEED, qid),
                policy_applicability=PolicyApplicability.NOT_APPLICABLE_OUT_OF_DOMAIN,
                corpus_coverage=CorpusCoverage.OUT_OF_DOMAIN,
                abstention_ground_truth=AbstentionGroundTruth.SHOULD_ABSTAIN,
                judgments=_make_judgments([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
                rationale=rationale,
            )
        )

    # =========================================================================
    # COHORT C4: Authored paraphrases and in-domain coverage gaps (20 queries)
    # 12 topic paraphrases (3 per each of the 4 corpus topics)
    # 8 in-domain coverage-gap queries (AML investigation subjects with no matching procedure)
    # =========================================================================
    # Topic 1: Large/unusual transaction review
    queries.append(
        EvalQuery(
            query_id="c4_001",
            cohort="C4",
            query_text="protocol for evaluating transactions exceeding expected customer volume",
            split=assign_split(SEED, "c4_001"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [2, 2, 0, 0, 0, 0, 0, 0, 0, 0],
            ),
            rationale="Paraphrase of large transaction review focusing on expected volume deviation and baseline comparison.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_002",
            cohort="C4",
            query_text="verifying customer source of funds against historical salary and profile",
            split=assign_split(SEED, "c4_002"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [2, 2, 0, 0, 0, 0, 0, 0, 0, 0],
            ),
            rationale="Paraphrase of large transaction procedure focusing on KYC source of funds and salary discrepancy checks.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_003",
            cohort="C4",
            query_text="investigating sudden high-value wire transfers from unknown counterparties",
            split=assign_split(SEED, "c4_003"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [2, 2, 0, 0, 0, 0, 0, 0, 0, 0],
            ),
            rationale="Paraphrase of large transaction procedure focusing on wire transfers from third-party counterparties.",
        )
    )

    # Topic 2: New beneficiary review
    queries.append(
        EvalQuery(
            query_id="c4_004",
            cohort="C4",
            query_text="steps to verify newly added payment recipient before executing transfer",
            split=assign_split(SEED, "c4_004"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [0, 0, 2, 2, 2, 0, 0, 0, 0, 0],
            ),
            rationale="Paraphrase of new beneficiary procedure focusing on recipient verification and payment scrutiny.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_005",
            cohort="C4",
            query_text="evaluating risk when account transfers funds immediately after adding payee",
            split=assign_split(SEED, "c4_005"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [0, 0, 2, 2, 2, 0, 0, 0, 0, 0],
            ),
            rationale="Paraphrase of new beneficiary procedure focusing on payment timing and transaction velocity following payee addition.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_006",
            cohort="C4",
            query_text="reviewing overseas corporate beneficiary added by retail account holder",
            split=assign_split(SEED, "c4_006"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [0, 0, 2, 2, 2, 0, 0, 0, 0, 0],
            ),
            rationale="Paraphrase of new beneficiary procedure focusing on overseas corporate payee addition by retail customer.",
        )
    )

    # Topic 3: Rapid movement of funds
    queries.append(
        EvalQuery(
            query_id="c4_007",
            cohort="C4",
            query_text="analyzing same-day pass-through transfers between accounts",
            split=assign_split(SEED, "c4_007"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [0, 0, 0, 0, 0, 2, 2, 2, 0, 0],
            ),
            rationale="Paraphrase of rapid movement procedure focusing on same-day pass-through transactions and conduit flow.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_008",
            cohort="C4",
            query_text="determining economic rationale for rapid withdrawal following deposit",
            split=assign_split(SEED, "c4_008"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [0, 0, 0, 0, 0, 2, 2, 2, 0, 0],
            ),
            rationale="Paraphrase of rapid movement procedure focusing on economic rationale assessment for swift deposit and withdrawal.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_009",
            cohort="C4",
            query_text="calculating elapsed duration between incoming credits and outbound wires",
            split=assign_split(SEED, "c4_009"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [0, 0, 0, 0, 0, 2, 2, 2, 0, 0],
            ),
            rationale="Paraphrase of rapid movement procedure focusing on calculating elapsed time and transaction sequencing.",
        )
    )

    # Topic 4: Evidence and documentation standards
    queries.append(
        EvalQuery(
            query_id="c4_010",
            cohort="C4",
            query_text="requirements for citing empirical records in investigation case notes",
            split=assign_split(SEED, "c4_010"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [0, 0, 0, 0, 0, 0, 0, 0, 2, 2],
            ),
            rationale="Paraphrase of evidence documentation policy focusing on empirical record citation in case dispositions.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_011",
            cohort="C4",
            query_text="prohibition on automated tooling freezing accounts without human authorization",
            split=assign_split(SEED, "c4_011"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [0, 0, 0, 0, 0, 0, 0, 0, 2, 2],
            ),
            rationale="Paraphrase of evidence documentation policy focusing on automated tooling boundaries and human decision authority.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_012",
            cohort="C4",
            query_text="standards for establishing audit trail and chronological narrative in reviews",
            split=assign_split(SEED, "c4_012"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.COVERED,
            abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
            judgments=_make_judgments(
                [0, 0, 0, 0, 0, 0, 0, 0, 2, 2],
            ),
            rationale="Paraphrase of evidence documentation policy focusing on auditability, chronology, and fact-interpretation distinction.",
        )
    )

    # In-domain coverage gaps (8 queries)
    queries.append(
        EvalQuery(
            query_id="c4_013",
            cohort="C4",
            query_text="sanctions list screening protocol for newly onboarded customers",
            split=assign_split(SEED, "c4_013"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.NOT_COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            rationale="In-domain coverage-gap query: customer watchlist screening is an applicable investigation subject entirely absent from the synthetic corpus.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_014",
            cohort="C4",
            query_text="identifying politically exposed persons during periodic account reviews",
            split=assign_split(SEED, "c4_014"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.NOT_COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            rationale="In-domain coverage-gap query: politically exposed persons review is an applicable investigation subject entirely absent from the synthetic corpus.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_015",
            cohort="C4",
            query_text="investigating potential trade-based over-invoicing and fraudulent shipping manifests",
            split=assign_split(SEED, "c4_015"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.NOT_COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            rationale="In-domain coverage-gap query: trade finance over-invoicing is an applicable subject entirely absent from the synthetic corpus.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_016",
            cohort="C4",
            query_text="procedures for handling correspondent banking nested account flows",
            split=assign_split(SEED, "c4_016"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.NOT_COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            rationale="In-domain coverage-gap query: correspondent banking nested accounts is an applicable subject entirely absent from the synthetic corpus.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_017",
            cohort="C4",
            query_text="customer due diligence requirements for bearer share entities",
            split=assign_split(SEED, "c4_017"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.NOT_COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            rationale="In-domain coverage-gap query: bearer share entity due diligence is an applicable subject entirely absent from the synthetic corpus.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_018",
            cohort="C4",
            query_text="verifying ultimate beneficial ownership of complex trust structures",
            split=assign_split(SEED, "c4_018"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.NOT_COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            rationale="In-domain coverage-gap query: trust beneficial ownership verification is an applicable subject entirely absent from the synthetic corpus.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_019",
            cohort="C4",
            query_text="handling law enforcement subpoena requests for customer financial records",
            split=assign_split(SEED, "c4_019"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.NOT_COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            rationale="In-domain coverage-gap query: legal subpoena document handling is an applicable subject with no procedure in the synthetic corpus.",
        )
    )

    queries.append(
        EvalQuery(
            query_id="c4_020",
            cohort="C4",
            query_text="standards for currency transaction reporting on repeated cash deposits",
            split=assign_split(SEED, "c4_020"),
            policy_applicability=PolicyApplicability.APPLICABLE,
            corpus_coverage=CorpusCoverage.NOT_COVERED,
            abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
            judgments=_make_judgments([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            rationale="In-domain coverage-gap query: currency transaction reporting thresholds and procedures are an applicable subject entirely absent from the synthetic corpus.",
        )
    )

    eval_set = EvalSet(
        version=EVAL_SET_VERSION,
        seed=SEED,
        corpus_id=CORPUS_ID,
        model_name=MODEL_NAME,
        model_snapshot=MODEL_SNAPSHOT,
        retrieval_k=RETRIEVAL_K,
        retrieval_top_k=RETRIEVAL_TOP_K,
        labeler_provenance=LABELER_PROVENANCE,
        cohort_status=dict(COHORT_STATUS),
        protocol_status=PROTOCOL_STATUS,
        chunk_refs=CORPUS_CHUNK_REFS,
        queries=tuple(queries),
    )

    validate_eval_set(eval_set)
    return eval_set
