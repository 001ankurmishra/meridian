import os
import typing
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from meridian.api.cases import get_engine
from meridian.identity.authentication import get_auth_engine
from meridian.main import app
from tests.auth_helpers import get_auth_headers
from tests.db_cleanup import clean_investigation_run_dependencies
from tests.test_e2e_worked_example import _find_rahul_fixture


@pytest.fixture
def client(app_role_engine: Engine) -> typing.Generator[TestClient, None, None]:
    app.dependency_overrides[get_engine] = lambda: app_role_engine
    app.dependency_overrides[get_auth_engine] = lambda: app_role_engine
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_analyst(superuser_engine: Engine) -> uuid.UUID:
    uid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (user_id, email, role, created_at) "
                "VALUES (:uid, :email, 'analyst', :now)"
            ),
            {"uid": uid, "email": f"test_{uid}@example.com",
             "now": datetime.now(timezone.utc)}
        )
    return uid


def _seed_senior(superuser_engine: Engine) -> uuid.UUID:
    uid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (user_id, email, role, created_at) "
                "VALUES (:uid, :email, 'senior_analyst', :now)"
            ),
            {"uid": uid, "email": f"test_senior_{uid}@example.com",
             "now": datetime.now(timezone.utc)}
        )
    return uid


def _cleanup_case_data(
    superuser_engine: Engine,
    case_id: uuid.UUID | None,
    alert_id: uuid.UUID | None,
    analyst_id: uuid.UUID | None = None,
) -> None:
    with superuser_engine.begin() as conn:
        if case_id is not None:
            if alert_id is None:
                alert_id = conn.execute(
                    text("SELECT alert_id FROM cases WHERE case_id = :cid"),
                    {"cid": case_id}
                ).scalar()
            # find inv run
            run_id = conn.execute(
                text("SELECT investigation_run_id FROM investigation_runs "
                     "WHERE case_id = :cid"),
                {"cid": case_id}
            ).scalar()

            conn.execute(
                text("DELETE FROM audit_events WHERE case_id = :cid"),
                {"cid": case_id}
            )
            if run_id is not None:
                clean_investigation_run_dependencies(conn, investigation_run_id=run_id)
            conn.execute(
                text("DELETE FROM cases WHERE case_id = :cid"),
                {"cid": case_id}
            )

        if alert_id is not None:
            conn.execute(
                text("DELETE FROM alerts WHERE alert_id = :aid"),
                {"aid": alert_id}
            )

        if analyst_id is not None:
            conn.execute(
                text("DELETE FROM api_tokens WHERE user_id = :uid"),
                {"uid": analyst_id}
            )
            conn.execute(
                text("DELETE FROM users WHERE user_id = :uid"),
                {"uid": analyst_id}
            )


