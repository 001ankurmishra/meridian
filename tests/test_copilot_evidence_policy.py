# ruff: noqa: E501
"""Focused tests for Copilot EvidencePackage policy provenance verification and binding (M2).

Covers:
1. Registered, untampered policy chunk is included as verified evidence.
2. Modified chunk text is rejected fail-closed (CHUNK_HASH_MISMATCH).
3. Unregistered document is rejected (UNREGISTERED_DOCUMENT).
4. Unsupported document version or provenance mismatch is rejected (PROVENANCE_MISMATCH, NOT_APPROVED).
5. Chunk index, ordering, or metadata mismatches are rejected (CHUNK_INDEX_OUT_OF_BOUNDS, CHUNK_HASH_MISMATCH).
6. Registry identity or content changes affect package_hash.
7. Policy chunk digest or policy text changes affect package_hash.
8. Identical evidence inputs produce identical package hashes (determinism).
9. Empty evidence behaves according to the existing contract.
10. Mixed policy, investigation, and audit evidence preserves established semantics.
11. Existing failure behavior, scope checks, and public interfaces remain compatible.
12. Zero ML / PyTorch / Transformers loaded during evidence packaging.
13. Real PostgreSQL integration: load_package verifies DB chunks in read-only snapshot.
"""

import asyncio
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from typing import Generator
from uuid import UUID

import pytest
from sqlalchemy import Engine, text

from meridian.agents.policy.chunking import chunk_document
from meridian.agents.report.report_assembly import InvestigationReport
from meridian.agents.report.screening_classification import classify_screening_state
from meridian.copilot.drafts import (
    MockProvider,
    generate_draft,
    load_package,
    package_report,
)
from meridian.copilot.policy_verification import (
    PolicyChunkRecord,
    PolicyVerificationReason,
    verify_policy_chunk,
)
from meridian.evidence.evidence import (
    EVIDENCE_TYPE_ALERTED_TRANSACTION,
    EVIDENCE_TYPE_POLICY_CHUNK,
    EvidenceRecord,
    record_evidence,
)
from meridian.findings.findings import FindingRecord, record_finding
from meridian.identity.tokens import issue_token
from meridian.loader.policy_corpus import POLICY_CORPUS_V1
from meridian.loader.policy_ingest import ingest_policy_corpus
from meridian.orchestration.investigation_run import create_investigation_run
from meridian.recommendations.recommendations import RecommendationRecord
from meridian.registry.generator import load_canonical_registry
from tests.test_identity_tokens import _cleanup_user, _seed_user
from tests.test_report_assembly import (
    _cleanup_seeded_data,
    setup_agent_run,
    setup_alert,
    setup_case,
    setup_customer_and_transaction,
)

pytestmark = pytest.mark.offline_guard_unit

CASE_ID = UUID("11111111-1111-1111-1111-111111111111")
RUN_ID = UUID("22222222-2222-2222-2222-222222222222")
EV_TX_ID = UUID("33333333-3333-3333-3333-333333333333")
EV_POL_ID = UUID("44444444-4444-4444-4444-444444444444")
FIND_TX_ID = UUID("55555555-5555-5555-5555-555555555555")
FIND_POL_ID = UUID("66666666-6666-6666-6666-666666666666")
REC_ID = UUID("77777777-7777-7777-7777-777777777777")
AGENT_ID = UUID("88888888-8888-8888-8888-888888888888")
SOURCE_ID = UUID("99999999-9999-9999-9999-999999999999")
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Extract real approved chunks from canonical corpus
_DOC_RAPID = next(d for d in POLICY_CORPUS_V1 if "Rapid movement" in d.title)
_CHUNKS_RAPID = chunk_document(_DOC_RAPID.text)
DOC_RAPID_FUNDS_TITLE = _DOC_RAPID.title
DOC_RAPID_FUNDS_TYPE = _DOC_RAPID.document_type
DOC_RAPID_FUNDS_VERSION = _DOC_RAPID.version
DOC_RAPID_FUNDS_REF = _DOC_RAPID.source_url_or_ref

CHUNK_RAPID_FUNDS_0_TEXT = _CHUNKS_RAPID[0]
CHUNK_RAPID_FUNDS_1_TEXT = _CHUNKS_RAPID[1]


