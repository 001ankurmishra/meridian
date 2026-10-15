"""Tests for F11 watchlist screening report rendering and deterministic classification.

Tests all 7 states of ADR-0008 D10, consistency checks, prohibited language,
safe display-field handling, and integration with assemble_report().
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import Engine, text

from meridian.agents.report.report_assembly import (
    assemble_report,
)
from meridian.agents.report.screening_classification import (
    SanctionsAgentRunInfo,
    ScreeningResultRow,
    WatchlistScreeningState,
    classify_screening_state,
)
from meridian.audit.audit_trail import get_case_audit_trail
from meridian.evidence.evidence import (
    EVIDENCE_TYPE_POLICY_CHUNK,
    EVIDENCE_TYPE_WATCHLIST_ENTRY,
    record_evidence,
)
from meridian.findings.findings import record_finding
from meridian.orchestration.investigation_run import create_investigation_run
from meridian.orchestration.screening_results_persistence import (
    record_screening_result,
)
from tests.test_report_assembly import (
    _cleanup_seeded_data,
    assert_no_forbidden_language,
    setup_alert,
    setup_case,
    setup_customer_and_transaction,
)

# ADR-0008 D10 prohibited phrases
PROHIBITED_PHRASES: tuple[str, ...] = (
    "sanctioned customer",
    "confirmed hit",
    "criminal",
    "money laundering",
    "cleared",
    "clean",
    "no sanctions exposure",
)


def assert_no_d10_prohibited_wording(text_content: str) -> None:
    """Ensure no ADR-0008 D10 prohibited phrase appears in the text."""
    lower = text_content.lower()
    for phrase in PROHIBITED_PHRASES:
        assert phrase not in lower, (
            f"Prohibited phrase '{phrase}' found in '{text_content}'"
        )


# ==============================================================================
# Unit Tests for classify_screening_state (Pure logic across all 7 D10 branches)
# ==============================================================================


def test_d10_branch_1_candidate_matches_found_consistent() -> None:
    """Branch 1: Consistent CANDIDATE_MATCHES_FOUND screening row."""
    inv_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    s_row = ScreeningResultRow(
        screening_result_id=uuid.uuid4(),
        investigation_run_id=inv_id,
        agent_run_id=ar_id,
        outcome="CANDIDATE_MATCHES_FOUND",
        reason_code=None,
        candidate_count=2,
        watchlist_name="test_sdn_synthetic",
        watchlist_version="2026-10-08",
        matching_rule_id="exact_norm_name_v1",
        normalization_version="v1",
    )
    ar_info = SanctionsAgentRunInfo(
        agent_run_id=ar_id,
        agent_name="SanctionsAgent",
        status="SUCCESS",
        investigation_run_id=inv_id,
    )

    section = classify_screening_state(
        screening_result=s_row,
        referenced_agent_run=ar_info,
        all_sanctions_agent_runs=(ar_info,),
        candidate_finding_count=2,
    )

    assert section.state == WatchlistScreeningState.CANDIDATE_MATCHES_FOUND
    assert section.classification_branch == 1
    assert "2 candidate match(es)" in section.rendered_text
    assert "test_sdn_synthetic" in section.rendered_text
    assert "2026-10-08" in section.rendered_text
    assert "exact_norm_name_v1" in section.rendered_text
    assert (
        "Candidate for human review; not an identity or sanctions determination."
        in section.rendered_text
    )
    assert not section.is_inconsistent
    assert_no_d10_prohibited_wording(section.rendered_text)


def test_d10_branch_2_no_candidate_match() -> None:
    """Branch 2: Consistent NO_CANDIDATE_MATCH screening row."""
    inv_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    s_row = ScreeningResultRow(
        screening_result_id=uuid.uuid4(),
        investigation_run_id=inv_id,
        agent_run_id=ar_id,
        outcome="NO_CANDIDATE_MATCH",
        reason_code=None,
        candidate_count=0,
        watchlist_name="test_sdn_synthetic",
        watchlist_version="2026-10-08",
        matching_rule_id="exact_norm_name_v1",
        normalization_version="v1",
    )
    ar_info = SanctionsAgentRunInfo(
        agent_run_id=ar_id,
        agent_name="SanctionsAgent",
        status="SUCCESS",
        investigation_run_id=inv_id,
    )

    section = classify_screening_state(
        screening_result=s_row,
        referenced_agent_run=ar_info,
        all_sanctions_agent_runs=(ar_info,),
        candidate_finding_count=0,
    )

    assert section.state == WatchlistScreeningState.NO_CANDIDATE_MATCH
    assert section.classification_branch == 2
    assert section.rendered_text == (
        "No candidate match against synthetic list test_sdn_synthetic 2026-10-08. "
        "This is not a clearance."
    )
    assert not section.is_inconsistent
    assert_no_d10_prohibited_wording(section.rendered_text)


@pytest.mark.parametrize(
    "reason_code",
    [
        "CUSTOMER_NAME_MISSING",
        "CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION",
        "WATCHLIST_VERSION_NOT_LOADED",
    ],
)
def test_d10_branch_3_not_performed(reason_code: str) -> None:
    """Branch 3: Consistent NOT_PERFORMED with valid abstention reason codes."""
    inv_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    s_row = ScreeningResultRow(
        screening_result_id=uuid.uuid4(),
        investigation_run_id=inv_id,
        agent_run_id=ar_id,
        outcome="NOT_PERFORMED",
        reason_code=reason_code,
        candidate_count=0,
        watchlist_name="test_sdn_synthetic",
        watchlist_version="2026-10-08",
        matching_rule_id="exact_norm_name_v1",
        normalization_version="v1",
    )
    ar_info = SanctionsAgentRunInfo(
        agent_run_id=ar_id,
        agent_name="SanctionsAgent",
        status="SUCCESS",
        investigation_run_id=inv_id,
    )

    section = classify_screening_state(
        screening_result=s_row,
        referenced_agent_run=ar_info,
        all_sanctions_agent_runs=(ar_info,),
        candidate_finding_count=0,
    )

    assert section.state == WatchlistScreeningState.NOT_PERFORMED
    assert section.classification_branch == 3
    assert section.rendered_text == f"Not determined: {reason_code}."
    assert section.reason_code == reason_code
    assert not section.is_inconsistent
    assert_no_d10_prohibited_wording(section.rendered_text)


def test_d10_branch_4_screening_error() -> None:
    """Branch 4: No row; SanctionsAgent run for same inv_run with status FAILED."""
    inv_id = uuid.uuid4()
    ar_info = SanctionsAgentRunInfo(
        agent_run_id=uuid.uuid4(),
        agent_name="SanctionsAgent",
        status="FAILED",
        investigation_run_id=inv_id,
    )

    section = classify_screening_state(
        screening_result=None,
        referenced_agent_run=None,
        all_sanctions_agent_runs=(ar_info,),
        candidate_finding_count=0,
    )

    assert section.state == WatchlistScreeningState.SCREENING_ERROR
    assert section.classification_branch == 4
    assert section.rendered_text == "Screening error. Not determined."
    assert not section.is_inconsistent
    assert_no_d10_prohibited_wording(section.rendered_text)


@pytest.mark.parametrize("status", ["SUCCESS", "PARTIAL"])
def test_d10_branch_5_missing_result_row(status: str) -> None:
    """Branch 5: No row; SanctionsAgent run with status SUCCESS or PARTIAL."""
    inv_id = uuid.uuid4()
    ar_info = SanctionsAgentRunInfo(
        agent_run_id=uuid.uuid4(),
        agent_name="SanctionsAgent",
        status=status,
        investigation_run_id=inv_id,
    )

    section = classify_screening_state(
        screening_result=None,
        referenced_agent_run=None,
        all_sanctions_agent_runs=(ar_info,),
        candidate_finding_count=0,
    )

    assert section.state == WatchlistScreeningState.INCONSISTENT_MISSING_RESULT
    assert section.classification_branch == 5
    assert section.rendered_text == "Inconsistent screening record. Not determined."
    assert section.is_inconsistent
    assert_no_d10_prohibited_wording(section.rendered_text)


def test_d10_branch_6_screening_not_recorded() -> None:
    """Branch 6: No row; no SanctionsAgent run for same investigation_run_id."""
    section = classify_screening_state(
        screening_result=None,
        referenced_agent_run=None,
        all_sanctions_agent_runs=(),
        candidate_finding_count=0,
    )

    assert section.state == WatchlistScreeningState.SCREENING_NOT_RECORDED
    assert section.classification_branch == 6
    assert section.rendered_text == "Screening not recorded. Not determined."
    assert not section.is_inconsistent
    assert_no_d10_prohibited_wording(section.rendered_text)


def test_d10_branch_7_candidate_count_mismatch() -> None:
    """Branch 7: Row exists but candidate_count != candidate finding count."""
    inv_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    s_row = ScreeningResultRow(
        screening_result_id=uuid.uuid4(),
        investigation_run_id=inv_id,
        agent_run_id=ar_id,
        outcome="CANDIDATE_MATCHES_FOUND",
        reason_code=None,
        candidate_count=2,
        watchlist_name="test_sdn_synthetic",
        watchlist_version="2026-10-08",
        matching_rule_id="exact_norm_name_v1",
        normalization_version="v1",
    )
    ar_info = SanctionsAgentRunInfo(
        agent_run_id=ar_id,
        agent_name="SanctionsAgent",
        status="SUCCESS",
        investigation_run_id=inv_id,
    )

    # 1 finding instead of 2 -> inconsistent!
    section = classify_screening_state(
        screening_result=s_row,
        referenced_agent_run=ar_info,
        all_sanctions_agent_runs=(ar_info,),
        candidate_finding_count=1,
    )

    assert section.state == WatchlistScreeningState.INCONSISTENT_INVALID_ROW
    assert section.classification_branch == 7
    assert section.rendered_text == "Inconsistent screening record. Not determined."
    assert section.is_inconsistent
    assert_no_d10_prohibited_wording(section.rendered_text)


def test_d10_branch_7_referenced_run_not_success() -> None:
    """Branch 7: Row exists but referenced run is not SUCCESS."""
    inv_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    s_row = ScreeningResultRow(
        screening_result_id=uuid.uuid4(),
        investigation_run_id=inv_id,
        agent_run_id=ar_id,
        outcome="CANDIDATE_MATCHES_FOUND",
        reason_code=None,
        candidate_count=1,
        watchlist_name="test_sdn_synthetic",
        watchlist_version="2026-10-08",
        matching_rule_id="exact_norm_name_v1",
        normalization_version="v1",
    )
    ar_info = SanctionsAgentRunInfo(
        agent_run_id=ar_id,
        agent_name="SanctionsAgent",
        status="FAILED",  # FAILED instead of SUCCESS
        investigation_run_id=inv_id,
    )

    section = classify_screening_state(
        screening_result=s_row,
        referenced_agent_run=ar_info,
        all_sanctions_agent_runs=(ar_info,),
        candidate_finding_count=1,
    )

    assert section.state == WatchlistScreeningState.INCONSISTENT_INVALID_ROW
    assert section.classification_branch == 7
    assert section.rendered_text == "Inconsistent screening record. Not determined."
    assert section.is_inconsistent


def test_d10_branch_7_referenced_run_different_investigation() -> None:
    """Branch 7: Row exists but referenced run belongs to different investigation."""
    inv_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    s_row = ScreeningResultRow(
        screening_result_id=uuid.uuid4(),
        investigation_run_id=inv_id,
        agent_run_id=ar_id,
        outcome="NO_CANDIDATE_MATCH",
        reason_code=None,
        candidate_count=0,
        watchlist_name="test_sdn_synthetic",
        watchlist_version="2026-10-08",
        matching_rule_id="exact_norm_name_v1",
        normalization_version="v1",
    )
    ar_info = SanctionsAgentRunInfo(
        agent_run_id=ar_id,
        agent_name="SanctionsAgent",
        status="SUCCESS",
        investigation_run_id=uuid.uuid4(),  # Different investigation_run_id!
    )

    section = classify_screening_state(
        screening_result=s_row,
        referenced_agent_run=ar_info,
        all_sanctions_agent_runs=(),
        candidate_finding_count=0,
    )

    assert section.state == WatchlistScreeningState.INCONSISTENT_INVALID_ROW
    assert section.classification_branch == 7
    assert section.rendered_text == "Inconsistent screening record. Not determined."
    assert section.is_inconsistent


def test_d10_branch_7_referenced_run_different_agent_name() -> None:
    """Branch 7: Row exists but referenced run has agent_name != SanctionsAgent."""
    inv_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    s_row = ScreeningResultRow(
        screening_result_id=uuid.uuid4(),
        investigation_run_id=inv_id,
        agent_run_id=ar_id,
        outcome="NO_CANDIDATE_MATCH",
        reason_code=None,
        candidate_count=0,
        watchlist_name="test_sdn_synthetic",
        watchlist_version="2026-10-08",
        matching_rule_id="exact_norm_name_v1",
        normalization_version="v1",
    )
    ar_info = SanctionsAgentRunInfo(
        agent_run_id=ar_id,
        agent_name="TransactionAgent",  # Wrong agent!
        status="SUCCESS",
        investigation_run_id=inv_id,
    )

    section = classify_screening_state(
        screening_result=s_row,
        referenced_agent_run=ar_info,
        all_sanctions_agent_runs=(),
        candidate_finding_count=0,
    )

    assert section.state == WatchlistScreeningState.INCONSISTENT_INVALID_ROW
    assert section.classification_branch == 7
    assert section.rendered_text == "Inconsistent screening record. Not determined."
    assert section.is_inconsistent


def test_d10_no_row_no_agent_run_with_positive_candidate_findings() -> None:
    """ADR-0008 D7/D10: No row and no SanctionsAgent run produces
    SCREENING_NOT_RECORDED regardless of candidate-finding count.
    """
    section = classify_screening_state(
        screening_result=None,
        referenced_agent_run=None,
        all_sanctions_agent_runs=(),
        candidate_finding_count=2,
    )

    assert section.state == WatchlistScreeningState.SCREENING_NOT_RECORDED
    assert section.classification_branch == 6
    assert section.rendered_text == "Screening not recorded. Not determined."
    assert not section.is_inconsistent
    assert_no_d10_prohibited_wording(section.rendered_text)


def test_d10_no_row_failed_agent_run_with_positive_candidate_findings() -> None:
    """ADR-0008 D10 Branch 4: No row and SanctionsAgent FAILED produces
    SCREENING_ERROR regardless of candidate-finding count.
    """
    inv_id = uuid.uuid4()
    ar_info = SanctionsAgentRunInfo(
        agent_run_id=uuid.uuid4(),
        agent_name="SanctionsAgent",
        status="FAILED",
        investigation_run_id=inv_id,
    )
    section = classify_screening_state(
        screening_result=None,
        referenced_agent_run=None,
        all_sanctions_agent_runs=(ar_info,),
        candidate_finding_count=2,
    )

    assert section.state == WatchlistScreeningState.SCREENING_ERROR
    assert section.classification_branch == 4
    assert section.rendered_text == "Screening error. Not determined."
    assert not section.is_inconsistent
    assert_no_d10_prohibited_wording(section.rendered_text)


def test_d10_multiple_sanctions_agent_runs_handling() -> None:
    """Verify handling when multiple SanctionsAgent runs exist."""
    inv_id = uuid.uuid4()
    run_failed_1 = SanctionsAgentRunInfo(
        agent_run_id=uuid.uuid4(),
        agent_name="SanctionsAgent",
        status="FAILED",
        investigation_run_id=inv_id,
    )
    run_failed_2 = SanctionsAgentRunInfo(
        agent_run_id=uuid.uuid4(),
        agent_name="SanctionsAgent",
        status="FAILED",
        investigation_run_id=inv_id,
    )
    run_success = SanctionsAgentRunInfo(
        agent_run_id=uuid.uuid4(),
        agent_name="SanctionsAgent",
        status="SUCCESS",
        investigation_run_id=inv_id,
    )

    # 1. Multiple failed runs, no row -> SCREENING_ERROR
    sec_all_failed = classify_screening_state(
        screening_result=None,
        referenced_agent_run=None,
        all_sanctions_agent_runs=(run_failed_1, run_failed_2),
        candidate_finding_count=0,
    )
    assert sec_all_failed.state == WatchlistScreeningState.SCREENING_ERROR
    assert sec_all_failed.classification_branch == 4

    # 2. Failed run followed by SUCCESS, missing row -> INCONSISTENT_MISSING_RESULT
    sec_mixed = classify_screening_state(
        screening_result=None,
        referenced_agent_run=None,
        all_sanctions_agent_runs=(run_failed_1, run_success),
        candidate_finding_count=0,
    )
    assert sec_mixed.state == WatchlistScreeningState.INCONSISTENT_MISSING_RESULT
    assert sec_mixed.classification_branch == 5

    # 3. Failed run followed by SUCCESS, row references SUCCESS -> NO_CANDIDATE_MATCH
    s_row = ScreeningResultRow(
        screening_result_id=uuid.uuid4(),
        investigation_run_id=inv_id,
        agent_run_id=run_success.agent_run_id,
        outcome="NO_CANDIDATE_MATCH",
        reason_code=None,
        candidate_count=0,
        watchlist_name="test_sdn_synthetic",
        watchlist_version="2026-10-08",
        matching_rule_id="exact_norm_name_v1",
        normalization_version="v1",
    )
    sec_success_referenced = classify_screening_state(
        screening_result=s_row,
        referenced_agent_run=run_success,
        all_sanctions_agent_runs=(run_failed_1, run_success),
        candidate_finding_count=0,
    )
    assert sec_success_referenced.state == WatchlistScreeningState.NO_CANDIDATE_MATCH
    assert sec_success_referenced.classification_branch == 2


# ==============================================================================
# Database Integration Tests for assemble_report and get_case_audit_trail
# ==============================================================================


def _setup_screening_test_env(
    superuser_engine: Engine,
    app_role_engine: Engine,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Helper to seed customer, case, investigation run, and policy finding."""
    cid, tid = setup_customer_and_transaction(superuser_engine)
    alert_id = setup_alert(superuser_engine, cid, tid)
    case_id = setup_case(superuser_engine, alert_id)
    inv_run = create_investigation_run(app_role_engine, case_id)
    return cid, tid, case_id, inv_run.investigation_run_id


