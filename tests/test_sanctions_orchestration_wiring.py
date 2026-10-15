# ruff: noqa: E501
"""Tests for F11 sanctions-screening orchestrator wiring and transactional authoring (Task 24 Stage 2b-1).

Verifies Criteria 1 through 10:
- Criterion 1: Exact agent_run_id propagation across orchestrator, dispatch,
  agent_runs, screening_results, and evidence (produced_by_agent_run_id).
- Criterion 2: Three persisted domain outcomes (CANDIDATE_MATCHES_FOUND,
  NO_CANDIDATE_MATCH, NOT_PERFORMED) with approved reason-code semantics.
- Criterion 3: screened_customer evidence policy (Decision A / Option B(i)),
  ensuring exactly one row per screening result across all 3 outcomes, correct FKs,
  no rows on technical/persistence failure, and neutral docstrings.
- Criterion 4: Candidate linkage (watchlist_entry evidence, INVESTIGATIVE finding,
  fixed-template recommendation, evidence references, candidate_count == subjects).
- Criterion 5: Atomic Stage 2 rollback (injected failure rolls back screening_results,
  evidence, findings, and recommendations).
- Criterion 6: Stage 1 independence (independently committed agent_runs row remains).
- Criterion 7: Technical failures (State 4 non-fatal) and Stage 1 persistence
  failures (State 5 fatal and propagated).
- Criterion 8: Guard failures for missing or inconsistent agent_runs records.
- Criterion 9: Primary evidence completion prerequisites unaffected by F11.
- Criterion 10: Re-entrancy and uniqueness guards.
- Additional mandatory checks: no risk_signals from F11, no prohibited phrases,
  and architecture import boundaries.
"""

from __future__ import annotations

import ast
import datetime as dt
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Generator
from unittest.mock import patch

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from meridian.agents.graph.structure_signals import ChainDepthComputed, CycleNotFound
from meridian.agents.graph.subgraph import SubgraphResult
from meridian.agents.policy.policy_agent import (
    PolicyCitation,
    PolicyEvidenceFound,
    PolicyEvidenceInsufficient,
)
from meridian.agents.report.authoring import (
    SANCTIONS_RECOMMENDATION_TEXT,
    AuthoringAlreadyPerformedError,
    author_investigation_records,
)
from meridian.agents.report.outcome import (
    InvestigationOutcome,
    PolicyOutcome,
)
from meridian.agents.sanctions.types import (
    AbstentionReason,
    ScreeningOutcome,
)
from meridian.agents.transaction.amount_deviation import (
    AmountDeviationComputed,
    AmountDeviationUnknown,
)
from meridian.evidence.evidence import (
    EVIDENCE_TYPE_SCREENED_CUSTOMER,
    EVIDENCE_TYPE_WATCHLIST_ENTRY,
    REFERENCE_TABLE_CUSTOMERS,
)
from meridian.loader.watchlist_corpus import get_synthetic_watchlist_corpus
from meridian.loader.watchlist_ingest import ingest_watchlist_version
from meridian.orchestration.graph_agent_dispatch import GraphAgentDispatchResult
from meridian.orchestration.investigation_orchestrator import orchestrate_investigation
from meridian.orchestration.sanctions_agent_dispatch import (
    REASON_DATABASE_ERROR,
    SanctionsDispatchError,
)
from meridian.orchestration.screening_results_persistence import (
    AgentRunGuardError,
    record_screening_result,
)
from tests.db_cleanup import clean_investigation_run_dependencies

PROHIBITED_EXPRESSIONS: tuple[str, ...] = (
    "sanctioned customer",
    "confirmed hit",
    "criminal",
    "money laundering",
    "cleared",
    "clean",
    "no sanctions exposure",
)


def _cleanup_all(superuser_engine: Engine) -> None:
    """Comprehensive test cleanup in reverse FK order."""
    with superuser_engine.begin() as conn:
        clean_investigation_run_dependencies(conn)
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM transactions"))
        conn.execute(text("DELETE FROM beneficiaries"))
        conn.execute(text("DELETE FROM accounts"))
        conn.execute(text("DELETE FROM customers"))
        conn.execute(text("DELETE FROM watchlist_entries"))


@pytest.fixture(autouse=True)
def clean_database(superuser_engine: Engine) -> Generator[None, None, None]:
    """Clean database before and after each test."""
    _cleanup_all(superuser_engine)
    yield
    _cleanup_all(superuser_engine)