def make_policy_chunk_record(
    chunk_id: UUID = SOURCE_ID,
    chunk_index: int = 0,
    chunk_text: str = CHUNK_RAPID_FUNDS_0_TEXT,
    title: str = DOC_RAPID_FUNDS_TITLE,
    document_type: str = DOC_RAPID_FUNDS_TYPE,
    version: str = DOC_RAPID_FUNDS_VERSION,
    source_url_or_ref: str | None = DOC_RAPID_FUNDS_REF,
    is_synthetic: bool = True,
) -> PolicyChunkRecord:
    """Helper creating a test PolicyChunkRecord with approved defaults."""
    return PolicyChunkRecord(
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        title=title,
        document_type=document_type,
        version=version,
        source_url_or_ref=source_url_or_ref,
        is_synthetic=is_synthetic,
    )


def make_investigation_report(
    findings: list[FindingRecord] | None = None,
    evidence: list[EvidenceRecord] | None = None,
    applicable_policies: list[EvidenceRecord] | None = None,
    recommendations: list[RecommendationRecord] | None = None,
    completeness_status: str = "COMPLETE",
) -> InvestigationReport:
    """Helper building an InvestigationReport with controlled components."""
    if findings is None:
        findings = [
            FindingRecord(
                finding_id=FIND_TX_ID,
                investigation_run_id=RUN_ID,
                observed_fact="Recorded amount is INR 100.00.",
                derived_signal=None,
                interpretation=None,
                evidence_ids=[EV_TX_ID],
                confidence="LOW",
                created_at=NOW,
            )
        ]
    if evidence is None:
        evidence = [
            EvidenceRecord(
                evidence_id=EV_TX_ID,
                investigation_run_id=RUN_ID,
                evidence_type=EVIDENCE_TYPE_ALERTED_TRANSACTION,
                reference_table="transactions",
                reference_id=SOURCE_ID,
                produced_by_agent_run_id=AGENT_ID,
                created_at=NOW,
            )
        ]
    if applicable_policies is None:
        applicable_policies = []
    if recommendations is None:
        recommendations = []

    return InvestigationReport(
        investigation_run_id=RUN_ID,
        case_id=CASE_ID,
        customer_name="Test Customer",
        is_synthetic=True,
        risk_level="LOW",
        evidence_completeness_status=completeness_status,
        summary="Test Summary",
        findings=findings,
        evidence=evidence,
        applicable_policies=applicable_policies,
        recommendations=recommendations,
        risk_signals=[],
        confidence_text="Confidence is LOW.",
        watchlist_screening=classify_screening_state(
            screening_result=None,
            referenced_agent_run=None,
            all_sanctions_agent_runs=(),
            candidate_finding_count=0,
        ),
    )


# ---------------------------------------------------------------------------
# 1. Registered untampered policy chunk is included as verified evidence
# ---------------------------------------------------------------------------


def test_registered_untampered_policy_chunk_included():
    chunk_rec = make_policy_chunk_record()
    outcome = verify_policy_chunk(chunk_rec)
    assert outcome.is_valid is True
    assert outcome.chunk_hash is not None
    assert outcome.registry_version == "meridian.policy-registry.v1"

    ev_policy = EvidenceRecord(
        evidence_id=EV_POL_ID,
        investigation_run_id=RUN_ID,
        evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
        reference_table="document_chunks",
        reference_id=chunk_rec.chunk_id,
        produced_by_agent_run_id=AGENT_ID,
        created_at=NOW,
    )
    report = make_investigation_report(applicable_policies=[ev_policy])

    pkg = package_report(report, CASE_ID, RUN_ID, policy_chunks=[chunk_rec])

    # Check verified policy passage
    policy_passages = [p for p in pkg.passages if p.passage_id.startswith("policy:")]
    assert len(policy_passages) == 1
    p = policy_passages[0]
    assert p.passage_id == f"policy:{EV_POL_ID}"
    assert p.kind == "observed_fact"
    assert p.text == CHUNK_RAPID_FUNDS_0_TEXT
    assert p.evidence_ids == (str(EV_POL_ID),)
    assert p.confidence == "RECORDED"

    # Check cryptographic policy provenance binding
    assert pkg.policy_provenance is not None
    assert pkg.policy_provenance["registry_version"] == "meridian.policy-registry.v1"
    assert len(pkg.policy_provenance["chunks"]) == 1
    chunk_meta = pkg.policy_provenance["chunks"][0]
    assert chunk_meta["chunk_hash"] == outcome.chunk_hash
    assert chunk_meta["chunk_index"] == 0
    assert chunk_meta["document_title"] == DOC_RAPID_FUNDS_TITLE
    assert chunk_meta["evidence_id"] == str(EV_POL_ID)

    # Check extractive draft generation
    result = asyncio.run(generate_draft(pkg, MockProvider()))
    assert result.status == "DRAFT"
    claim_texts = [c.text for c in result.draft.summary]
    assert CHUNK_RAPID_FUNDS_0_TEXT in claim_texts


