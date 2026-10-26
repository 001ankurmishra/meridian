# ruff: noqa: E501
"""
Integrity and structural validation tests for PROPOSED RAG evaluation set fixture.

Status: FROZEN.
Protocol and evaluation set are pending human maintainer approval.

CRITICAL ARCHITECTURAL BOUNDARIES:
- NO retrieval execution
- NO embeddings or model loading
- NO database connections
- NO metric computation on real data
- Passing these tests proves structure, binding, and mathematical validity ONLY;
  it does NOT prove substantive correctness of human/AI judgments.
"""

import ast
import hashlib
import itertools
import math
import os
import re
import subprocess
import sys
from dataclasses import replace
from fractions import Fraction
from typing import List, Set, Tuple

import pytest

from meridian.agents.policy.chunking import chunk_document
from meridian.fixtures.policy_retrieval_eval_set import (
    CORPUS_CHUNK_REFS,
    PROTOCOL_STATUS,
    AbstentionGroundTruth,
    CorpusCoverage,
    EvalQuery,
    EvalSet,
    PolicyApplicability,
    assign_split,
    build_eval_set,
    canonical_json,
    canonical_sha256,
    validate_eval_set,
)
from meridian.loader.policy_corpus import POLICY_CORPUS_V1

# Pinned maintainer-approved canonical SHA-256 for change detection.
# Updating during review is expected; becomes the FROZEN identity only on maintainer approval.
FROZEN_CANONICAL_SHA256 = "993af9703de5b147a5f34ffa4d5bf01eafa025738915a3b0be940199aa78e053"


# =============================================================================
# 1. BINDING TEST
# =============================================================================
def test_binding_against_policy_corpus_and_chunking() -> None:
    """
    Recomputes (title, version, chunk_index, sha256(text)) from POLICY_CORPUS_V1
    via chunk_document and asserts exact set equality with the fixture's chunk refs.
    Fails loudly on any corpus or chunking drift.
    """
    recomputed_refs: List[Tuple[str, str, int, str]] = []
    for doc in POLICY_CORPUS_V1:
        chunks = chunk_document(doc.text)
        for idx, chunk_text in enumerate(chunks):
            sha = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
            recomputed_refs.append((doc.title, doc.version, idx, sha))

    assert len(recomputed_refs) == 10, f"Expected 10 chunks from POLICY_CORPUS_V1, got {len(recomputed_refs)}"

    fixture_refs = [
        (c.title, c.version, c.chunk_index, c.text_sha256)
        for c in CORPUS_CHUNK_REFS
    ]

    assert recomputed_refs == fixture_refs, "Fixture chunk refs drifted from POLICY_CORPUS_V1 chunking"


# =============================================================================
# 2. COMPLETENESS TEST
# =============================================================================
def test_judgments_completeness_and_notes() -> None:
    """
    Every query has exactly one judgment per chunk (all 10 chunks).
    Grades are strictly in {0, 1, 2}.
    Every grade 1 requires a non-empty note naming the supporting element.
    Every borderline=True requires a non-empty note of <= 200 chars.
    """
    eval_set = build_eval_set()
    canonical_refs = tuple(eval_set.chunk_refs)

    for q in eval_set.queries:
        assert len(q.judgments) == 10, f"Query {q.query_id} has {len(q.judgments)} judgments"
        judged_refs = tuple(j.chunk_ref for j in q.judgments)
        assert judged_refs == canonical_refs, f"Query {q.query_id} chunk refs mismatch"

        for j in q.judgments:
            assert j.grade in {0, 1, 2}, f"Query {q.query_id} invalid grade {j.grade}"
            if j.grade == 1:
                assert j.note is not None and len(j.note.strip()) > 0, (
                    f"Query {q.query_id} grade 1 missing required note"
                )
            if j.borderline:
                assert j.note is not None and len(j.note.strip()) > 0, (
                    f"Query {q.query_id} borderline judgment missing required note"
                )
                assert len(j.note) <= 200, (
                    f"Query {q.query_id} borderline note exceeds 200 chars: {len(j.note)}"
                )


# =============================================================================
# 3. VALIDATOR POSITIVE TEST
# =============================================================================
def test_validator_positive() -> None:
    """build_eval_set() produces an EvalSet that passes validate_eval_set without errors."""
    eval_set = build_eval_set()
    validate_eval_set(eval_set)