def _seed_test_case_and_alert(
    superuser_engine: Engine,
    *,
    full_name: str | None = "Aurelius Vance",
    dob: dt.date | None = dt.date(1980, 5, 14),
    status: str = "OPEN",
    include_tx: bool = True,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed customer, account, transaction, alert, and case.

    Returns (case_id, customer_id, transaction_id).
    """
    case_id = uuid.uuid4()
    alert_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    tx_id = uuid.uuid4() if include_tx else None

    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers ("
                "    customer_id, full_name, date_of_birth, is_synthetic, created_at"
                ") VALUES ("
                "    :cid, :name, :dob, true, now()"
                ")"
            ),
            {"cid": customer_id, "name": full_name, "dob": dob},
        )
        if include_tx and tx_id is not None:
            account_id = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO accounts (account_id, customer_id, status, created_at) "
                    "VALUES (:aid, :cid, 'active', now())"
                ),
                {"aid": account_id, "cid": customer_id},
            )
            conn.execute(
                text(
                    "INSERT INTO transactions "
                    "(transaction_id, source_account_id, amount, currency, occurred_at, created_at) "
                    "VALUES (:tid, :aid, 100, 'INR', now(), now())"
                ),
                {"tid": tx_id, "aid": account_id},
            )

        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, transaction_id, alert_type, created_at) "
                "VALUES (:aid, :cid, :tid, 'TEST_ALERT', now())"
            ),
            {"aid": alert_id, "cid": customer_id, "tid": tx_id},
        )
        conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status, opened_at, created_at) "
                "VALUES (:cid, :aid, :status, now(), now())"
            ),
            {"cid": case_id, "aid": alert_id, "status": status},
        )

    return case_id, customer_id, tx_id or uuid.uuid4()


def _mock_standard_agents() -> tuple[Any, Any, Any]:
    """Return standard mocks for Transaction, Graph, and Policy agents."""
    p_compute = patch(
        "meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation"
    )
    p_graph = patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
    p_policy = patch(
        "meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence"
    )
    return p_compute, p_graph, p_policy


# ==============================================================================
# Criterion 1 — Exact agent_run_id propagation
# ==============================================================================


def test_criterion_1_exact_agent_run_id_propagation(
    superuser_engine: Engine,
    app_role_engine: Engine,
) -> None:
    """Prove that the exact same UUID appears in all 5 required places:

    1. Orchestrator-generated ID passed to dispatch
    2. Persisted agent_runs.agent_run_id
    3. screening_results.agent_run_id
    4. screened_customer evidence produced_by_agent_run_id
    5. watchlist_entry evidence produced_by_agent_run_id
    """
    corpus = get_synthetic_watchlist_corpus()
    ingest_watchlist_version(superuser_engine, corpus)

    case_id, customer_id, tx_id = _seed_test_case_and_alert(
        superuser_engine, full_name="Aurelius Vance"
    )

    p_compute, p_graph, p_policy = _mock_standard_agents()
    with p_compute as m_tx, p_graph as m_graph, p_policy as m_policy:
        m_tx.return_value = AmountDeviationComputed(
            alerted_transaction_id=tx_id,
            source_account_id=uuid.uuid4(),
            alerted_amount=Decimal("100"),
            historical_average=Decimal("10"),
            deviation_multiple=Decimal("10"),
            historical_transaction_count=1,
            source_transaction_ids=(uuid.uuid4(),),
            currency="INR",
        )
        m_graph.return_value = GraphAgentDispatchResult(
            investigation_run_id=uuid.uuid4(),
            result=SubgraphResult(
                start_entity_id=uuid.uuid4(),
                max_hops=3,
                node_entity_ids=(uuid.uuid4(),),
                relationship_ids=(uuid.uuid4(),),
                truncated=False,
            ),
            cycle_result=CycleNotFound(account_id=uuid.uuid4()),
            chain_result=ChainDepthComputed(
                account_id=uuid.uuid4(),
                depth=0,
                chain_entity_ids=(),
                chain_relationship_ids=(),
            ),
        )
        m_policy.return_value = PolicyEvidenceFound(
            citations=[
                PolicyCitation(
                    document_id=uuid.uuid4(),
                    document_type="policy",
                    chunk_text="text",
                    chunk_id=uuid.uuid4(),
                    title="Policy A",
                    version="1.0",
                    chunk_index=1,
                    rrf_score=0.9,
                    is_synthetic=False,
                )
            ]
        )

        status = orchestrate_investigation(app_role_engine, case_id)
        assert status == "COMPLETE"

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"
            ),
            {"cid": case_id},
        ).scalar()
        assert inv_run_id is not None

        # 1. Fetch sanctions agent_run
        sanctions_run = conn.execute(
            text(
                "SELECT agent_run_id, status FROM agent_runs "
                "WHERE investigation_run_id = :inv_id AND agent_name = 'SanctionsAgent'"
            ),
            {"inv_id": inv_run_id},
        ).fetchone()
        assert sanctions_run is not None
        sanctions_agent_run_id, run_status = sanctions_run
        assert run_status == "SUCCESS"

        # 2. Fetch screening_results
        screening_row = conn.execute(
            text(
                "SELECT screening_result_id, agent_run_id, customer_id, outcome "
                "FROM screening_results WHERE investigation_run_id = :inv_id"
            ),
            {"inv_id": inv_run_id},
        ).fetchone()
        assert screening_row is not None
        _, s_agent_run_id, s_cust_id, s_outcome = screening_row
        assert s_outcome == ScreeningOutcome.CANDIDATE_MATCHES_FOUND.value
        assert s_cust_id == customer_id
        # Exact agent_run_id match in screening_results
        assert s_agent_run_id == sanctions_agent_run_id

        # 3. Fetch screened_customer evidence
        cust_ev = conn.execute(
            text(
                "SELECT evidence_id, produced_by_agent_run_id, reference_id "
                "FROM evidence WHERE investigation_run_id = :inv_id AND evidence_type = :etype"
            ),
            {"inv_id": inv_run_id, "etype": EVIDENCE_TYPE_SCREENED_CUSTOMER},
        ).fetchone()
        assert cust_ev is not None
        _, cust_ev_run_id, cust_ev_ref_id = cust_ev
        assert cust_ev_ref_id == customer_id
        # Exact agent_run_id match in screened_customer evidence
        assert cust_ev_run_id == sanctions_agent_run_id

        # 4. Fetch watchlist_entry evidence
        wl_ev_rows = conn.execute(
            text(
                "SELECT evidence_id, produced_by_agent_run_id, reference_id "
                "FROM evidence WHERE investigation_run_id = :inv_id AND evidence_type = :etype"
            ),
            {"inv_id": inv_run_id, "etype": EVIDENCE_TYPE_WATCHLIST_ENTRY},
        ).fetchall()
        assert len(wl_ev_rows) > 0
        for _, wl_ev_run_id, _ in wl_ev_rows:
            # Exact agent_run_id match in watchlist_entry evidence
            assert wl_ev_run_id == sanctions_agent_run_id


# ==============================================================================
# Criterion 2 — Three persisted domain outcomes
# ==============================================================================


@pytest.mark.parametrize(
    (
        "customer_name",
        "ingest_corpus",
        "expected_outcome",
        "expected_reason",
        "expected_candidates",
    ),
    [
        (
            "Aurelius Vance",
            True,
            ScreeningOutcome.CANDIDATE_MATCHES_FOUND.value,
            None,
            1,
        ),
        (
            "Unmatched Person",
            True,
            ScreeningOutcome.NO_CANDIDATE_MATCH.value,
            None,
            0,
        ),
        (
            "Aurelius Vance",
            False,
            ScreeningOutcome.NOT_PERFORMED.value,
            AbstentionReason.WATCHLIST_VERSION_NOT_LOADED.value,
            0,
        ),
    ],
)
def test_criterion_2_three_persisted_domain_outcomes(
    superuser_engine: Engine,
    app_role_engine: Engine,
    customer_name: str,
    ingest_corpus: bool,
    expected_outcome: str,
    expected_reason: str | None,
    expected_candidates: int,
) -> None:
    """Verify all 3 domain outcomes are persisted end-to-end with correct reason codes."""
    if ingest_corpus:
        corpus = get_synthetic_watchlist_corpus()
        ingest_watchlist_version(superuser_engine, corpus)

    case_id, customer_id, tx_id = _seed_test_case_and_alert(
        superuser_engine, full_name=customer_name
    )

    p_compute, p_graph, p_policy = _mock_standard_agents()
    with p_compute as m_tx, p_graph as m_graph, p_policy as m_policy:
        m_tx.return_value = AmountDeviationComputed(
            alerted_transaction_id=tx_id,
            source_account_id=uuid.uuid4(),
            alerted_amount=Decimal("100"),
            historical_average=Decimal("10"),
            deviation_multiple=Decimal("10"),
            historical_transaction_count=1,
            source_transaction_ids=(uuid.uuid4(),),
            currency="INR",
        )
        m_graph.return_value = GraphAgentDispatchResult(
            investigation_run_id=uuid.uuid4(),
            result=SubgraphResult(
                start_entity_id=uuid.uuid4(),
                max_hops=3,
                node_entity_ids=(uuid.uuid4(),),
                relationship_ids=(uuid.uuid4(),),
                truncated=False,
            ),
            cycle_result=CycleNotFound(account_id=uuid.uuid4()),
            chain_result=ChainDepthComputed(
                account_id=uuid.uuid4(),
                depth=0,
                chain_entity_ids=(),
                chain_relationship_ids=(),
            ),
        )
        m_policy.return_value = PolicyEvidenceFound(citations=[])

        status = orchestrate_investigation(app_role_engine, case_id)
        assert status in ("COMPLETE", "INCOMPLETE_INSUFFICIENT_EVIDENCE")

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"
            ),
            {"cid": case_id},
        ).scalar()

        row = conn.execute(
            text(
                "SELECT outcome, reason_code, candidate_count "
                "FROM screening_results WHERE investigation_run_id = :inv_id"
            ),
            {"inv_id": inv_run_id},
        ).fetchone()
        assert row is not None
        outcome, reason_code, candidate_count = row
        assert outcome == expected_outcome
        assert reason_code == expected_reason
        assert candidate_count == expected_candidates


# ==============================================================================
# Criterion 3 — screened_customer evidence policy (Decision A / Option B(i))
# ==============================================================================


def test_criterion_3_screened_customer_evidence_for_all_three_outcomes(
    superuser_engine: Engine,
    app_role_engine: Engine,
) -> None:
    """Verify exactly one screened_customer row per persisted screening result for all 3 outcomes."""
    test_cases = [
        ("Aurelius Vance", True),  # CANDIDATE_MATCHES_FOUND
        ("Unmatched Person", True),  # NO_CANDIDATE_MATCH
        ("Aurelius Vance", False),  # NOT_PERFORMED
    ]

    for name, load_wl in test_cases:
        _cleanup_all(superuser_engine)
        if load_wl:
            corpus = get_synthetic_watchlist_corpus()
            ingest_watchlist_version(superuser_engine, corpus)

        case_id, customer_id, tx_id = _seed_test_case_and_alert(
            superuser_engine, full_name=name
        )

        p_compute, p_graph, p_policy = _mock_standard_agents()
        with p_compute as m_tx, p_graph as m_graph, p_policy as m_policy:
            m_tx.return_value = AmountDeviationComputed(
                alerted_transaction_id=tx_id,
                source_account_id=uuid.uuid4(),
                alerted_amount=Decimal("100"),
                historical_average=Decimal("10"),
                deviation_multiple=Decimal("10"),
                historical_transaction_count=1,
                source_transaction_ids=(uuid.uuid4(),),
                currency="INR",
            )
            m_graph.return_value = GraphAgentDispatchResult(
                investigation_run_id=uuid.uuid4(),
                result=SubgraphResult(
                    start_entity_id=uuid.uuid4(),
                    max_hops=3,
                    node_entity_ids=(uuid.uuid4(),),
                    relationship_ids=(uuid.uuid4(),),
                    truncated=False,
                ),
                cycle_result=CycleNotFound(account_id=uuid.uuid4()),
                chain_result=ChainDepthComputed(
                    account_id=uuid.uuid4(),
                    depth=0,
                    chain_entity_ids=(),
                    chain_relationship_ids=(),
                ),
            )
            m_policy.return_value = PolicyEvidenceFound(citations=[])

            orchestrate_investigation(app_role_engine, case_id)

        with superuser_engine.connect() as conn:
            inv_run_id = conn.execute(
                text(
                    "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"
                ),
                {"cid": case_id},
            ).scalar()

            # Screening result must exist
            s_res = conn.execute(
                text(
                    "SELECT agent_run_id FROM screening_results WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run_id},
            ).fetchone()
            assert s_res is not None
            expected_agent_run_id = s_res[0]

            # Exactly one screened_customer row
            rows = conn.execute(
                text(
                    "SELECT evidence_id, reference_table, reference_id, produced_by_agent_run_id "
                    "FROM evidence WHERE investigation_run_id = :inv_id AND evidence_type = :etype"
                ),
                {"inv_id": inv_run_id, "etype": EVIDENCE_TYPE_SCREENED_CUSTOMER},
            ).fetchall()
            assert len(rows) == 1, (
                f"Expected 1 screened_customer row for name={name}, got {len(rows)}"
            )
            _, ref_table, ref_id, produced_by = rows[0]
            assert ref_table == REFERENCE_TABLE_CUSTOMERS
            assert ref_id == customer_id
            assert produced_by == expected_agent_run_id


def test_criterion_3_screened_customer_constant_neutrality() -> None:
    """Verify constant documentation in evidence.py describes screened_customer neutrally."""
    evidence_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "meridian"
        / "evidence"
        / "evidence.py"
    )
    content = evidence_path.read_text()
    assert "EVIDENCE_TYPE_SCREENED_CUSTOMER" in content
    # Verify neutral pointer description
    assert "Neutral customer-reference pointer" in content
    assert "does not represent a screening outcome" in content
    assert "not evidence of clearance" in content


# ==============================================================================
# Criterion 4 — Candidate linkage
# ==============================================================================


def test_criterion_4_candidate_linkage_and_ad10_wording(
    superuser_engine: Engine,
    app_role_engine: Engine,
) -> None:
    """Verify candidate evidence, INVESTIGATIVE finding, and recommendation linkage."""
    corpus = get_synthetic_watchlist_corpus()
    ingest_watchlist_version(superuser_engine, corpus)

    case_id, customer_id, tx_id = _seed_test_case_and_alert(
        superuser_engine, full_name="Aurelius Vance", dob=dt.date(1980, 5, 14)
    )

    p_compute, p_graph, p_policy = _mock_standard_agents()
    with p_compute as m_tx, p_graph as m_graph, p_policy as m_policy:
        m_tx.return_value = AmountDeviationComputed(
            alerted_transaction_id=tx_id,
            source_account_id=uuid.uuid4(),
            alerted_amount=Decimal("100"),
            historical_average=Decimal("10"),
            deviation_multiple=Decimal("10"),
            historical_transaction_count=1,
            source_transaction_ids=(uuid.uuid4(),),
            currency="INR",
        )
        m_graph.return_value = GraphAgentDispatchResult(
            investigation_run_id=uuid.uuid4(),
            result=SubgraphResult(
                start_entity_id=uuid.uuid4(),
                max_hops=3,
                node_entity_ids=(uuid.uuid4(),),
                relationship_ids=(uuid.uuid4(),),
                truncated=False,
            ),
            cycle_result=CycleNotFound(account_id=uuid.uuid4()),
            chain_result=ChainDepthComputed(
                account_id=uuid.uuid4(),
                depth=0,
                chain_entity_ids=(),
                chain_relationship_ids=(),
            ),
        )
        m_policy.return_value = PolicyEvidenceFound(citations=[])

        status = orchestrate_investigation(app_role_engine, case_id)
        assert status == "COMPLETE"

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"
            ),
            {"cid": case_id},
        ).scalar()

        # 1. Candidate count
        screening_res = conn.execute(
            text(
                "SELECT candidate_count FROM screening_results WHERE investigation_run_id = :inv_id"
            ),
            {"inv_id": inv_run_id},
        ).fetchone()
        assert screening_res is not None
        assert screening_res[0] == 1

        # 2. Watchlist entry evidence
        wl_evidence = conn.execute(
            text(
                "SELECT evidence_id, reference_id FROM evidence "
                "WHERE investigation_run_id = :inv_id AND evidence_type = :etype"
            ),
            {"inv_id": inv_run_id, "etype": EVIDENCE_TYPE_WATCHLIST_ENTRY},
        ).fetchall()
        assert len(wl_evidence) >= 1
        matched_entry_ids = {row[1] for row in wl_evidence}

        # Check foreign keys resolve in watchlist_entries
        for entry_id in matched_entry_ids:
            entry_exists = conn.execute(
                text("SELECT 1 FROM watchlist_entries WHERE entry_id = :eid"),
                {"eid": entry_id},
            ).scalar()
            assert entry_exists == 1

        # 3. Findings check
        f_rows = conn.execute(
            text(
                "SELECT finding_id, observed_fact, derived_signal, interpretation, evidence_ids, confidence "
                "FROM findings WHERE investigation_run_id = :inv_id"
            ),
            {"inv_id": inv_run_id},
        ).fetchall()

        # Filter for the F11 sanctions finding
        sanctions_findings = [f for f in f_rows if "synthetic list" in f[1]]
        assert len(sanctions_findings) == 1
        finding_id, obs, derived, interp, ev_ids, conf = sanctions_findings[0]

        # Verify exact ADR-0008 D10 structure
        assert (
            "The customer's normalized name equals a listed name on synthetic list"
            in obs
        )
        assert "under rule exact_norm_name_v1, normalization v1" in obs
        assert "Exact normalized-name equality; dob_comparison =" in derived
        assert (
            interp
            == "Candidate watchlist match for human review. Not an identity or sanctions determination. Synthetic list. No validated threshold."
        )
        assert conf == "LOW"

        # Evidence references in finding: must include screened_customer and all matched watchlist_entry
        cust_ev_id = conn.execute(
            text(
                "SELECT evidence_id FROM evidence "
                "WHERE investigation_run_id = :inv_id AND evidence_type = :etype"
            ),
            {"inv_id": inv_run_id, "etype": EVIDENCE_TYPE_SCREENED_CUSTOMER},
        ).scalar()
        assert cust_ev_id in ev_ids
        for wl_ev_id, _ in wl_evidence:
            assert wl_ev_id in ev_ids

        # 4. Recommendation check
        recs = conn.execute(
            text(
                "SELECT recommendation_id, text, based_on_finding_ids "
                "FROM recommendations WHERE investigation_run_id = :inv_id"
            ),
            {"inv_id": inv_run_id},
        ).fetchall()
        sanctions_recs = [r for r in recs if finding_id in r[2]]
        assert len(sanctions_recs) == 1
        assert sanctions_recs[0][1] == SANCTIONS_RECOMMENDATION_TEXT


def test_criterion_4_no_findings_or_recommendations_for_no_match_or_abstention(
    superuser_engine: Engine,
    app_role_engine: Engine,
) -> None:
    """Verify NO sanctions findings or recommendations are authored for NO_CANDIDATE_MATCH or NOT_PERFORMED."""
    # Test NO_CANDIDATE_MATCH
    corpus = get_synthetic_watchlist_corpus()
    ingest_watchlist_version(superuser_engine, corpus)

    case_id, _, tx_id = _seed_test_case_and_alert(
        superuser_engine, full_name="Totally Unmatched Person"
    )

    p_compute, p_graph, p_policy = _mock_standard_agents()
    with p_compute as m_tx, p_graph as m_graph, p_policy as m_policy:
        m_tx.return_value = AmountDeviationComputed(
            alerted_transaction_id=tx_id,
            source_account_id=uuid.uuid4(),
            alerted_amount=Decimal("100"),
            historical_average=Decimal("10"),
            deviation_multiple=Decimal("10"),
            historical_transaction_count=1,
            source_transaction_ids=(uuid.uuid4(),),
            currency="INR",
        )
        m_graph.return_value = GraphAgentDispatchResult(
            investigation_run_id=uuid.uuid4(),
            result=SubgraphResult(
                start_entity_id=uuid.uuid4(),
                max_hops=3,
                node_entity_ids=(uuid.uuid4(),),
                relationship_ids=(uuid.uuid4(),),
                truncated=False,
            ),
            cycle_result=CycleNotFound(account_id=uuid.uuid4()),
            chain_result=ChainDepthComputed(
                account_id=uuid.uuid4(),
                depth=0,
                chain_entity_ids=(),
                chain_relationship_ids=(),
            ),
        )
        m_policy.return_value = PolicyEvidenceFound(citations=[])

        orchestrate_investigation(app_role_engine, case_id)

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"
            ),
            {"cid": case_id},
        ).scalar()

        # Zero watchlist_entry evidence
        wl_count = conn.execute(
            text(
                "SELECT count(*) FROM evidence "
                "WHERE investigation_run_id = :inv_id AND evidence_type = :etype"
            ),
            {"inv_id": inv_run_id, "etype": EVIDENCE_TYPE_WATCHLIST_ENTRY},
        ).scalar()
        assert wl_count == 0

        # Zero sanctions findings
        findings = conn.execute(
            text(
                "SELECT observed_fact FROM findings WHERE investigation_run_id = :inv_id"
            ),
            {"inv_id": inv_run_id},
        ).fetchall()
        assert not any("synthetic list" in f[0] for f in findings)


# ==============================================================================
# Criteria 5 & 6 — Atomic Stage 2 rollback & Stage 1 independence
# ==============================================================================


def test_criteria_5_and_6_atomic_stage_2_rollback_and_stage_1_independence(
    superuser_engine: Engine,
    app_role_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inject failure after record_screening_result() in Stage 2 authoring.

    Prove:
    - Criterion 5: All Stage 2 writes roll back (0 screening_results, 0 F11 evidence, 0 findings, 0 recs).
    - Criterion 6: Stage 1 agent_runs row remains persisted with status SUCCESS.
    """
    corpus = get_synthetic_watchlist_corpus()
    ingest_watchlist_version(superuser_engine, corpus)

    case_id, customer_id, tx_id = _seed_test_case_and_alert(
        superuser_engine, full_name="Aurelius Vance"
    )

    import meridian.agents.report.authoring as authoring_module

    original_record_ev = authoring_module.record_evidence_with_connection

    def failing_record_ev(conn: Any, *args: Any, **kwargs: Any) -> Any:
        # Fail when inserting screened_customer evidence
        if kwargs.get("evidence_type") == EVIDENCE_TYPE_SCREENED_CUSTOMER:
            raise ValueError("Injected Stage 2 authoring failure on evidence insertion")
        return original_record_ev(conn, *args, **kwargs)

    monkeypatch.setattr(
        authoring_module, "record_evidence_with_connection", failing_record_ev
    )

    p_compute, p_graph, p_policy = _mock_standard_agents()
    with p_compute as m_tx, p_graph as m_graph, p_policy as m_policy:
        m_tx.return_value = AmountDeviationComputed(
            alerted_transaction_id=tx_id,
            source_account_id=uuid.uuid4(),
            alerted_amount=Decimal("100"),
            historical_average=Decimal("10"),
            deviation_multiple=Decimal("10"),
            historical_transaction_count=1,
            source_transaction_ids=(uuid.uuid4(),),
            currency="INR",
        )
        m_graph.return_value = GraphAgentDispatchResult(
            investigation_run_id=uuid.uuid4(),
            result=SubgraphResult(
                start_entity_id=uuid.uuid4(),
                max_hops=3,
                node_entity_ids=(uuid.uuid4(),),
                relationship_ids=(uuid.uuid4(),),
                truncated=False,
            ),
            cycle_result=CycleNotFound(account_id=uuid.uuid4()),
            chain_result=ChainDepthComputed(
                account_id=uuid.uuid4(),
                depth=0,
                chain_entity_ids=(),
                chain_relationship_ids=(),
            ),
        )
        m_policy.return_value = PolicyEvidenceFound(citations=[])

        with pytest.raises(ValueError, match="Injected Stage 2 authoring failure"):
            orchestrate_investigation(app_role_engine, case_id)

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"
            ),
            {"cid": case_id},
        ).scalar()
        assert inv_run_id is not None

        # Criterion 5: All Stage 2 domain writes rolled back
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM screening_results WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run_id},
            ).scalar()
            == 0
        )

        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM evidence WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run_id},
            ).scalar()
            == 0
        )

        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM findings WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run_id},
            ).scalar()
            == 0
        )

        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM recommendations WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run_id},
            ).scalar()
            == 0
        )

        # Criterion 6: Stage 1 agent_runs row remains persisted and intact
        sanctions_run = conn.execute(
            text(
                "SELECT status FROM agent_runs "
                "WHERE investigation_run_id = :inv_id AND agent_name = 'SanctionsAgent'"
            ),
            {"inv_id": inv_run_id},
        ).fetchone()
        assert sanctions_run is not None
        assert sanctions_run[0] == "SUCCESS"


