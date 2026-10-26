"""Adversarial persistence and report checks against the disposable database."""

import uuid
from collections.abc import Generator

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
from tests.test_report_assembly import (
    _cleanup_seeded_data,
    setup_agent_run,
    setup_alert,
    setup_case,
    setup_customer_and_transaction,
)


@pytest.fixture
def context(
    app_role_engine: Engine, superuser_engine: Engine,
) -> Generator[tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID], None, None]:
    cid, tid = setup_customer_and_transaction(superuser_engine)
    try:
        case = setup_case(superuser_engine, setup_alert(superuser_engine, cid, tid))
        run = create_investigation_run(app_role_engine, case).investigation_run_id
        other_case = setup_case(
            superuser_engine, setup_alert(superuser_engine, cid, tid)
        )
        other = create_investigation_run(
            app_role_engine, other_case
        ).investigation_run_id
        agent = setup_agent_run(superuser_engine, run)
        yield tid, run, other, agent
    finally:
        _cleanup_seeded_data(superuser_engine, cid)


@pytest.mark.parametrize("table", ["transactions", "transactions; DROP TABLE cases"])
def test_reject_unresolved_source(
    app_role_engine: Engine, context: tuple[uuid.UUID, ...], table: str,
) -> None:
    _, run, _, agent = context
    with pytest.raises(ValueError):
        record_evidence(app_role_engine, run, "transaction", table,
                        uuid.uuid4(), agent)


def test_reject_cross_run_producer(
    app_role_engine: Engine, context: tuple[uuid.UUID, ...],
) -> None:
    tid, _, other, agent = context
    with pytest.raises(ValueError, match="producer"):
        record_evidence(app_role_engine, other, "transaction", "transactions",
                        tid, agent)


def test_reject_cross_run_finding_and_recommendation(
    app_role_engine: Engine, context: tuple[uuid.UUID, ...],
) -> None:
    tid, run, other, agent = context
    ev = record_evidence(app_role_engine, run, "transaction", "transactions",
                         tid, agent)
    with pytest.raises(ValueError, match="same investigation"):
        record_finding(app_role_engine, other, "Fact", None, None,
                       [ev.evidence_id], "LOW")
    finding = record_finding(app_role_engine, run, "Fact", None, None,
                             [ev.evidence_id], "LOW")
    with pytest.raises(ValueError, match="same investigation"):
        record_recommendation(app_role_engine, other, "Human review",
                              [finding.finding_id])


@pytest.mark.parametrize("corruption", ["missing", "source", "ownership", "producer"])
def test_report_revalidates_persisted_evidence(
    app_role_engine: Engine, superuser_engine: Engine,
    context: tuple[uuid.UUID, ...], corruption: str,
) -> None:
    tid, run, other, agent = context
    ev = record_evidence(app_role_engine, run, "transaction", "transactions",
                         tid, agent)
    record_finding(app_role_engine, run, "Fact", None, None,
                   [ev.evidence_id], "LOW")
    # Simulate legacy/corrupt data with the privileged role. The runtime role
    # cannot update or delete these append-only rows.
    with superuser_engine.begin() as conn:
        if corruption == "missing":
            conn.execute(text("DELETE FROM evidence WHERE evidence_id = :id"),
                         {"id": ev.evidence_id})
        elif corruption == "source":
            conn.execute(text("UPDATE evidence SET reference_id = :bad "
                              "WHERE evidence_id = :id"),
                         {"bad": uuid.uuid4(), "id": ev.evidence_id})
        elif corruption == "ownership":
            conn.execute(text("UPDATE evidence SET investigation_run_id = :other "
                              "WHERE evidence_id = :id"),
                         {"other": other, "id": ev.evidence_id})
        else:
            conn.execute(text("UPDATE agent_runs SET investigation_run_id = :other "
                              "WHERE agent_run_id = :id"),
                         {"id": agent, "other": other})
    with pytest.raises(InsufficientEvidenceError):
        assemble_report(app_role_engine, run)


def test_failure_canary_is_not_persisted_or_returned(
    app_role_engine: Engine, superuser_engine: Engine,
    context: tuple[uuid.UUID, ...],
) -> None:
    from meridian.audit.audit_trail import get_case_audit_trail
    from meridian.orchestration.agent_run_tracking import record_agent_run

    _, run, _, _ = context
    canary = "secret-token-and-private-customer-canary"

    def fail() -> None:
        raise RuntimeError(canary)

    with pytest.raises(RuntimeError):
        record_agent_run(app_role_engine, run, "CanaryAgent", fail)
    with superuser_engine.begin() as conn:
        error = conn.scalar(text("SELECT error FROM agent_runs "
                                 "WHERE investigation_run_id = :run "
                                 "AND agent_name = 'CanaryAgent'"), {"run": run})
        assert error == "AGENT_ERROR"
        case_id = conn.scalar(text("SELECT case_id FROM investigation_runs "
                                   "WHERE investigation_run_id = :run"),
                              {"run": run})
        # Legacy text is sanitized at read time without changing stored history.
        conn.execute(text("UPDATE agent_runs SET error = :canary "
                          "WHERE investigation_run_id = :run "
                          "AND agent_name = 'CanaryAgent'"),
                     {"canary": canary, "run": run})
    assert canary not in repr(get_case_audit_trail(app_role_engine, case_id))


def test_unexpected_api_error_does_not_leak(caplog: pytest.LogCaptureFixture) -> None:
    from fastapi.testclient import TestClient

    from meridian.db.session import get_db
    from meridian.main import app

    canary = "private-exception-canary"

    def unavailable() -> None:
        raise RuntimeError(canary)

    app.dependency_overrides[get_db] = unavailable
    try:
        response = TestClient(app).get("/health")
        assert response.status_code == 500
        assert canary not in response.text
        assert canary not in caplog.text
        assert response.headers["X-Request-ID"] == response.json()["request_id"]
    finally:
        app.dependency_overrides.clear()


def test_complete_report_requires_findings(
    app_role_engine: Engine, superuser_engine: Engine,
    context: tuple[uuid.UUID, ...],
) -> None:
    _, run, _, _ = context
    with superuser_engine.begin() as conn:
        conn.execute(text("UPDATE investigation_runs SET status = 'COMPLETE' "
                          "WHERE investigation_run_id = :run"), {"run": run})
    with pytest.raises(InsufficientEvidenceError, match="no supported findings"):
        assemble_report(app_role_engine, run)


@pytest.mark.parametrize("reference", ["missing", "other_run", "empty"])
def test_report_revalidates_recommendation_findings(
    app_role_engine: Engine, superuser_engine: Engine,
    context: tuple[uuid.UUID, ...], reference: str,
) -> None:
    tid, run, other, agent = context
    ev = record_evidence(app_role_engine, run, "transaction", "transactions",
                         tid, agent)
    finding = record_finding(app_role_engine, run, "Fact", None, None,
                             [ev.evidence_id], "LOW")
    rec = record_recommendation(app_role_engine, run, "Review", [finding.finding_id])
    with superuser_engine.begin() as conn:
        if reference == "other_run":
            conn.execute(text("UPDATE findings SET investigation_run_id = :other "
                              "WHERE finding_id = :id"),
                         {"other": other, "id": finding.finding_id})
        else:
            conn.execute(text("UPDATE recommendations SET based_on_finding_ids = :ids "
                              "WHERE recommendation_id = :id"),
                         {"ids": [] if reference == "empty" else [uuid.uuid4()],
                          "id": rec.recommendation_id})
    with pytest.raises(InsufficientEvidenceError, match="Recommendation"):
        assemble_report(app_role_engine, run)