# =============================================================================
# 4. VALIDATOR NEGATIVE TESTS & ACCEPTANCE TEST
# =============================================================================
def _make_dummy_set_with_query(modified_query: EvalQuery) -> EvalSet:
    base = build_eval_set()
    # Replace query c1_01 with the modified query
    new_queries = [modified_query] + list(base.queries[1:])
    return replace(base, queries=tuple(new_queries))


def test_validator_negative_should_abstain_with_applicable() -> None:
    """V4 violation: SHOULD_ABSTAIN with APPLICABLE must raise ValueError."""
    base = build_eval_set()
    target = base.queries[0]
    bad_q = replace(
        target,
        policy_applicability=PolicyApplicability.APPLICABLE,
        corpus_coverage=CorpusCoverage.OUT_OF_DOMAIN,
        abstention_ground_truth=AbstentionGroundTruth.SHOULD_ABSTAIN,
        cohort="C3",
        split=assign_split(base.seed, target.query_id),
    )
    test_set = _make_dummy_set_with_query(bad_q)
    with pytest.raises(ValueError, match="V4 violation|V2 violation"):
        validate_eval_set(test_set)


def test_validator_negative_should_abstain_with_not_covered_in_domain() -> None:
    """V4 violation: SHOULD_ABSTAIN with NOT_COVERED and no out-of-domain basis must raise."""
    base = build_eval_set()
    target = base.queries[0]
    bad_judgments = tuple(replace(j, grade=0, note=None, borderline=False) for j in target.judgments)
    bad_q = replace(
        target,
        policy_applicability=PolicyApplicability.APPLICABLE,
        corpus_coverage=CorpusCoverage.NOT_COVERED,
        abstention_ground_truth=AbstentionGroundTruth.SHOULD_ABSTAIN,
        judgments=bad_judgments,
        cohort="C3",
        split=assign_split(base.seed, target.query_id),
    )
    test_set = _make_dummy_set_with_query(bad_q)
    with pytest.raises(ValueError, match="V4 violation"):
        validate_eval_set(test_set)


def test_validator_negative_not_applicable_with_nonzero_grade() -> None:
    """V1 violation: NOT_APPLICABLE_OUT_OF_DOMAIN with a nonzero grade must raise."""
    base = build_eval_set()
    target = base.queries[0]
    bad_q = replace(
        target,
        policy_applicability=PolicyApplicability.NOT_APPLICABLE_OUT_OF_DOMAIN,
        corpus_coverage=CorpusCoverage.OUT_OF_DOMAIN,
        abstention_ground_truth=AbstentionGroundTruth.SHOULD_ABSTAIN,
        cohort="C3",
        split=assign_split(base.seed, target.query_id),
        # target already has nonzero grades
    )
    test_set = _make_dummy_set_with_query(bad_q)
    with pytest.raises(ValueError, match="V1 violation"):
        validate_eval_set(test_set)


def test_validator_negative_covered_with_no_grade_2() -> None:
    """V3 violation: coverage COVERED with no grade 2 must raise."""
    base = build_eval_set()
    target = base.queries[0]
    no_grade2_judgments = tuple(
        replace(j, grade=1 if j.grade == 2 else j.grade, note="Supporting element" if j.grade == 2 else j.note)
        for j in target.judgments
    )
    bad_q = replace(
        target,
        corpus_coverage=CorpusCoverage.COVERED,
        judgments=no_grade2_judgments,
    )
    test_set = _make_dummy_set_with_query(bad_q)
    with pytest.raises(ValueError, match="V3 violation"):
        validate_eval_set(test_set)


def test_validator_negative_should_retrieve_with_not_covered() -> None:
    """V5 violation: SHOULD_RETRIEVE with NOT_COVERED must raise."""
    base = build_eval_set()
    target = base.queries[0]
    zero_judgments = tuple(replace(j, grade=0, note=None, borderline=False) for j in target.judgments)
    bad_q = replace(
        target,
        corpus_coverage=CorpusCoverage.NOT_COVERED,
        abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
        judgments=zero_judgments,
    )
    test_set = _make_dummy_set_with_query(bad_q)
    with pytest.raises(ValueError, match="V5 violation"):
        validate_eval_set(test_set)