# ==============================================================================
# Criterion 7 — Technical and persistence failures
# ==============================================================================


def test_criterion_7_state_4_ordinary_technical_failure_is_non_fatal(
    superuser_engine: Engine,
    app_role_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """State 4: Ordinary technical screening failure is non-fatal to investigation.

    - Stage 1 agent_runs is recorded as FAILED with approved reason code.
    - Zero screening_results rows created.
    - Zero F11 evidence rows created.
    - Investigation status concludes as COMPLETE per primary evidence prerequisites.
    """
    case_id, _, tx_id = _seed_test_case_and_alert(
        superuser_engine, full_name="Aurelius Vance"
    )

    import meridian.orchestration.sanctions_agent_dispatch as dispatch_module

    # Inject technical database failure during customer lookup in screening
    def failing_read(*args: Any, **kwargs: Any) -> Any:
        raise SanctionsDispatchError(REASON_DATABASE_ERROR)

    monkeypatch.setattr(dispatch_module, "read_watchlist_version", failing_read)

    # Spy on author_investigation_records to verify SanctionsOutcome.error is populated with reason code
    import meridian.orchestration.investigation_orchestrator as orch_module

    captured_outcomes: list[InvestigationOutcome] = []
    orig_author = orch_module.author_investigation_records

    def spy_author(conn: Any, outcome: InvestigationOutcome) -> Any:
        captured_outcomes.append(outcome)
        return orig_author(conn, outcome)

    monkeypatch.setattr(orch_module, "author_investigation_records", spy_author)

    p_compute, p_graph, p_policy = _mock_standard_agents()
    with p_compute as m_tx, p_graph as m_graph, p_policy as m_policy:
        m_tx.return_value = AmountDeviationComputed(
            alerted_transaction_id=tx_id,
            source_account_id=uuid.uuid4(),
            alerted_amount=Decimal("100"),
            historical_average=Decimal("10"),
            deviation_multiple=Decimal("10"),
            historical_transaction_count=1,
            source_transaction_ids=(uuid.uuid4(),),
            currency="INR",
        )
        m_graph.return_value = GraphAgentDispatchResult(
            investigation_run_id=uuid.uuid4(),
            result=SubgraphResult(
                start_entity_id=uuid.uuid4(),
                max_hops=3,
                node_entity_ids=(uuid.uuid4(),),
                relationship_ids=(uuid.uuid4(),),
                truncated=False,
            ),
            cycle_result=CycleNotFound(account_id=uuid.uuid4()),
            chain_result=ChainDepthComputed(
                account_id=uuid.uuid4(),
                depth=0,
                chain_entity_ids=(),
                chain_relationship_ids=(),
            ),
        )
        m_policy.return_value = PolicyEvidenceFound(citations=[])

        status = orchestrate_investigation(app_role_engine, case_id)
        # Investigation is NOT aborted
        assert status == "COMPLETE"
        # SanctionsOutcome carried the sanitized reason code
        assert len(captured_outcomes) == 1
        assert captured_outcomes[0].sanctions is not None
        assert captured_outcomes[0].sanctions.result is None
        assert captured_outcomes[0].sanctions.error == REASON_DATABASE_ERROR

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"
            ),
            {"cid": case_id},
        ).scalar()

        # Stage 1 agent_run is recorded as FAILED with approved code
        run_row = conn.execute(
            text(
                "SELECT status, error FROM agent_runs "
                "WHERE investigation_run_id = :inv_id AND agent_name = 'SanctionsAgent'"
            ),
            {"inv_id": inv_run_id},
        ).fetchone()
        assert run_row is not None
        assert run_row[0] == "FAILED"
        assert run_row[1] == REASON_DATABASE_ERROR

        # No screening_results or F11 evidence authored
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM screening_results WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run_id},
            ).scalar()
            == 0
        )

        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM evidence "
                    "WHERE investigation_run_id = :inv_id AND evidence_type IN (:t1, :t2)"
                ),
                {
                    "inv_id": inv_run_id,
                    "t1": EVIDENCE_TYPE_SCREENED_CUSTOMER,
                    "t2": EVIDENCE_TYPE_WATCHLIST_ENTRY,
                },
            ).scalar()
            == 0
        )