# ---------------------------------------------------------------------------
# 2. Modified chunk text is rejected fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "corrupted_text",
    [
        CHUNK_RAPID_FUNDS_0_TEXT + " extra text",
        CHUNK_RAPID_FUNDS_0_TEXT[:-1],
        CHUNK_RAPID_FUNDS_0_TEXT.replace("purposes", "PURPOSES"),
        CHUNK_RAPID_FUNDS_0_TEXT.replace("cryptocurrency", "blockchain"),
    ],
)
def test_modified_chunk_text_rejected(corrupted_text):
    chunk_rec = make_policy_chunk_record(chunk_text=corrupted_text)
    outcome = verify_policy_chunk(chunk_rec)
    assert outcome.is_valid is False
    assert outcome.reason == PolicyVerificationReason.CHUNK_HASH_MISMATCH

    ev_policy = EvidenceRecord(
        evidence_id=EV_POL_ID,
        investigation_run_id=RUN_ID,
        evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
        reference_table="document_chunks",
        reference_id=chunk_rec.chunk_id,
        produced_by_agent_run_id=AGENT_ID,
        created_at=NOW,
    )
    report = make_investigation_report(applicable_policies=[ev_policy])
    pkg = package_report(report, CASE_ID, RUN_ID, policy_chunks=[chunk_rec])

    # Tampered chunk must NOT appear in passages
    assert not any(p.passage_id.startswith("policy:") for p in pkg.passages)
    assert pkg.policy_provenance is None
    assert any("omitted" in lim for lim in pkg.limitations)


# ---------------------------------------------------------------------------
# 3. Unregistered document is rejected
# ---------------------------------------------------------------------------


def test_unregistered_document_rejected():
    chunk_rec = make_policy_chunk_record(title="Unregistered Synthetic Policy")
    outcome = verify_policy_chunk(chunk_rec)
    assert outcome.is_valid is False
    assert outcome.reason == PolicyVerificationReason.UNREGISTERED_DOCUMENT

    ev_policy = EvidenceRecord(
        evidence_id=EV_POL_ID,
        investigation_run_id=RUN_ID,
        evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
        reference_table="document_chunks",
        reference_id=chunk_rec.chunk_id,
        produced_by_agent_run_id=AGENT_ID,
        created_at=NOW,
    )
    report = make_investigation_report(applicable_policies=[ev_policy])
    pkg = package_report(report, CASE_ID, RUN_ID, policy_chunks=[chunk_rec])

    assert not any(p.passage_id.startswith("policy:") for p in pkg.passages)
    assert pkg.policy_provenance is None
    assert any("omitted" in lim for lim in pkg.limitations)


# ---------------------------------------------------------------------------
# 4. Unsupported document version or provenance mismatch is rejected
# ---------------------------------------------------------------------------


def test_unsupported_version_rejected():
    chunk_rec = make_policy_chunk_record(version="v2")
    outcome = verify_policy_chunk(chunk_rec)
    assert outcome.is_valid is False
    assert outcome.reason == PolicyVerificationReason.UNREGISTERED_DOCUMENT


def test_non_synthetic_document_rejected():
    chunk_rec = make_policy_chunk_record(is_synthetic=False)
    outcome = verify_policy_chunk(chunk_rec)
    assert outcome.is_valid is False
    assert outcome.reason == PolicyVerificationReason.PROVENANCE_MISMATCH