def test_validator_negative_c2_query_with_should_retrieve() -> None:
    """V5/V7 violation: C2 query with SHOULD_RETRIEVE must raise."""
    base = build_eval_set()
    c2_q = next(q for q in base.queries if q.cohort == "C2" and q.corpus_coverage == CorpusCoverage.COVERED)
    bad_q = replace(
        c2_q,
        abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
    )
    test_set = _make_dummy_set_with_query(bad_q)
    with pytest.raises(ValueError, match="V5 violation|V7 violation"):
        validate_eval_set(test_set)


def test_validator_negative_undetermined_with_should_retrieve() -> None:
    """V5/V7 violation: UNDETERMINED with SHOULD_RETRIEVE must raise."""
    base = build_eval_set()
    target = base.queries[0]
    bad_q = replace(
        target,
        policy_applicability=PolicyApplicability.UNDETERMINED,
        abstention_ground_truth=AbstentionGroundTruth.SHOULD_RETRIEVE,
    )
    test_set = _make_dummy_set_with_query(bad_q)
    with pytest.raises(ValueError, match="V5 violation|V7 violation"):
        validate_eval_set(test_set)


def test_validator_accepts_applicable_not_covered_not_assessed() -> None:
    """
    CRITICAL ACCEPTANCE TEST:
    An APPLICABLE + NOT_COVERED + NOT_ASSESSED query is ACCEPTED.
    A missing grade-2 chunk or lack of synthetic corpus coverage NEVER implies
    SHOULD_ABSTAIN or non-applicability.
    """
    base = build_eval_set()
    target = base.queries[0]
    zero_judgments = tuple(replace(j, grade=0, note=None, borderline=False) for j in target.judgments)
    valid_gap_q = replace(
        target,
        policy_applicability=PolicyApplicability.APPLICABLE,
        corpus_coverage=CorpusCoverage.NOT_COVERED,
        abstention_ground_truth=AbstentionGroundTruth.NOT_ASSESSED,
        judgments=zero_judgments,
    )
    test_set = _make_dummy_set_with_query(valid_gap_q)
    # Must validate cleanly without raising
    validate_eval_set(test_set)


# =============================================================================
# 5. COHORT COUNTS AND EXACT STRINGS
# =============================================================================
def test_cohort_counts_and_exact_strings() -> None:
    """
    Verifies:
    - Exact C1 strings: ['large_transaction', 'new_beneficiary', 'rapid_movement']
    - Exact C2 strings: ['AML_GENERAL', 'AML_STRUCTURING', 'AML_RAPID_MOVEMENT', 'AML_CIRCULAR', 'AML_MULE']
    - Total query count in [38, 50]
    - >= 4 C4 coverage-gap queries
    - Empty string present exactly once in C3 with UNDETERMINED and NOT_ASSESSED
    - C2 cohort_status is PROVISIONAL
    - PROTOCOL_STATUS == 'FROZEN'
    """
    eval_set = build_eval_set()
    assert PROTOCOL_STATUS == "FROZEN"
    assert eval_set.protocol_status == "FROZEN"
    assert eval_set.cohort_status["C2"] == "PROVISIONAL"

    total_queries = len(eval_set.queries)
    assert 38 <= total_queries <= 50, f"Expected 38-50 queries, got {total_queries}"

    c1_queries = [q for q in eval_set.queries if q.cohort == "C1"]
    assert [q.query_text for q in c1_queries] == [
        "large_transaction",
        "new_beneficiary",
        "rapid_movement",
    ]

    c2_queries = [q for q in eval_set.queries if q.cohort == "C2"]
    assert [q.query_text for q in c2_queries] == [
        "AML_GENERAL",
        "AML_STRUCTURING",
        "AML_RAPID_MOVEMENT",
        "AML_CIRCULAR",
        "AML_MULE",
    ]

    c3_queries = [q for q in eval_set.queries if q.cohort == "C3"]
    empty_queries = [q for q in c3_queries if q.query_text == ""]
    assert len(empty_queries) == 1, f"Expected empty string exactly once in C3, got {len(empty_queries)}"
    assert empty_queries[0].policy_applicability == PolicyApplicability.UNDETERMINED
    assert empty_queries[0].abstention_ground_truth == AbstentionGroundTruth.NOT_ASSESSED
    assert empty_queries[0].corpus_coverage == CorpusCoverage.NOT_COVERED

    c4_queries = [q for q in eval_set.queries if q.cohort == "C4"]
    c4_coverage_gaps = [
        q for q in c4_queries
        if q.corpus_coverage in {CorpusCoverage.NOT_COVERED, CorpusCoverage.PARTIALLY_COVERED}
    ]
    assert len(c4_coverage_gaps) >= 4, f"Expected >=4 C4 coverage-gap queries, got {len(c4_coverage_gaps)}"