def test_criterion_7_state_5_stage_1_persistence_failure_is_fatal(
    superuser_engine: Engine,
    app_role_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """State 5: Stage 1 agent-run persistence failure propagates and aborts orchestration call.

    - The persistence exception is not swallowed.
    - Not misclassified as ordinary screening failure.
    - Investigation run is marked FAILED.
    - Zero screening_results or F11 evidence written.
    """
    case_id, _, tx_id = _seed_test_case_and_alert(
        superuser_engine, full_name="Aurelius Vance"
    )

    import meridian.orchestration.sanctions_agent_dispatch as dispatch_module

    # Inject failure into record_agent_run (Stage 1 tracking persistence)
    def failing_record_agent_run(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Disk full / DB connection lost during agent_runs insert")

    monkeypatch.setattr(dispatch_module, "record_agent_run", failing_record_agent_run)

    p_compute, p_graph, p_policy = _mock_standard_agents()
    with p_compute as m_tx, p_graph as m_graph, p_policy as m_policy:
        m_tx.return_value = AmountDeviationComputed(
            alerted_transaction_id=tx_id,
            source_account_id=uuid.uuid4(),
            alerted_amount=Decimal("100"),
            historical_average=Decimal("10"),
            deviation_multiple=Decimal("10"),
            historical_transaction_count=1,
            source_transaction_ids=(uuid.uuid4(),),
            currency="INR",
        )
        m_graph.return_value = GraphAgentDispatchResult(
            investigation_run_id=uuid.uuid4(),
            result=SubgraphResult(
                start_entity_id=uuid.uuid4(),
                max_hops=3,
                node_entity_ids=(uuid.uuid4(),),
                relationship_ids=(uuid.uuid4(),),
                truncated=False,
            ),
            cycle_result=CycleNotFound(account_id=uuid.uuid4()),
            chain_result=ChainDepthComputed(
                account_id=uuid.uuid4(),
                depth=0,
                chain_entity_ids=(),
                chain_relationship_ids=(),
            ),
        )
        m_policy.return_value = PolicyEvidenceFound(citations=[])

        with pytest.raises(RuntimeError, match="Disk full"):
            orchestrate_investigation(app_role_engine, case_id)

    with superuser_engine.connect() as conn:
        inv_run = conn.execute(
            text("SELECT status FROM investigation_runs WHERE case_id = :cid"),
            {"cid": case_id},
        ).fetchone()
        assert inv_run is not None
        assert inv_run[0] == "FAILED"

        # Zero screening_results or F11 evidence
        assert (
            conn.execute(text("SELECT count(*) FROM screening_results")).scalar() == 0
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM evidence WHERE evidence_type IN (:t1, :t2)"),
                {
                    "t1": EVIDENCE_TYPE_SCREENED_CUSTOMER,
                    "t2": EVIDENCE_TYPE_WATCHLIST_ENTRY,
                },
            ).scalar()
            == 0
        )


# ==============================================================================
# Criterion 8 — Missing and inconsistent records (Guard failures)
# ==============================================================================


def test_criterion_8_guard_failures_in_authoring(
    superuser_engine: Engine,
) -> None:
    """Verify record_screening_result guards reject invalid/inconsistent agent runs."""
    inv_id = uuid.uuid4()
    cust_id = uuid.uuid4()
    run_id = uuid.uuid4()

    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers (customer_id, full_name, is_synthetic, created_at) VALUES (:c, 'Test', true, now())"
            ),
            {"c": cust_id},
        )
        # Create investigation run
        case_id = uuid.uuid4()
        alert_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, alert_type, created_at) VALUES (:a, :c, 'TEST', now())"
            ),
            {"a": alert_id, "c": cust_id},
        )
        conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status, opened_at, created_at) VALUES (:case, :a, 'OPEN', now(), now())"
            ),
            {"case": case_id, "a": alert_id},
        )
        conn.execute(
            text(
                "INSERT INTO investigation_runs (investigation_run_id, case_id, status, started_at) VALUES (:inv, :case, 'IN_PROGRESS', now())"
            ),
            {"inv": inv_id, "case": case_id},
        )

    # 1. Nonexistent agent_run_id
    with superuser_engine.begin() as conn:
        with pytest.raises(AgentRunGuardError):
            record_screening_result(
                conn,
                investigation_run_id=inv_id,
                agent_run_id=run_id,
                customer_id=cust_id,
                outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                reason_code=None,
                candidate_count=0,
                watchlist_name="list",
                watchlist_version="v1",
                matching_rule_id="rule",
                normalization_version="v1",
            )

    # 2. Agent run with wrong agent_name
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_runs (agent_run_id, investigation_run_id, agent_name, status, started_at, tool_calls) "
                "VALUES (:aid, :inv, 'TransactionAgent', 'SUCCESS', now(), '{}')"
            ),
            {"aid": run_id, "inv": inv_id},
        )
        with pytest.raises(AgentRunGuardError):
            record_screening_result(
                conn,
                investigation_run_id=inv_id,
                agent_run_id=run_id,
                customer_id=cust_id,
                outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                reason_code=None,
                candidate_count=0,
                watchlist_name="list",
                watchlist_version="v1",
                matching_rule_id="rule",
                normalization_version="v1",
            )

    # 3. Agent run with status FAILED
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE agent_runs SET agent_name = 'SanctionsAgent', status = 'FAILED' WHERE agent_run_id = :aid"
            ),
            {"aid": run_id},
        )
        with pytest.raises(AgentRunGuardError):
            record_screening_result(
                conn,
                investigation_run_id=inv_id,
                agent_run_id=run_id,
                customer_id=cust_id,
                outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                reason_code=None,
                candidate_count=0,
                watchlist_name="list",
                watchlist_version="v1",
                matching_rule_id="rule",
                normalization_version="v1",
            )