def test_unapproved_document_rejected():
    registry = load_canonical_registry()
    # Mark the document as unapproved in a custom test registry
    altered_registry = deepcopy(registry)
    for doc in altered_registry["documents"]:
        if doc["title"] == DOC_RAPID_FUNDS_TITLE:
            doc["approved_for_public_deployment"] = False

    chunk_rec = make_policy_chunk_record()
    outcome = verify_policy_chunk(chunk_rec, registry=altered_registry)
    assert outcome.is_valid is False
    assert outcome.reason == PolicyVerificationReason.NOT_APPROVED


# ---------------------------------------------------------------------------
# 5. Chunk index, ordering, or metadata mismatches are rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_index", [-1, 3, 4, 100])
def test_chunk_index_out_of_bounds_rejected(bad_index):
    chunk_rec = make_policy_chunk_record(chunk_index=bad_index)
    outcome = verify_policy_chunk(chunk_rec)
    assert outcome.is_valid is False
    assert outcome.reason == PolicyVerificationReason.CHUNK_INDEX_OUT_OF_BOUNDS


def test_chunk_index_text_mismatch_rejected():
    # Chunk 0 text paired with chunk index 1
    chunk_rec = make_policy_chunk_record(
        chunk_index=1, chunk_text=CHUNK_RAPID_FUNDS_0_TEXT
    )
    outcome = verify_policy_chunk(chunk_rec)
    assert outcome.is_valid is False
    assert outcome.reason == PolicyVerificationReason.CHUNK_HASH_MISMATCH


def test_metadata_mismatch_rejected():
    # Wrong document_type
    chunk_rec = make_policy_chunk_record(document_type="regulatory_guidance")
    outcome = verify_policy_chunk(chunk_rec)
    assert outcome.is_valid is False
    assert outcome.reason == PolicyVerificationReason.UNREGISTERED_DOCUMENT

    # Wrong source_url_or_ref
    chunk_rec_ref = make_policy_chunk_record(source_url_or_ref="wrong-reference")
    outcome_ref = verify_policy_chunk(chunk_rec_ref)
    assert outcome_ref.is_valid is False
    assert outcome_ref.reason == PolicyVerificationReason.UNREGISTERED_DOCUMENT


# ---------------------------------------------------------------------------
# 6. Registry identity or content changes affect package_hash
# ---------------------------------------------------------------------------


def test_registry_identity_or_content_changes_affect_package_hash():
    chunk_rec = make_policy_chunk_record()
    ev_policy = EvidenceRecord(
        evidence_id=EV_POL_ID,
        investigation_run_id=RUN_ID,
        evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
        reference_table="document_chunks",
        reference_id=chunk_rec.chunk_id,
        produced_by_agent_run_id=AGENT_ID,
        created_at=NOW,
    )
    report = make_investigation_report(applicable_policies=[ev_policy])

    # Standard package with committed registry
    pkg_standard = package_report(report, CASE_ID, RUN_ID, policy_chunks=[chunk_rec])

    # Custom registry with modified registry_version
    reg_modified_version = deepcopy(load_canonical_registry())
    reg_modified_version["registry_version"] = "meridian.policy-registry.v2"
    pkg_mod_version = package_report(
        report,
        CASE_ID,
        RUN_ID,
        policy_chunks=[chunk_rec],
        registry=reg_modified_version,
    )

    assert pkg_standard.package_hash != pkg_mod_version.package_hash
    assert (
        pkg_mod_version.policy_provenance["registry_version"]
        == "meridian.policy-registry.v2"
    )

    # Custom registry with modified doc_hash
    reg_modified_content = deepcopy(load_canonical_registry())
    for d in reg_modified_content["documents"]:
        if d["title"] == DOC_RAPID_FUNDS_TITLE:
            d["doc_hash"] = "0" * 64
    pkg_mod_content = package_report(
        report,
        CASE_ID,
        RUN_ID,
        policy_chunks=[chunk_rec],
        registry=reg_modified_content,
    )

    assert pkg_standard.package_hash != pkg_mod_content.package_hash