# =============================================================================
# 6. SPLIT ASSIGNMENT DETERMINISM
# =============================================================================
def test_split_assignments_and_hash_determinism() -> None:
    """
    Verifies:
    - C1 and C2 splits are 'NONE'
    - C3 and C4 splits match assign_split(seed, query_id)
    - >= 4 DEV and >= 4 HELDOUT in C3 and C4
    - Split assignment is deterministic across PYTHONHASHSEED values via subprocess
    """
    eval_set = build_eval_set()
    c3_dev = sum(1 for q in eval_set.queries if q.cohort == "C3" and q.split == "DEV")
    c3_heldout = sum(1 for q in eval_set.queries if q.cohort == "C3" and q.split == "HELDOUT")
    assert c3_dev >= 4 and c3_heldout >= 4, f"C3 split balance violated: DEV={c3_dev}, HELDOUT={c3_heldout}"

    c4_dev = sum(1 for q in eval_set.queries if q.cohort == "C4" and q.split == "DEV")
    c4_heldout = sum(1 for q in eval_set.queries if q.cohort == "C4" and q.split == "HELDOUT")
    assert c4_dev >= 4 and c4_heldout >= 4, f"C4 split balance violated: DEV={c4_dev}, HELDOUT={c4_heldout}"

    for q in eval_set.queries:
        if q.cohort in {"C1", "C2"}:
            assert q.split == "NONE"
        else:
            assert q.split == assign_split(eval_set.seed, q.query_id)

    # Subprocess check across PYTHONHASHSEED values
    for seed_val in ["0", "1", "42"]:
        env = dict(os.environ, PYTHONPATH=os.path.abspath('src'), PYTHONHASHSEED=seed_val)
        res = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from meridian.fixtures.policy_retrieval_eval_set import build_eval_set, assign_split; "
                    "es = build_eval_set(); "
                    "splits = [q.split for q in es.queries if q.cohort in ('C3', 'C4')]; "
                    "expected = [assign_split(es.seed, q.query_id) for q in es.queries if q.cohort in ('C3', 'C4')]; "
                    "assert splits == expected; print('OK')"
                ),
            ],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        assert "OK" in res.stdout


# =============================================================================
# 7. LEAKAGE GUARD
# =============================================================================
def test_c4_query_leakage_guard() -> None:
    """No C4 query shares a contiguous 5-word span (case-folded, punctuation-stripped) with any chunk text."""
    eval_set = build_eval_set()
    chunks = []
    for doc in POLICY_CORPUS_V1:
        chunks.extend(chunk_document(doc.text))

    def word_tokens(s: str) -> List[str]:
        return re.findall(r"\w+", s.lower())

    def get_ngrams(words: List[str], n: int = 5) -> Set[Tuple[str, ...]]:
        return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}

    chunk_5grams: Set[Tuple[str, ...]] = set()
    for c in chunks:
        chunk_5grams.update(get_ngrams(word_tokens(c), 5))

    c4_queries = [q for q in eval_set.queries if q.cohort == "C4"]
    for q in c4_queries:
        q_words = word_tokens(q.query_text)
        q_5grams = get_ngrams(q_words, 5)
        overlap = q_5grams.intersection(chunk_5grams)
        assert not overlap, f"5-word leakage detected in C4 query '{q.query_id}': {overlap}"