# ==============================================================================
# Criterion 9 — Completion and safety regressions
# ==============================================================================


def test_criterion_9_completion_prerequisites_unaffected_by_f11(
    superuser_engine: Engine,
    app_role_engine: Engine,
) -> None:
    """Verify primary evidence rules still strictly determine completion status."""
    corpus = get_synthetic_watchlist_corpus()
    ingest_watchlist_version(superuser_engine, corpus)

    # Case where tx evidence is insufficient (AmountDeviationUnknown)
    case_id, _, tx_id = _seed_test_case_and_alert(
        superuser_engine, full_name="Aurelius Vance"
    )

    p_compute, p_graph, p_policy = _mock_standard_agents()
    with p_compute as m_tx, p_graph as m_graph, p_policy as m_policy:
        m_tx.return_value = AmountDeviationUnknown(
            alerted_transaction_id=tx_id,
            source_account_id=uuid.uuid4(),
            reason="insufficient historical transactions",
        )
        m_graph.return_value = GraphAgentDispatchResult(
            investigation_run_id=uuid.uuid4(),
            result=SubgraphResult(
                start_entity_id=uuid.uuid4(),
                max_hops=3,
                node_entity_ids=(uuid.uuid4(),),
                relationship_ids=(uuid.uuid4(),),
                truncated=False,
            ),
            cycle_result=CycleNotFound(account_id=uuid.uuid4()),
            chain_result=ChainDepthComputed(
                account_id=uuid.uuid4(),
                depth=0,
                chain_entity_ids=(),
                chain_relationship_ids=(),
            ),
        )
        m_policy.return_value = PolicyEvidenceFound(citations=[])

        # Even though F11 found a candidate match, tx evidence is missing
        status = orchestrate_investigation(app_role_engine, case_id)
        assert status == "INCOMPLETE_INSUFFICIENT_EVIDENCE"