# ---------------------------------------------------------------------------
# 7. Policy chunk digest or policy text changes affect package_hash
# ---------------------------------------------------------------------------


def test_chunk_change_affects_package_hash():
    chunk_rec_0 = make_policy_chunk_record(
        chunk_index=0, chunk_text=CHUNK_RAPID_FUNDS_0_TEXT
    )
    chunk_rec_1 = make_policy_chunk_record(
        chunk_index=1, chunk_text=CHUNK_RAPID_FUNDS_1_TEXT
    )

    ev_0 = EvidenceRecord(
        evidence_id=EV_POL_ID,
        investigation_run_id=RUN_ID,
        evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
        reference_table="document_chunks",
        reference_id=chunk_rec_0.chunk_id,
        produced_by_agent_run_id=AGENT_ID,
        created_at=NOW,
    )
    ev_1 = EvidenceRecord(
        evidence_id=EV_POL_ID,
        investigation_run_id=RUN_ID,
        evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
        reference_table="document_chunks",
        reference_id=chunk_rec_1.chunk_id,
        produced_by_agent_run_id=AGENT_ID,
        created_at=NOW,
    )

    pkg_0 = package_report(
        make_investigation_report(applicable_policies=[ev_0]),
        CASE_ID,
        RUN_ID,
        policy_chunks=[chunk_rec_0],
    )
    pkg_1 = package_report(
        make_investigation_report(applicable_policies=[ev_1]),
        CASE_ID,
        RUN_ID,
        policy_chunks=[chunk_rec_1],
    )

    assert pkg_0.package_hash != pkg_1.package_hash


# ---------------------------------------------------------------------------
# 8. Identical evidence inputs produce identical package hashes (determinism)
# ---------------------------------------------------------------------------


def test_package_hash_is_deterministic():
    chunk_rec = make_policy_chunk_record()
    ev_policy = EvidenceRecord(
        evidence_id=EV_POL_ID,
        investigation_run_id=RUN_ID,
        evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
        reference_table="document_chunks",
        reference_id=chunk_rec.chunk_id,
        produced_by_agent_run_id=AGENT_ID,
        created_at=NOW,
    )
    report = make_investigation_report(applicable_policies=[ev_policy])

    hashes = [
        package_report(
            report, CASE_ID, RUN_ID, policy_chunks=[chunk_rec]
        ).package_hash
        for _ in range(5)
    ]
    assert len(set(hashes)) == 1


# ---------------------------------------------------------------------------
# 9. Empty evidence behaves according to the existing contract
# ---------------------------------------------------------------------------


def test_empty_policy_evidence_preserves_contract():
    report_no_policy = make_investigation_report(applicable_policies=[])
    pkg = package_report(report_no_policy, CASE_ID, RUN_ID)

    assert pkg.policy_provenance is None
    assert len(pkg.passages) == 1
    assert pkg.passages[0].passage_id == f"{FIND_TX_ID}:observed_fact"
    # Ensure payload() does not include policy_provenance key when None
    payload_dict = pkg.payload()
    assert "policy_provenance" not in payload_dict


# ---------------------------------------------------------------------------
# 10. Mixed policy, investigation, and audit evidence preserves semantics
# ---------------------------------------------------------------------------