# =============================================================================
# 8. CANONICAL JSON AND PINNED SHA-256
# =============================================================================
def test_canonical_json_determinism_and_pinned_sha256() -> None:
    """
    canonical_json is byte-identical across two builds and a fresh subprocess.
    SHA-256 equals FROZEN_CANONICAL_SHA256 pinned in this test suite.
    """
    set1 = build_eval_set()
    set2 = build_eval_set()

    json1 = canonical_json(set1)
    json2 = canonical_json(set2)
    assert json1 == json2, "canonical_json differed across consecutive builds in same process"

    sha1 = canonical_sha256(set1)
    assert sha1 == FROZEN_CANONICAL_SHA256, (
        f"canonical_sha256 {sha1} does not match FROZEN_CANONICAL_SHA256 {FROZEN_CANONICAL_SHA256}"
    )

    # Subprocess check for byte-identical serialization in a clean interpreter
    env = dict(os.environ, PYTHONPATH=os.path.abspath('src'))
    res = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from meridian.fixtures.policy_retrieval_eval_set import build_eval_set, canonical_json, canonical_sha256; "
                "es = build_eval_set(); "
                "print(canonical_sha256(es))"
            ),
        ],
        capture_output=True,
            env=env,
        text=True,
        check=True,
    )
    subprocess_sha = res.stdout.strip()
    assert subprocess_sha == FROZEN_CANONICAL_SHA256


# =============================================================================
# 9. FORBIDDEN VOCABULARY SCAN
# =============================================================================
def test_forbidden_vocabulary_scan() -> None:
    """
    Scans all fixture text and strings for forbidden vocabulary:
    'suspicious', 'money laundering', 'recommend escalation', accusatory phrasing.
    """
    fixture_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "meridian", "fixtures", "policy_retrieval_eval_set.py"
    )
    with open(fixture_path, "r", encoding="utf-8") as f:
        file_text = f.read().lower()

    forbidden_patterns = [
        r"\bsuspicious\b",
        r"\bmoney laundering\b",
        r"\brecommend escalation\b",
        r"\baccus\w*\b",
        r"\billicit\b",
        r"\bguilty\b",
    ]

    for pat in forbidden_patterns:
        matches = re.findall(pat, file_text)
        assert not matches, f"Forbidden vocabulary pattern '{pat}' matched in fixture file: {matches}"

    # Also scan runtime data fields of EvalSet
    eval_set = build_eval_set()
    all_strings = []
    for q in eval_set.queries:
        all_strings.extend([q.query_text, q.rationale])
        for j in q.judgments:
            if j.note:
                all_strings.append(j.note)

    for s in all_strings:
        lower_s = s.lower()
        for pat in forbidden_patterns:
            matches = re.findall(pat, lower_s)
            assert not matches, f"Forbidden vocabulary pattern '{pat}' matched in runtime string '{s}'"


# =============================================================================
# 10. IMPORT GUARD AND AST ISOLATION
# =============================================================================
def test_import_guard_and_ast_isolation() -> None:
    """
    Subprocess test: Importing the fixture, chunk_document and policy_corpus leaves
    sentence_transformers, meridian.agents.policy.retrieval, meridian.db.session out of sys.modules.
    Also AST inspection: fixture module imports only stdlib modules.
    """
    # 1. Subprocess import check
    env = dict(os.environ, PYTHONPATH=os.path.abspath('src'))
    res = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import meridian.fixtures.policy_retrieval_eval_set; "
                "from meridian.agents.policy.chunking import chunk_document; "
                "from meridian.loader.policy_corpus import POLICY_CORPUS_V1; "
                "forbidden = ['sentence_transformers', 'meridian.agents.policy.retrieval', 'meridian.db.session', 'meridian.agents.policy.policy_agent']; "
                "loaded = [m for m in forbidden if m in sys.modules]; "
                "assert not loaded, f'Forbidden modules loaded: {loaded}'; "
                "print('OK')"
            ),
        ],
        capture_output=True,
            env=env,
        text=True,
        check=True,
    )
    assert "OK" in res.stdout

    # 2. AST inspection of fixture module
    fixture_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "meridian", "fixtures", "policy_retrieval_eval_set.py"
    )
    with open(fixture_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=fixture_path)

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module.split(".")[0])

    allowed_stdlib = {"dataclasses", "enum", "hashlib", "json", "typing"}
    for mod in imported_modules:
        assert mod in allowed_stdlib, f"Non-stdlib or unapproved module imported in fixture: {mod}"


# =============================================================================
# 11. FORMULA VERIFICATION ON TOY INPUTS ONLY
# =============================================================================
# Test-local closed-form expectation formulas.
# Note: These helpers must NOT be applied to fixture queries or retrieval output
# and must NOT be placed in a reusable module.

def _toy_exp_precision(N: int, R: int, k: int) -> Fraction:
    return Fraction(R, N)


def _toy_exp_recall(N: int, R: int, k: int) -> Fraction:
    return Fraction(k, N)