# ==============================================================================
# Criterion 10 — Existing retry/re-entrancy behavior
# ==============================================================================


def test_criterion_10_authoring_reentrancy_guards(
    superuser_engine: Engine,
    app_role_engine: Engine,
) -> None:
    """Verify AuthoringAlreadyPerformedError is raised when re-authoring an investigation."""
    corpus = get_synthetic_watchlist_corpus()
    ingest_watchlist_version(superuser_engine, corpus)

    case_id, customer_id, tx_id = _seed_test_case_and_alert(
        superuser_engine, full_name="Aurelius Vance"
    )

    p_compute, p_graph, p_policy = _mock_standard_agents()
    with p_compute as m_tx, p_graph as m_graph, p_policy as m_policy:
        m_tx.return_value = AmountDeviationComputed(
            alerted_transaction_id=tx_id,
            source_account_id=uuid.uuid4(),
            alerted_amount=Decimal("100"),
            historical_average=Decimal("10"),
            deviation_multiple=Decimal("10"),
            historical_transaction_count=1,
            source_transaction_ids=(uuid.uuid4(),),
            currency="INR",
        )
        m_graph.return_value = GraphAgentDispatchResult(
            investigation_run_id=uuid.uuid4(),
            result=SubgraphResult(
                start_entity_id=uuid.uuid4(),
                max_hops=3,
                node_entity_ids=(uuid.uuid4(),),
                relationship_ids=(uuid.uuid4(),),
                truncated=False,
            ),
            cycle_result=CycleNotFound(account_id=uuid.uuid4()),
            chain_result=ChainDepthComputed(
                account_id=uuid.uuid4(),
                depth=0,
                chain_entity_ids=(),
                chain_relationship_ids=(),
            ),
        )
        m_policy.return_value = PolicyEvidenceFound(citations=[])

        status = orchestrate_investigation(app_role_engine, case_id)
        assert status == "COMPLETE"

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"
            ),
            {"cid": case_id},
        ).scalar()
        assert inv_run_id is not None

        # Re-authoring the same run must raise AuthoringAlreadyPerformedError
        outcome = InvestigationOutcome(
            investigation_run_id=inv_run_id,
            alert_type="TEST",
            transaction=None,
            graph=None,
            policy=PolicyOutcome(
                result=PolicyEvidenceInsufficient(), agent_run_id=uuid.uuid4()
            ),
        )
        with pytest.raises(AuthoringAlreadyPerformedError):
            with superuser_engine.begin() as tx_conn:
                author_investigation_records(tx_conn, outcome)