def test_api_happy_path(
    client: TestClient,
    superuser_engine: Engine,
    app_role_engine: Engine,
) -> None:
    loader_url = os.environ.get("LOADER_DATABASE_URL")
    if not loader_url:
        pytest.skip("LOADER_DATABASE_URL not set")

    # ==================== PRE-CLEAN ====================
    from tests.db_cleanup import (
        clean_investigation_run_dependencies,
    )
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events"))
        clean_investigation_run_dependencies(conn)
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))

    from meridian.loader.main import main as loader_main
    loader_main()

    customer_id, account_id, transaction_id = _find_rahul_fixture()

    analyst_id = _seed_analyst(superuser_engine)
    senior_id = _seed_senior(superuser_engine)
    case_id: uuid.UUID | None = None
    alert_id: uuid.UUID | None = None

    try:
        headers = get_auth_headers(superuser_engine, senior_id)

        # POST /cases
        create_payload = {
            "customer_id": str(customer_id),
            "alert_type": "large_transaction",
            "alert_reasons": ["large_transaction", "new_beneficiary"],
            "transaction_id": str(transaction_id),
            "source_system": "api-e2e-test"
        }
        res_create = client.post("/cases", json=create_payload, headers=headers)
        assert res_create.status_code == 201, res_create.text
        create_data = res_create.json()
        case_id = uuid.UUID(create_data["case_id"])
        alert_id = uuid.UUID(create_data["alert_id"])

        # Assign analyst so APPROVE is authorized
        with superuser_engine.begin() as conn:
            conn.execute(
                text("UPDATE cases SET assigned_analyst_id = :aid "
                     "WHERE case_id = :cid"),
                {"aid": analyst_id, "cid": case_id}
            )

        headers = get_auth_headers(superuser_engine, analyst_id)

        # POST /cases/{case_id}/investigate
        res_inv = client.post(f"/cases/{case_id}/investigate", headers=headers)
        assert res_inv.status_code == 200, res_inv.text
        assert res_inv.json()["status"] == "COMPLETE"

        # GET /cases/{case_id}/report
        res_report = client.get(f"/cases/{case_id}/report", headers=headers)
        assert res_report.status_code == 200, res_report.text
        report_data = res_report.json()
        assert len(report_data["findings"]) > 0
        assert len(report_data["evidence"]) > 0
        assert len(report_data["recommendations"]) > 0
        assert len(report_data["applicable_policies"]) > 0

        # POST /cases/{case_id}/decision
        decision_payload = {
            "action": "APPROVE"
        }
        res_decision = client.post(
            f"/cases/{case_id}/decision", json=decision_payload, headers=headers
        )
        assert res_decision.status_code == 200, res_decision.text
        assert res_decision.json()["new_status"] == "CLOSED_APPROVED"

        # GET /cases/{case_id}/audit-trail
        res_audit = client.get(f"/cases/{case_id}/audit-trail", headers=headers)
        assert res_audit.status_code == 200, res_audit.text
        audit_data = res_audit.json()
        assert audit_data["case_status"] == "CLOSED_APPROVED"
        events = audit_data["audit_events"]
        assert len(events) == 1
        assert events[0]["action"] == "CASE_APPROVED"

    finally:
        _cleanup_case_data(superuser_engine, case_id, alert_id, analyst_id)


def test_api_invalid_input(
    client: TestClient, superuser_engine: Engine, app_role_engine: Engine
) -> None:
    # A2
    # must be senior analyst to create case
    analyst_id = _seed_analyst(superuser_engine)
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET role = 'senior_analyst' WHERE user_id = :uid"),
            {"uid": analyst_id}
        )
    headers = get_auth_headers(superuser_engine, analyst_id)

    payload = {
        "customer_id": str(uuid.uuid4()),
        "alert_type": "   ",  # invalid empty/whitespace
        "alert_reasons": ["some_reason"]
    }
    res = client.post("/cases", json=payload, headers=headers)
    assert res.status_code == 422
    _cleanup_case_data(superuser_engine, None, None, analyst_id)


def test_api_investigate_nonexistent(
    client: TestClient, superuser_engine: Engine, app_role_engine: Engine
) -> None:
    # A3
    analyst_id = _seed_analyst(superuser_engine)
    headers = get_auth_headers(superuser_engine, analyst_id)
    nonexistent = uuid.uuid4()
    res = client.post(f"/cases/{nonexistent}/investigate", headers=headers)
    assert res.status_code == 404
    _cleanup_case_data(superuser_engine, None, None, analyst_id)


def test_api_report_nonexistent(
    client: TestClient, superuser_engine: Engine, app_role_engine: Engine
) -> None:
    # A4
    analyst_id = _seed_analyst(superuser_engine)
    headers = get_auth_headers(superuser_engine, analyst_id)
    nonexistent = uuid.uuid4()
    res = client.get(f"/cases/{nonexistent}/report", headers=headers)
    assert res.status_code == 404
    _cleanup_case_data(superuser_engine, None, None, analyst_id)