def test_mixed_evidence_semantics():
    chunk_rec = make_policy_chunk_record()
    ev_tx = EvidenceRecord(
        evidence_id=EV_TX_ID,
        investigation_run_id=RUN_ID,
        evidence_type=EVIDENCE_TYPE_ALERTED_TRANSACTION,
        reference_table="transactions",
        reference_id=SOURCE_ID,
        produced_by_agent_run_id=AGENT_ID,
        created_at=NOW,
    )
    ev_policy = EvidenceRecord(
        evidence_id=EV_POL_ID,
        investigation_run_id=RUN_ID,
        evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
        reference_table="document_chunks",
        reference_id=chunk_rec.chunk_id,
        produced_by_agent_run_id=AGENT_ID,
        created_at=NOW,
    )
    finding_tx = FindingRecord(
        finding_id=FIND_TX_ID,
        investigation_run_id=RUN_ID,
        observed_fact="Recorded amount is INR 100.00.",
        derived_signal="Velocity is normal.",
        interpretation="No immediate risk.",
        evidence_ids=[EV_TX_ID],
        confidence="LOW",
        created_at=NOW,
    )
    finding_policy = FindingRecord(
        finding_id=FIND_POL_ID,
        investigation_run_id=RUN_ID,
        observed_fact="Policy reference finding text (should be omitted)",
        derived_signal=None,
        interpretation=None,
        evidence_ids=[EV_POL_ID],
        confidence="LOW",
        created_at=NOW,
    )
    rec = RecommendationRecord(
        recommendation_id=REC_ID,
        investigation_run_id=RUN_ID,
        text="Review transaction history.",
        based_on_finding_ids=[FIND_TX_ID],
        created_at=NOW,
    )

    report = make_investigation_report(
        findings=[finding_tx, finding_policy],
        evidence=[ev_tx],
        applicable_policies=[ev_policy],
        recommendations=[rec],
    )

    pkg = package_report(report, CASE_ID, RUN_ID, policy_chunks=[chunk_rec])

    # Check passages
    passage_ids = [p.passage_id for p in pkg.passages]
    # Investigative finding passages
    assert f"{FIND_TX_ID}:observed_fact" in passage_ids
    assert f"{FIND_TX_ID}:derived_signal" in passage_ids
    assert f"{FIND_TX_ID}:interpretation" in passage_ids
    # Policy chunk passage
    assert f"policy:{EV_POL_ID}" in passage_ids
    # Recommendation passage
    assert str(REC_ID) in passage_ids
    # Generated policy finding text was suppressed
    assert f"{FIND_POL_ID}:observed_fact" not in passage_ids

    # Policy passage has citing finding linked
    policy_p = next(p for p in pkg.passages if p.passage_id == f"policy:{EV_POL_ID}")
    assert policy_p.finding_ids == (str(FIND_POL_ID),)
    assert policy_p.text == CHUNK_RAPID_FUNDS_0_TEXT

    # Extractive draft generation works seamlessly
    draft_result = asyncio.run(generate_draft(pkg, MockProvider()))
    assert draft_result.status == "DRAFT"
    assert draft_result.draft is not None
    summary_ids = [c.passage_id for c in draft_result.draft.summary]
    assert f"{FIND_TX_ID}:observed_fact" in summary_ids
    assert f"policy:{EV_POL_ID}" in summary_ids


# ---------------------------------------------------------------------------
# 11. Existing failure behavior and scope boundaries remain compatible
# ---------------------------------------------------------------------------


def test_scope_mismatch_and_status_checks():
    report = make_investigation_report()

    # Scope mismatch: wrong case_id
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        package_report(report, UUID(int=999), RUN_ID)

    # Scope mismatch: wrong run_id
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        package_report(report, CASE_ID, UUID(int=999))

    # Run not final
    report_in_progress = make_investigation_report(completeness_status="IN_PROGRESS")
    with pytest.raises(ValueError, match="RUN_NOT_FINAL"):
        package_report(report_in_progress, CASE_ID, RUN_ID)


# ---------------------------------------------------------------------------
# 12. Runtime boundary: No ML libraries loaded during evidence packaging
# ---------------------------------------------------------------------------


def test_zero_ml_libraries_loaded():
    import os
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    src_dir = str(repo_root / "src")
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        f"{src_dir}:{env['PYTHONPATH']}" if "PYTHONPATH" in env else src_dir
    )

    cmd = [
        sys.executable,
        "-c",
        (
            "import sys, meridian.copilot.drafts, meridian.copilot.policy_verification; "
            "assert 'transformers' not in sys.modules, 'transformers was imported'; "
            "assert 'torch' not in sys.modules, 'torch was imported'"
        ),
    ]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert res.returncode == 0, f"ML libraries were imported: {res.stderr}"


# ---------------------------------------------------------------------------
# 13. Real PostgreSQL Integration Test
# ---------------------------------------------------------------------------