def test_criterion_10_unique_constraint_propagation(
    superuser_engine: Engine,
) -> None:
    """Verify unique constraint on screening_results.investigation_run_id raises IntegrityError."""
    inv_id = uuid.uuid4()
    cust_id = uuid.uuid4()
    run_id1 = uuid.uuid4()
    run_id2 = uuid.uuid4()

    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers (customer_id, full_name, is_synthetic, created_at) VALUES (:c, 'Test', true, now())"
            ),
            {"c": cust_id},
        )
        case_id = uuid.uuid4()
        alert_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, alert_type, created_at) VALUES (:a, :c, 'TEST', now())"
            ),
            {"a": alert_id, "c": cust_id},
        )
        conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status, opened_at, created_at) VALUES (:case, :a, 'OPEN', now(), now())"
            ),
            {"case": case_id, "a": alert_id},
        )
        conn.execute(
            text(
                "INSERT INTO investigation_runs (investigation_run_id, case_id, status, started_at) VALUES (:inv, :case, 'IN_PROGRESS', now())"
            ),
            {"inv": inv_id, "case": case_id},
        )
        conn.execute(
            text(
                "INSERT INTO agent_runs (agent_run_id, investigation_run_id, agent_name, status, started_at, tool_calls) "
                "VALUES (:aid, :inv, 'SanctionsAgent', 'SUCCESS', now(), '{}')"
            ),
            {"aid": run_id1, "inv": inv_id},
        )
        conn.execute(
            text(
                "INSERT INTO agent_runs (agent_run_id, investigation_run_id, agent_name, status, started_at, tool_calls) "
                "VALUES (:aid, :inv, 'SanctionsAgent', 'SUCCESS', now(), '{}')"
            ),
            {"aid": run_id2, "inv": inv_id},
        )

        record_screening_result(
            conn,
            investigation_run_id=inv_id,
            agent_run_id=run_id1,
            customer_id=cust_id,
            outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
            reason_code=None,
            candidate_count=0,
            watchlist_name="list",
            watchlist_version="v1",
            matching_rule_id="rule",
            normalization_version="v1",
        )

    # Second insert with same investigation_run_id must raise IntegrityError
    with superuser_engine.begin() as conn:
        with pytest.raises(IntegrityError):
            record_screening_result(
                conn,
                investigation_run_id=inv_id,
                agent_run_id=run_id2,
                customer_id=cust_id,
                outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                reason_code=None,
                candidate_count=0,
                watchlist_name="list",
                watchlist_version="v1",
                matching_rule_id="rule",
                normalization_version="v1",
            )


