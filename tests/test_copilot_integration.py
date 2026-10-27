"""Authenticated, read-only copilot package integration on guarded test DB."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text

from meridian.agents.report.report_assembly import assemble_report
from meridian.copilot.drafts import MockProvider, generate_draft, load_package
from meridian.evidence.evidence import record_evidence
from meridian.findings.findings import record_finding
from meridian.identity.tokens import issue_token, revoke_token
from meridian.orchestration.investigation_run import create_investigation_run
from tests.test_identity_tokens import _cleanup_user, _seed_user
from tests.test_report_assembly import (
    _cleanup_seeded_data,
    setup_agent_run,
    setup_alert,
    setup_case,
    setup_customer_and_transaction,
)


@pytest.fixture
def seeded(superuser_engine, app_role_engine):
    customer, transaction = setup_customer_and_transaction(superuser_engine)
    user = _seed_user(superuser_engine, "analyst")
    other = _seed_user(superuser_engine, "analyst")
    try:
        case = setup_case(
            superuser_engine, setup_alert(superuser_engine, customer, transaction)
        )
        with superuser_engine.begin() as conn:
            conn.execute(
                text("UPDATE cases SET assigned_analyst_id=:u WHERE case_id=:c"),
                {"u": user, "c": case},
            )
        run = create_investigation_run(app_role_engine, case).investigation_run_id
        agent = setup_agent_run(superuser_engine, run)
        evidence = record_evidence(
            app_role_engine,
            run,
            "alerted_transaction",
            "transactions",
            transaction,
            agent,
        )
        record_finding(
            app_role_engine,
            run,
            "Recorded amount is INR 100.00.",
            None,
            "Purpose is unknown.",
            [evidence.evidence_id],
            "LOW",
        )
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE investigation_runs SET status='COMPLETE' "
                    "WHERE investigation_run_id=:r"
                ),
                {"r": run},
            )
        token = issue_token(superuser_engine, user)
        other_token = issue_token(superuser_engine, other)
        yield case, run, token, other_token, evidence
    finally:
        _cleanup_seeded_data(superuser_engine, customer)
        _cleanup_user(superuser_engine, user)
        _cleanup_user(superuser_engine, other)


def test_package_and_mock_preserve_authoritative_report(app_role_engine, seeded):
    case, run, token, _, evidence = seeded
    before = assemble_report(app_role_engine, run)
    package = load_package(app_role_engine, token.plaintext_token, case, run)
    result = asyncio.run(generate_draft(package, MockProvider()))
    assert result.status == "DRAFT"
    assert result.draft.summary[0].evidence_ids == [str(evidence.evidence_id)]
    assert assemble_report(app_role_engine, run) == before


def test_auth_case_run_and_revocation_boundaries(
    app_role_engine, superuser_engine, seeded
):
    case, run, token, other, _ = seeded
    for credential, requested_case, requested_run in [
        ("invalid", case, run),
        (other.plaintext_token, case, run),
        (token.plaintext_token, uuid4(), run),
        (token.plaintext_token, case, uuid4()),
    ]:
        with pytest.raises(ValueError, match="UNAVAILABLE"):
            load_package(app_role_engine, credential, requested_case, requested_run)
    revoke_token(superuser_engine, token.token_id)
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        load_package(app_role_engine, token.plaintext_token, case, run)


def test_persisted_unresolved_evidence_rejected(
    app_role_engine, superuser_engine, seeded
):
    case, run, token, _, evidence = seeded
    with superuser_engine.begin() as conn:
        # Array references can exist without a matching evidence row.
        conn.execute(
            text("UPDATE findings SET evidence_ids=:ids WHERE investigation_run_id=:r"),
            {"ids": [uuid4()], "r": run},
        )
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        load_package(app_role_engine, token.plaintext_token, case, run)


def test_existing_evidence_from_other_run_rejected(
    app_role_engine, superuser_engine, seeded
):
    case, run, token, _, evidence = seeded
    other_run = uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO investigation_runs "
                "(investigation_run_id,case_id,status,started_at,created_at) "
                "VALUES (:r,:c,'FAILED',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"r": other_run, "c": case},
        )
    agent = setup_agent_run(superuser_engine, other_run)
    foreign = record_evidence(
        app_role_engine,
        other_run,
        "alerted_transaction",
        "transactions",
        evidence.reference_id,
        agent,
    )
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE findings SET evidence_ids=:ids WHERE investigation_run_id=:r"),
            {"ids": [foreign.evidence_id], "r": run},
        )
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        load_package(app_role_engine, token.plaintext_token, case, run)


def test_loader_database_error_redacted(app_role_engine, monkeypatch):
    def fail(*args):
        raise RuntimeError("secret password from database")

    monkeypatch.setattr("meridian.copilot.drafts.verify_token", fail)
    with pytest.raises(ValueError, match="^UNAVAILABLE$"):
        load_package(app_role_engine, "unused", uuid4(), uuid4())