@pytest.fixture
def policy_db_seeded(
    superuser_engine: Engine, loader_role_engine: Engine, app_role_engine: Engine
) -> Generator[tuple[UUID, UUID, UUID, str], None, None]:
    """Sets up a real database investigation run citing a real ingested policy chunk."""
    # 1. Clean and populate real policy corpus
    with superuser_engine.begin() as conn:
        conn.execute(text("TRUNCATE document_chunks, documents CASCADE"))
    docs_n, chunks_n = ingest_policy_corpus(loader_role_engine, POLICY_CORPUS_V1)
    assert docs_n == 4 and chunks_n == 10

    # 2. Get the chunk_id of Rapid movement of funds chunk 0
    with app_role_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT c.chunk_id FROM document_chunks c "
                "JOIN documents d ON c.document_id = d.document_id "
                "WHERE d.title = :title AND c.chunk_index = 0"
            ),
            {"title": DOC_RAPID_FUNDS_TITLE},
        ).fetchone()
        assert row is not None
        chunk_id = row.chunk_id

    # 3. Setup customer, transaction, case, and analyst user
    customer, transaction = setup_customer_and_transaction(superuser_engine)
    user = _seed_user(superuser_engine, "analyst")
    try:
        case = setup_case(
            superuser_engine, setup_alert(superuser_engine, customer, transaction)
        )
        with superuser_engine.begin() as conn:
            conn.execute(
                text("UPDATE cases SET assigned_analyst_id=:u WHERE case_id=:c"),
                {"u": user, "c": case},
            )
        inv_run = create_investigation_run(app_role_engine, case).investigation_run_id
        agent = setup_agent_run(superuser_engine, inv_run)

        # Record transaction evidence
        ev_tx = record_evidence(
            app_role_engine,
            inv_run,
            "alerted_transaction",
            "transactions",
            transaction,
            agent,
        )
        # Record policy chunk evidence
        ev_policy = record_evidence(
            app_role_engine,
            inv_run,
            EVIDENCE_TYPE_POLICY_CHUNK,
            "document_chunks",
            chunk_id,
            agent,
        )

        # Record findings
        record_finding(
            app_role_engine,
            inv_run,
            "Recorded amount is INR 100.00.",
            None,
            "Purpose is unknown.",
            [ev_tx.evidence_id],
            "LOW",
        )
        record_finding(
            app_role_engine,
            inv_run,
            "Policy citation finding.",
            None,
            None,
            [ev_policy.evidence_id],
            "LOW",
        )

        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE investigation_runs SET status='COMPLETE' "
                    "WHERE investigation_run_id=:r"
                ),
                {"r": inv_run},
            )
        token = issue_token(superuser_engine, user)

        yield case, inv_run, ev_policy.evidence_id, token.plaintext_token
    finally:
        _cleanup_seeded_data(superuser_engine, customer)
        _cleanup_user(superuser_engine, user)
        with superuser_engine.begin() as conn:
            conn.execute(text("TRUNCATE document_chunks, documents CASCADE"))


def test_load_package_live_postgres_integration(app_role_engine, policy_db_seeded):
    case, run, policy_ev_id, token = policy_db_seeded

    # Load package via authenticated read-only REPEATABLE READ snapshot
    package = load_package(app_role_engine, token, case, run)

    # Verify policy chunk was retrieved from DB, verified against registry, and included
    policy_passages = [p for p in package.passages if p.passage_id.startswith("policy:")]
    assert len(policy_passages) == 1
    p = policy_passages[0]
    assert p.passage_id == f"policy:{policy_ev_id}"
    assert p.text == CHUNK_RAPID_FUNDS_0_TEXT
    assert p.kind == "observed_fact"
    assert p.confidence == "RECORDED"

    # Verify policy provenance was cryptographically bound into package_hash
    assert package.policy_provenance is not None
    assert package.policy_provenance["registry_version"] == "meridian.policy-registry.v1"
    assert len(package.policy_provenance["chunks"]) == 1
    assert package.policy_provenance["chunks"][0]["evidence_id"] == str(policy_ev_id)

    # Verify draft generation over verified package
    draft_result = asyncio.run(generate_draft(package, MockProvider()))
    assert draft_result.status == "DRAFT"
    claim_texts = [c.text for c in draft_result.draft.summary]
    assert CHUNK_RAPID_FUNDS_0_TEXT in claim_texts