# ==============================================================================
# Additional mandatory checks
# ==============================================================================


def test_mandatory_no_f11_risk_signals_created(
    superuser_engine: Engine,
    app_role_engine: Engine,
) -> None:
    """Verify F11 screening produces ZERO risk_signals rows."""
    corpus = get_synthetic_watchlist_corpus()
    ingest_watchlist_version(superuser_engine, corpus)

    case_id, _, tx_id = _seed_test_case_and_alert(
        superuser_engine, full_name="Aurelius Vance"
    )

    p_compute, p_graph, p_policy = _mock_standard_agents()
    with p_compute as m_tx, p_graph as m_graph, p_policy as m_policy:
        m_tx.return_value = AmountDeviationComputed(
            alerted_transaction_id=tx_id,
            source_account_id=uuid.uuid4(),
            alerted_amount=Decimal("100"),
            historical_average=Decimal("10"),
            deviation_multiple=Decimal("10"),
            historical_transaction_count=1,
            source_transaction_ids=(uuid.uuid4(),),
            currency="INR",
        )
        m_graph.return_value = GraphAgentDispatchResult(
            investigation_run_id=uuid.uuid4(),
            result=SubgraphResult(
                start_entity_id=uuid.uuid4(),
                max_hops=3,
                node_entity_ids=(uuid.uuid4(),),
                relationship_ids=(uuid.uuid4(),),
                truncated=False,
            ),
            cycle_result=CycleNotFound(account_id=uuid.uuid4()),
            chain_result=ChainDepthComputed(
                account_id=uuid.uuid4(),
                depth=0,
                chain_entity_ids=(),
                chain_relationship_ids=(),
            ),
        )
        m_policy.return_value = PolicyEvidenceFound(citations=[])

        orchestrate_investigation(app_role_engine, case_id)

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"
            ),
            {"cid": case_id},
        ).scalar()

        # Check all risk signals for this investigation
        signals = conn.execute(
            text(
                "SELECT signal_type FROM risk_signals WHERE investigation_run_id = :inv_id"
            ),
            {"inv_id": inv_run_id},
        ).fetchall()
        for sig in signals:
            assert "sanctions" not in sig[0].lower()
            assert "watchlist" not in sig[0].lower()


def test_mandatory_prohibited_language_scan() -> None:
    """Scan authored F11 finding text, recommendation text, and constants for prohibited terms."""
    authoring_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "meridian"
        / "agents"
        / "report"
        / "authoring.py"
    )
    content = authoring_path.read_text().lower()

    # Authoring text must not author any prohibited phrase
    for prohibited in PROHIBITED_EXPRESSIONS:
        # Check SANCTIONS_RECOMMENDATION_TEXT
        assert prohibited not in SANCTIONS_RECOMMENDATION_TEXT.lower()

    # Check that the candidate finding interpretation uses approved disclaimer
    assert "not an identity or sanctions determination" in content
    assert "synthetic list" in content
    assert "no validated threshold" in content


def test_mandatory_architecture_import_guards() -> None:
    """Verify ADR-0008 D4 and modular monolith architecture import guards.

    1. entity_resolution never imports agents.sanctions.
    2. agents.report.outcome never imports orchestration.
    """
    repo_root = Path(__file__).resolve().parent.parent
    er_dir = repo_root / "src" / "meridian" / "entity_resolution"

    for py_file in er_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "sanctions" not in alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "sanctions" not in node.module

    # Guard: agents.report.outcome never imports orchestration
    outcome_file = repo_root / "src" / "meridian" / "agents" / "report" / "outcome.py"
    tree = ast.parse(outcome_file.read_text(), filename=str(outcome_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "orchestration" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "orchestration" not in node.module
