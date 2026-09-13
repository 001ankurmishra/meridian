"""Tests for report assembly primitive."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import Engine, text

from meridian.agents.report.report_assembly import (
    InsufficientEvidenceError,
    assemble_report,
)
from meridian.evidence.evidence import record_evidence
from meridian.findings.findings import record_finding
from meridian.orchestration.investigation_run import create_investigation_run
from meridian.recommendations.recommendations import record_recommendation


def setup_customer_and_transaction(
    superuser_engine: Engine, amount: float = 100.0
) -> tuple[uuid.UUID, uuid.UUID]:
    cid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers "
                "(customer_id, full_name, is_synthetic, kyc_risk_rating, created_at) "
                "VALUES (:cid, 'Test Customer', true, 'HIGH', :now)"
            ),
            {"cid": cid, "now": datetime.now(timezone.utc)},
        )

    aid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (account_id, customer_id, status, created_at) "
                "VALUES (:aid, :cid, 'active', :now)"
            ),
            {"aid": aid, "cid": cid, "now": datetime.now(timezone.utc)},
        )

    tid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions "
                "(transaction_id, source_account_id, amount, "
                "currency, occurred_at, created_at) "
                "VALUES (:tid, :aid, :amount, 'INR', :now, :now)"
            ),
            {
                "tid": tid,
                "aid": aid,
                "amount": amount,
                "now": datetime.now(timezone.utc),
            },
        )
    return cid, tid


def setup_alert(
    superuser_engine: Engine, customer_id: uuid.UUID, transaction_id: uuid.UUID
) -> uuid.UUID:
    alert_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts "
                "(alert_id, customer_id, transaction_id, created_at) "
                "VALUES (:aid, :cid, :tid, :now)"
            ),
            {"aid": alert_id, "cid": customer_id, "tid": transaction_id, "now": now},
        )
    return alert_id


def setup_case(superuser_engine: Engine, alert_id: uuid.UUID) -> uuid.UUID:
    case_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO cases "
                "(case_id, alert_id, status, created_at) "
                "VALUES (:cid, :aid, 'OPEN', :now)"
            ),
            {"cid": case_id, "aid": alert_id, "now": now},
        )
    return case_id


def setup_agent_run(superuser_engine: Engine, inv_run_id: uuid.UUID) -> uuid.UUID:
    ar_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_runs "
                "(agent_run_id, investigation_run_id, agent_name, status, "
                "started_at, tool_calls) "
                "VALUES (:ar_id, :inv_id, 'TestAgent', 'SUCCESS', :now, '[]')"
            ),
            {"ar_id": ar_id, "inv_id": inv_run_id, "now": now},
        )
    return ar_id


def _cleanup_seeded_data(superuser_engine: Engine, customer_id: uuid.UUID) -> None:
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM recommendations"))
        conn.execute(text("DELETE FROM findings"))
        conn.execute(text("DELETE FROM evidence"))
        conn.execute(text("DELETE FROM agent_runs"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(
            text(
                "DELETE FROM transactions WHERE source_account_id IN "
                "(SELECT account_id FROM accounts WHERE customer_id = :cid)"
            ),
            {"cid": customer_id},
        )
        conn.execute(
            text("DELETE FROM accounts WHERE customer_id = :cid"), {"cid": customer_id}
        )
        conn.execute(
            text("DELETE FROM customers WHERE customer_id = :cid"), {"cid": customer_id}
        )


def test_assemble_report_success(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Test deterministic report assembly with valid findings/evidence/recs."""
    cid, tid = setup_customer_and_transaction(superuser_engine)
    try:
        alert_id = setup_alert(superuser_engine, cid, tid)
        case_id = setup_case(superuser_engine, alert_id)
        inv_run = create_investigation_run(app_role_engine, case_id)
        ar_id = setup_agent_run(superuser_engine, inv_run.investigation_run_id)

        # Record Evidence
        ev1 = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run.investigation_run_id,
            evidence_type="transaction_amount_deviation",
            reference_table="transactions",
            reference_id=tid,
            produced_by_agent_run_id=ar_id,
        )
        ev_policy = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run.investigation_run_id,
            evidence_type="policy_chunk",
            reference_table="document_chunks",
            reference_id=uuid.uuid4(),
            produced_by_agent_run_id=ar_id,
        )

        # Record Finding
        finding = record_finding(
            engine=app_role_engine,
            investigation_run_id=inv_run.investigation_run_id,
            observed_fact="Transaction deviation is high.",
            derived_signal=None,
            interpretation=None,
            evidence_ids=[ev1.evidence_id, ev_policy.evidence_id],
            confidence="HIGH",
        )

        # Record Recommendation
        rec = record_recommendation(
            engine=app_role_engine,
            investigation_run_id=inv_run.investigation_run_id,
            recommendation_text="File SAR.",
            based_on_finding_ids=[finding.finding_id],
        )

        # Assemble Report
        report = assemble_report(app_role_engine, inv_run.investigation_run_id)

        assert report.case_id == case_id
        assert report.investigation_run_id == inv_run.investigation_run_id
        assert report.customer_name == "Test Customer"
        assert report.risk_level == "HIGH"
        assert report.evidence_completeness_status == "IN_PROGRESS"

        assert len(report.findings) == 1
        assert report.findings[0].finding_id == finding.finding_id

        assert len(report.evidence) == 1
        assert report.evidence[0].evidence_id == ev1.evidence_id

        assert len(report.applicable_policies) == 1
        assert report.applicable_policies[0].evidence_id == ev_policy.evidence_id

        assert len(report.recommendations) == 1
        assert report.recommendations[0].recommendation_id == rec.recommendation_id

        assert report.human_review_required is True
        assert "Overall confidence is HIGH" in report.confidence_text

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_assemble_report_insufficient_evidence(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Test that report assembly is gated if any finding lacks evidence."""
    cid, tid = setup_customer_and_transaction(superuser_engine)
    try:
        alert_id = setup_alert(superuser_engine, cid, tid)
        case_id = setup_case(superuser_engine, alert_id)
        inv_run = create_investigation_run(app_role_engine, case_id)

        # Record Finding WITH NO EVIDENCE
        record_finding(
            engine=app_role_engine,
            investigation_run_id=inv_run.investigation_run_id,
            observed_fact="Unsupported claim.",
            derived_signal=None,
            interpretation=None,
            evidence_ids=[],
            confidence="HIGH",
        )

        # Assemble Report should fail
        with pytest.raises(
            InsufficientEvidenceError, match="fails evidence sufficiency gate"
        ):
            assemble_report(app_role_engine, inv_run.investigation_run_id)

    finally:
        _cleanup_seeded_data(superuser_engine, cid)