def test_api_decision_invalid_action(
    client: TestClient, superuser_engine: Engine, app_role_engine: Engine
) -> None:
    # A5
    from tests.test_human_decisions import _seed_case
    actor_id = None
    case_id = None

    try:
        actor_id = _seed_analyst(superuser_engine)
        headers = get_auth_headers(superuser_engine, actor_id)
        case_id = _seed_case(superuser_engine, "OPEN", assigned_analyst_id=actor_id)

        payload = {
            "action": "INVALID_ACTION"
        }
        res = client.post(f"/cases/{case_id}/decision", json=payload, headers=headers)
        assert res.status_code == 422

        # assert UNCHANGED
        with superuser_engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM cases WHERE case_id = :cid"),
                {"cid": case_id}
            ).scalar()
            assert status == "OPEN"

            # also verify audit events
            count = conn.execute(
                text("SELECT count(*) FROM audit_events WHERE case_id = :cid"),
                {"cid": case_id}
            ).scalar()
            assert count == 0

    finally:
        _cleanup_case_data(
            superuser_engine, case_id=case_id, alert_id=None, analyst_id=actor_id
        )


def test_api_audit_trail_nonexistent(
    client: TestClient, superuser_engine: Engine, app_role_engine: Engine
) -> None:
    # A6
    analyst_id = _seed_analyst(superuser_engine)
    headers = get_auth_headers(superuser_engine, analyst_id)
    nonexistent = uuid.uuid4()
    res = client.get(f"/cases/{nonexistent}/audit-trail", headers=headers)
    assert res.status_code == 404
    _cleanup_case_data(superuser_engine, None, None, analyst_id)


def test_api_safety_invariant_report_readonly(
    client: TestClient,
    superuser_engine: Engine,
    app_role_engine: Engine,
) -> None:
    # A7
    loader_url = os.environ.get("LOADER_DATABASE_URL")
    if not loader_url:
        pytest.skip("LOADER_DATABASE_URL not set")

    customer_id, account_id, transaction_id = _find_rahul_fixture()

    case_id: uuid.UUID | None = None
    alert_id: uuid.UUID | None = None
    analyst_id: uuid.UUID | None = None

    try:
        senior_id = _seed_senior(superuser_engine)
        analyst_id = _seed_analyst(superuser_engine)
        headers = get_auth_headers(superuser_engine, senior_id)
        # POST /cases
        create_payload = {
            "customer_id": str(customer_id),
            "alert_type": "large_transaction",
            "alert_reasons": ["large_transaction"],
            "transaction_id": str(transaction_id),
            "source_system": "api-e2e-test"
        }
        res_create = client.post("/cases", json=create_payload, headers=headers)
        assert res_create.status_code == 201

        # Assign analyst so they can see it (visibility rule)
        case_id_str = res_create.json()["case_id"]
        with superuser_engine.begin() as conn:
            conn.execute(
                text("UPDATE cases SET assigned_analyst_id = :aid "
                     "WHERE case_id = :cid"),
                {"aid": analyst_id, "cid": case_id_str}
            )

        headers = get_auth_headers(superuser_engine, analyst_id)
        case_id = uuid.UUID(res_create.json()["case_id"])
        alert_id = uuid.UUID(res_create.json()["alert_id"])

        # Assign analyst to bypass visibility
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE cases SET assigned_analyst_id = :aid "
                    "WHERE case_id = :cid"
                ),
                {"aid": analyst_id, "cid": case_id}
            )

        # POST /cases/{case_id}/investigate
        res_inv = client.post(f"/cases/{case_id}/investigate", headers=headers)
        assert res_inv.status_code == 200

        with superuser_engine.connect() as conn:
            status_before = conn.execute(
                text("SELECT status FROM cases WHERE case_id = :cid"),
                {"cid": case_id}
            ).scalar()

        # GET /cases/{case_id}/report
        res_report = client.get(f"/cases/{case_id}/report", headers=headers)
        assert res_report.status_code == 200

        # Check status is unchanged
        with superuser_engine.connect() as conn:
            status_after = conn.execute(
                text("SELECT status FROM cases WHERE case_id = :cid"),
                {"cid": case_id}
            ).scalar()

        assert status_before == status_after
        assert status_after == "OPEN"

    finally:
        _cleanup_case_data(superuser_engine, case_id, alert_id, analyst_id)