def test_assemble_report_screening_not_recorded(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Pre-F11 or legacy investigation run: No SanctionsAgent run and no row."""
    cid, tid, case_id, inv_run_id = _setup_screening_test_env(
        superuser_engine, app_role_engine
    )
    try:
        now = datetime.now(timezone.utc)
        ar_id = uuid.uuid4()
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_runs ("
                    "agent_run_id, investigation_run_id, agent_name, "
                    "status, started_at, tool_calls) "
                    "VALUES (:ar_id, :inv_id, 'TransactionAgent', "
                    "'SUCCESS', :now, '{}')"
                ),
                {"ar_id": ar_id, "inv_id": inv_run_id, "now": now},
            )
        ev_policy = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run_id,
            evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
            reference_table="document_chunks",
            reference_id=uuid.uuid4(),
            produced_by_agent_run_id=ar_id,
        )
        record_finding(
            engine=app_role_engine,
            investigation_run_id=inv_run_id,
            observed_fact="Standard transaction check completed.",
            derived_signal=None,
            interpretation=None,
            evidence_ids=[ev_policy.evidence_id],
            confidence="HIGH",
        )

        report = assemble_report(app_role_engine, inv_run_id)

        ws = report.watchlist_screening
        assert ws.state == WatchlistScreeningState.SCREENING_NOT_RECORDED
        assert ws.rendered_text == "Screening not recorded. Not determined."
        assert ws.classification_branch == 6
        assert_no_forbidden_language(report)
        assert_no_d10_prohibited_wording(ws.rendered_text)

        # Audit trail check: screening_result is None
        trail = get_case_audit_trail(app_role_engine, case_id)
        assert len(trail.investigation_runs) == 1
        assert trail.investigation_runs[0].screening_result is None

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_assemble_report_screening_error(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """SanctionsAgent run FAILED, no screening_results row."""
    cid, tid, case_id, inv_run_id = _setup_screening_test_env(
        superuser_engine, app_role_engine
    )
    try:
        now = datetime.now(timezone.utc)
        sanctions_ar_id = uuid.uuid4()
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_runs ("
                    "agent_run_id, investigation_run_id, agent_name, "
                    "status, started_at, error, tool_calls) "
                    "VALUES (:ar_id, :inv_id, 'SanctionsAgent', "
                    "'FAILED', :now, 'DATABASE_ERROR', '{}')"
                ),
                {"ar_id": sanctions_ar_id, "inv_id": inv_run_id, "now": now},
            )

        ev_policy = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run_id,
            evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
            reference_table="document_chunks",
            reference_id=uuid.uuid4(),
            produced_by_agent_run_id=sanctions_ar_id,
        )
        record_finding(
            engine=app_role_engine,
            investigation_run_id=inv_run_id,
            observed_fact="Primary evidence check.",
            derived_signal=None,
            interpretation=None,
            evidence_ids=[ev_policy.evidence_id],
            confidence="HIGH",
        )

        report = assemble_report(app_role_engine, inv_run_id)

        ws = report.watchlist_screening
        assert ws.state == WatchlistScreeningState.SCREENING_ERROR
        assert ws.rendered_text == "Screening error. Not determined."
        assert ws.classification_branch == 4
        assert_no_forbidden_language(report)
        assert_no_d10_prohibited_wording(ws.rendered_text)

        # Audit trail check: screening_result is None
        trail = get_case_audit_trail(app_role_engine, case_id)
        assert trail.investigation_runs[0].screening_result is None

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_assemble_report_inconsistent_missing_result_row(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """SanctionsAgent run SUCCESS but authoring rolled back (no result row)."""
    cid, tid, case_id, inv_run_id = _setup_screening_test_env(
        superuser_engine, app_role_engine
    )
    try:
        now = datetime.now(timezone.utc)
        sanctions_ar_id = uuid.uuid4()
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_runs ("
                    "agent_run_id, investigation_run_id, agent_name, "
                    "status, started_at, tool_calls) "
                    "VALUES (:ar_id, :inv_id, 'SanctionsAgent', "
                    "'SUCCESS', :now, '{}')"
                ),
                {"ar_id": sanctions_ar_id, "inv_id": inv_run_id, "now": now},
            )

        ev_policy = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run_id,
            evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
            reference_table="document_chunks",
            reference_id=uuid.uuid4(),
            produced_by_agent_run_id=sanctions_ar_id,
        )
        record_finding(
            engine=app_role_engine,
            investigation_run_id=inv_run_id,
            observed_fact="Primary evidence check.",
            derived_signal=None,
            interpretation=None,
            evidence_ids=[ev_policy.evidence_id],
            confidence="HIGH",
        )

        report = assemble_report(app_role_engine, inv_run_id)

        ws = report.watchlist_screening
        assert ws.state == WatchlistScreeningState.INCONSISTENT_MISSING_RESULT
        assert ws.rendered_text == "Inconsistent screening record. Not determined."
        assert ws.classification_branch == 5
        assert ws.is_inconsistent
        assert_no_forbidden_language(report)

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_assemble_report_and_audit_trail_candidate_matches_found(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """End-to-end integration: CANDIDATE_MATCHES_FOUND with consistent findings."""
    cid, tid, case_id, inv_run_id = _setup_screening_test_env(
        superuser_engine, app_role_engine
    )
    try:
        now = datetime.now(timezone.utc)
        sanctions_ar_id = uuid.uuid4()
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_runs ("
                    "agent_run_id, investigation_run_id, agent_name, "
                    "status, started_at, tool_calls) "
                    "VALUES (:ar_id, :inv_id, 'SanctionsAgent', "
                    "'SUCCESS', :now, '{}')"
                ),
                {"ar_id": sanctions_ar_id, "inv_id": inv_run_id, "now": now},
            )

        # 1. Persist screening result
        with superuser_engine.begin() as conn:
            s_res_id = record_screening_result(
                conn,
                investigation_run_id=inv_run_id,
                agent_run_id=sanctions_ar_id,
                customer_id=cid,
                outcome="CANDIDATE_MATCHES_FOUND",
                reason_code=None,
                candidate_count=1,
                watchlist_name="test_sdn_synthetic",
                watchlist_version="2026-10-08",
                matching_rule_id="exact_norm_name_v1",
                normalization_version="v1",
            )

        # 2. Record customer and watchlist_entry evidence
        ev_policy = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run_id,
            evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
            reference_table="document_chunks",
            reference_id=uuid.uuid4(),
            produced_by_agent_run_id=sanctions_ar_id,
        )
        ev_watchlist = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run_id,
            evidence_type=EVIDENCE_TYPE_WATCHLIST_ENTRY,
            reference_table="watchlist_entries",
            reference_id=uuid.uuid4(),
            produced_by_agent_run_id=sanctions_ar_id,
        )

        # 3. Record candidate finding referencing watchlist_entry evidence
        record_finding(
            engine=app_role_engine,
            investigation_run_id=inv_run_id,
            observed_fact=(
                "The customer's normalized name equals a listed name on "
                "synthetic list test_sdn_synthetic 2026-10-08 under rule "
                "exact_norm_name_v1, normalization v1."
            ),
            derived_signal=(
                "Exact normalized-name equality; dob_comparison = NOT_COMPARABLE."
            ),
            interpretation=(
                "Candidate watchlist match for human review. "
                "Not an identity or sanctions determination. "
                "Synthetic list. No validated threshold."
            ),
            evidence_ids=[ev_policy.evidence_id, ev_watchlist.evidence_id],
            confidence="LOW",
        )

        # Assemble Report
        report = assemble_report(app_role_engine, inv_run_id)

        ws = report.watchlist_screening
        assert ws.state == WatchlistScreeningState.CANDIDATE_MATCHES_FOUND
        assert ws.classification_branch == 1
        assert "1 candidate match(es)" in ws.rendered_text
        assert "test_sdn_synthetic 2026-10-08" in ws.rendered_text
        assert "exact_norm_name_v1" in ws.rendered_text
        assert ws.candidate_count == 1
        assert ws.outcome == "CANDIDATE_MATCHES_FOUND"
        assert ws.agent_run_id == sanctions_ar_id
        assert_no_forbidden_language(report)
        assert_no_d10_prohibited_wording(ws.rendered_text)

        # Audit Trail Verification
        trail = get_case_audit_trail(app_role_engine, case_id)
        assert len(trail.investigation_runs) == 1
        run_entry = trail.investigation_runs[0]
        assert run_entry.screening_result is not None
        sr_entry = run_entry.screening_result
        assert sr_entry.screening_result_id == s_res_id
        assert sr_entry.agent_run_id == sanctions_ar_id
        assert sr_entry.outcome == "CANDIDATE_MATCHES_FOUND"
        assert sr_entry.reason_code is None
        assert sr_entry.candidate_count == 1
        assert sr_entry.watchlist_name == "test_sdn_synthetic"
        assert sr_entry.watchlist_version == "2026-10-08"
        assert sr_entry.matching_rule_id == "exact_norm_name_v1"
        assert sr_entry.normalization_version == "v1"
        assert isinstance(sr_entry.created_at, datetime)

        # Safe display verification: ensure no sensitive customer or subject fields
        assert not hasattr(sr_entry, "customer_id")
        assert not hasattr(sr_entry, "subject_key")
        assert not hasattr(sr_entry, "customer_name")
        assert not hasattr(sr_entry, "date_of_birth")

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_assemble_report_no_candidate_match(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Integration: NO_CANDIDATE_MATCH persisted and rendered."""
    cid, tid, case_id, inv_run_id = _setup_screening_test_env(
        superuser_engine, app_role_engine
    )
    try:
        now = datetime.now(timezone.utc)
        sanctions_ar_id = uuid.uuid4()
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_runs ("
                    "agent_run_id, investigation_run_id, agent_name, "
                    "status, started_at, tool_calls) "
                    "VALUES (:ar_id, :inv_id, 'SanctionsAgent', "
                    "'SUCCESS', :now, '{}')"
                ),
                {"ar_id": sanctions_ar_id, "inv_id": inv_run_id, "now": now},
            )
            record_screening_result(
                conn,
                investigation_run_id=inv_run_id,
                agent_run_id=sanctions_ar_id,
                customer_id=cid,
                outcome="NO_CANDIDATE_MATCH",
                reason_code=None,
                candidate_count=0,
                watchlist_name="test_sdn_synthetic",
                watchlist_version="2026-10-08",
                matching_rule_id="exact_norm_name_v1",
                normalization_version="v1",
            )

        ev_policy = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run_id,
            evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
            reference_table="document_chunks",
            reference_id=uuid.uuid4(),
            produced_by_agent_run_id=sanctions_ar_id,
        )
        record_finding(
            engine=app_role_engine,
            investigation_run_id=inv_run_id,
            observed_fact="No alerts on primary transactions.",
            derived_signal=None,
            interpretation=None,
            evidence_ids=[ev_policy.evidence_id],
            confidence="HIGH",
        )

        report = assemble_report(app_role_engine, inv_run_id)

        ws = report.watchlist_screening
        assert ws.state == WatchlistScreeningState.NO_CANDIDATE_MATCH
        assert ws.classification_branch == 2
        assert ws.rendered_text == (
            "No candidate match against synthetic list test_sdn_synthetic 2026-10-08. "
            "This is not a clearance."
        )
        assert_no_forbidden_language(report)
        assert_no_d10_prohibited_wording(ws.rendered_text)

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_assemble_report_not_performed_abstention(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Integration: NOT_PERFORMED with CUSTOMER_NAME_MISSING."""
    cid, tid, case_id, inv_run_id = _setup_screening_test_env(
        superuser_engine, app_role_engine
    )
    try:
        now = datetime.now(timezone.utc)
        sanctions_ar_id = uuid.uuid4()
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_runs ("
                    "agent_run_id, investigation_run_id, agent_name, "
                    "status, started_at, tool_calls) "
                    "VALUES (:ar_id, :inv_id, 'SanctionsAgent', "
                    "'SUCCESS', :now, '{}')"
                ),
                {"ar_id": sanctions_ar_id, "inv_id": inv_run_id, "now": now},
            )
            record_screening_result(
                conn,
                investigation_run_id=inv_run_id,
                agent_run_id=sanctions_ar_id,
                customer_id=cid,
                outcome="NOT_PERFORMED",
                reason_code="CUSTOMER_NAME_MISSING",
                candidate_count=0,
                watchlist_name="test_sdn_synthetic",
                watchlist_version="2026-10-08",
                matching_rule_id="exact_norm_name_v1",
                normalization_version="v1",
            )

        ev_policy = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run_id,
            evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
            reference_table="document_chunks",
            reference_id=uuid.uuid4(),
            produced_by_agent_run_id=sanctions_ar_id,
        )
        record_finding(
            engine=app_role_engine,
            investigation_run_id=inv_run_id,
            observed_fact="Primary transaction analysis completed.",
            derived_signal=None,
            interpretation=None,
            evidence_ids=[ev_policy.evidence_id],
            confidence="HIGH",
        )

        report = assemble_report(app_role_engine, inv_run_id)

        ws = report.watchlist_screening
        assert ws.state == WatchlistScreeningState.NOT_PERFORMED
        assert ws.classification_branch == 3
        assert ws.rendered_text == "Not determined: CUSTOMER_NAME_MISSING."
        assert ws.reason_code == "CUSTOMER_NAME_MISSING"
        assert_no_forbidden_language(report)
        assert_no_d10_prohibited_wording(ws.rendered_text)

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_assemble_report_inconsistent_candidate_count_mismatch(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Integration: Candidate count in screening row (1) != candidate findings (0)."""
    cid, tid, case_id, inv_run_id = _setup_screening_test_env(
        superuser_engine, app_role_engine
    )
    try:
        now = datetime.now(timezone.utc)
        sanctions_ar_id = uuid.uuid4()
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_runs ("
                    "agent_run_id, investigation_run_id, agent_name, "
                    "status, started_at, tool_calls) "
                    "VALUES (:ar_id, :inv_id, 'SanctionsAgent', "
                    "'SUCCESS', :now, '{}')"
                ),
                {"ar_id": sanctions_ar_id, "inv_id": inv_run_id, "now": now},
            )
            # Row has candidate_count=1
            record_screening_result(
                conn,
                investigation_run_id=inv_run_id,
                agent_run_id=sanctions_ar_id,
                customer_id=cid,
                outcome="CANDIDATE_MATCHES_FOUND",
                reason_code=None,
                candidate_count=1,
                watchlist_name="test_sdn_synthetic",
                watchlist_version="2026-10-08",
                matching_rule_id="exact_norm_name_v1",
                normalization_version="v1",
            )

        # Only policy finding recorded (0 candidate findings with watchlist evidence)
        ev_policy = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run_id,
            evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
            reference_table="document_chunks",
            reference_id=uuid.uuid4(),
            produced_by_agent_run_id=sanctions_ar_id,
        )
        record_finding(
            engine=app_role_engine,
            investigation_run_id=inv_run_id,
            observed_fact="Policy chunk evidence only.",
            derived_signal=None,
            interpretation=None,
            evidence_ids=[ev_policy.evidence_id],
            confidence="HIGH",
        )

        report = assemble_report(app_role_engine, inv_run_id)

        ws = report.watchlist_screening
        assert ws.state == WatchlistScreeningState.INCONSISTENT_INVALID_ROW
        assert ws.classification_branch == 7
        assert ws.rendered_text == "Inconsistent screening record. Not determined."
        assert ws.is_inconsistent
        assert_no_forbidden_language(report)

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_assemble_report_screening_error_with_candidate_finding(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Integration: SanctionsAgent FAILED with candidate finding
    produces SCREENING_ERROR.

    Per ADR-0008 D7 & D10 Branch 4, outcome is not inferred from findings.
    """
    cid, tid, case_id, inv_run_id = _setup_screening_test_env(
        superuser_engine, app_role_engine
    )
    try:
        now = datetime.now(timezone.utc)
        sanctions_ar_id = uuid.uuid4()
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_runs ("
                    "agent_run_id, investigation_run_id, agent_name, "
                    "status, started_at, error, tool_calls) "
                    "VALUES (:ar_id, :inv_id, 'SanctionsAgent', "
                    "'FAILED', :now, 'ERR', '{}')"
                ),
                {"ar_id": sanctions_ar_id, "inv_id": inv_run_id, "now": now},
            )

        # Record watchlist evidence and candidate finding, but NO screening row
        ev_policy = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run_id,
            evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
            reference_table="document_chunks",
            reference_id=uuid.uuid4(),
            produced_by_agent_run_id=sanctions_ar_id,
        )
        ev_watchlist = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run_id,
            evidence_type=EVIDENCE_TYPE_WATCHLIST_ENTRY,
            reference_table="watchlist_entries",
            reference_id=uuid.uuid4(),
            produced_by_agent_run_id=sanctions_ar_id,
        )
        record_finding(
            engine=app_role_engine,
            investigation_run_id=inv_run_id,
            observed_fact="Candidate finding exists without screening row.",
            derived_signal=None,
            interpretation=None,
            evidence_ids=[ev_policy.evidence_id, ev_watchlist.evidence_id],
            confidence="LOW",
        )

        report = assemble_report(app_role_engine, inv_run_id)

        ws = report.watchlist_screening
        assert ws.state == WatchlistScreeningState.SCREENING_ERROR
        assert ws.classification_branch == 4
        assert ws.rendered_text == "Screening error. Not determined."
        assert not ws.is_inconsistent
        assert_no_forbidden_language(report)

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_assemble_report_no_row_no_agent_run_with_candidate_finding(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Integration: No row and no SanctionsAgent run produces SCREENING_NOT_RECORDED

    even if candidate finding exists, per ADR-0008 D7 & D10 Branch 6.
    """
    cid, tid, case_id, inv_run_id = _setup_screening_test_env(
        superuser_engine, app_role_engine
    )
    try:
        now = datetime.now(timezone.utc)
        other_ar_id = uuid.uuid4()
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_runs ("
                    "agent_run_id, investigation_run_id, agent_name, "
                    "status, started_at, tool_calls) "
                    "VALUES (:ar_id, :inv_id, 'TransactionAgent', "
                    "'SUCCESS', :now, '{}')"
                ),
                {"ar_id": other_ar_id, "inv_id": inv_run_id, "now": now},
            )

        ev_policy = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run_id,
            evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
            reference_table="document_chunks",
            reference_id=uuid.uuid4(),
            produced_by_agent_run_id=other_ar_id,
        )
        ev_watchlist = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run_id,
            evidence_type=EVIDENCE_TYPE_WATCHLIST_ENTRY,
            reference_table="watchlist_entries",
            reference_id=uuid.uuid4(),
            produced_by_agent_run_id=other_ar_id,
        )
        record_finding(
            engine=app_role_engine,
            investigation_run_id=inv_run_id,
            observed_fact="Candidate finding exists without screening row or run.",
            derived_signal=None,
            interpretation=None,
            evidence_ids=[ev_policy.evidence_id, ev_watchlist.evidence_id],
            confidence="LOW",
        )

        report = assemble_report(app_role_engine, inv_run_id)

        ws = report.watchlist_screening
        assert ws.state == WatchlistScreeningState.SCREENING_NOT_RECORDED
        assert ws.classification_branch == 6
        assert ws.rendered_text == "Screening not recorded. Not determined."
        assert not ws.is_inconsistent
        assert_no_forbidden_language(report)

    finally:
        _cleanup_seeded_data(superuser_engine, cid)