def _toy_exp_hit(N: int, R: int, k: int) -> Fraction:
    if k > N:
        return Fraction(1, 1)
    return Fraction(1, 1) - Fraction(math.comb(N - R, k), math.comb(N, k))


def _toy_exp_rr(N: int, R: int) -> Fraction:
    total = Fraction(0, 1)
    denom = math.comb(N, R)
    for j in range(1, N - R + 2):
        term = Fraction(math.comb(N - j, R - 1), j * denom)
        total += term
    return total


def _toy_dcg(grades: List[int], k: int) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(grades[:k]))


def _toy_idcg(grades: List[int], k: int) -> float:
    return _toy_dcg(sorted(grades, reverse=True), k)


def _toy_exp_ndcg(grades: List[int], k: int) -> float:
    N = len(grades)
    G = sum(grades)
    ideal = _toy_idcg(grades, k)
    if ideal == 0.0:
        return 0.0
    discount_sum = sum(1.0 / math.log2(i + 2) for i in range(k))
    return ((G / N) * discount_sum) / ideal


def test_random_ordering_expectation_formulas_toy_verification() -> None:
    """
    Checks closed-form expectation helpers against brute-force enumeration of all
    permutations on N=6 for R in {1,2,3} and graded vector [2,1,1,0,0,0] for k in {1,3,5}.
    Asserts exact equality for rational metrics and 1e-9 for nDCG.
    Also asserts worked example values for N=10, R=3:
    - E[Hit@5] == 11/12
    - E[RR] == 3601/6720
    - E[nDCG@5] == 0.376688 (rounds to 0.3767).
    """
    # 1. Brute force check on N=6
    N = 6
    for R in [1, 2, 3]:
        vec = [1] * R + [0] * (N - R)
        perms = list(itertools.permutations(vec))
        num_perms = len(perms)

        for k in [1, 3, 5]:
            brute_p = Fraction(sum(sum(p[:k]) for p in perms), num_perms * k)
            assert brute_p == _toy_exp_precision(N, R, k), f"P@{k} mismatch for R={R}"

            brute_r = Fraction(sum(sum(p[:k]) for p in perms), num_perms * R)
            assert brute_r == _toy_exp_recall(N, R, k), f"R@{k} mismatch for R={R}"

            brute_hit = Fraction(sum(1 for p in perms if any(p[:k])), num_perms)
            assert brute_hit == _toy_exp_hit(N, R, k), f"Hit@{k} mismatch for R={R}"

        # Reciprocal Rank
        brute_rr_sum = Fraction(0, 1)
        for p in perms:
            first_rel_rank = next(i for i, val in enumerate(p) if val == 1) + 1
            brute_rr_sum += Fraction(1, first_rel_rank)
        brute_rr = brute_rr_sum / num_perms
        assert brute_rr == _toy_exp_rr(N, R), f"RR mismatch for R={R}"

    # Graded nDCG check on N=6
    graded_vec = [2, 1, 1, 0, 0, 0]
    graded_perms = list(itertools.permutations(graded_vec))
    num_graded_perms = len(graded_perms)

    for k in [1, 3, 5]:
        ideal = _toy_idcg(graded_vec, k)
        brute_ndcg = sum(_toy_dcg(list(p), k) / ideal for p in graded_perms) / num_graded_perms
        closed_ndcg = _toy_exp_ndcg(graded_vec, k)
        assert abs(brute_ndcg - closed_ndcg) < 1e-9, f"nDCG@{k} mismatch: {brute_ndcg} vs {closed_ndcg}"

    # 2. Worked example assertions (N=10, R=3)
    assert _toy_exp_precision(10, 3, 5) == Fraction(3, 10)
    assert _toy_exp_recall(10, 3, 5) == Fraction(1, 2)
    assert _toy_exp_hit(10, 3, 5) == Fraction(11, 12)
    assert _toy_exp_rr(10, 3) == Fraction(3601, 6720)

    # Graded worked example: one 2, two 1, rest 0, k=5, N=10
    worked_grades = [2, 1, 1, 0, 0, 0, 0, 0, 0, 0]
    worked_ndcg = _toy_exp_ndcg(worked_grades, 5)
    assert f"{worked_ndcg:.6f}" == "0.376688"
    assert round(worked_ndcg, 4) == 0.3767
