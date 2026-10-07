import typing
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from meridian.api.cases import get_engine
from meridian.identity.authentication import get_auth_engine
from meridian.main import app
from tests.auth_helpers import get_auth_headers
from tests.test_human_decisions import _seed_case
from tests.test_identity_tokens import _cleanup_user, _seed_user


@pytest.fixture
def client(app_role_engine: Engine) -> typing.Generator[TestClient, None, None]:
    app.dependency_overrides[get_engine] = lambda: app_role_engine
    app.dependency_overrides[get_auth_engine] = lambda: app_role_engine
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_unauthenticated_requests(client: TestClient) -> None:
    # missing token
    res = client.post(
        "/cases",
        json={
            "customer_id": str(uuid.uuid4()),
            "alert_type": "test",
            "alert_reasons": [],
        },
    )
    assert res.status_code == 401

    # invalid token
    res = client.post(
        "/cases",
        json={
            "customer_id": str(uuid.uuid4()),
            "alert_type": "test",
            "alert_reasons": [],
        },
        headers={"Authorization": "Bearer invalid_token"},
    )
    assert res.status_code == 401


def test_authorization_roles(
    client: TestClient, superuser_engine: Engine, app_role_engine: Engine
) -> None:
    analyst_uid = _seed_user(superuser_engine, "analyst")
    try:
        headers = get_auth_headers(superuser_engine, analyst_uid)

        # analyst cannot create case
        res = client.post(
            "/cases",
            json={
                "customer_id": str(uuid.uuid4()),
                "alert_type": "test",
                "alert_reasons": [],
            },
            headers=headers,
        )
        assert res.status_code == 403
    finally:
        _cleanup_user(superuser_engine, analyst_uid)


def test_case_visibility_analyst(
    client: TestClient, superuser_engine: Engine, app_role_engine: Engine
) -> None:
    analyst_uid = _seed_user(superuser_engine, "analyst")
    senior_uid = _seed_user(superuser_engine, "senior_analyst")
    case_id = None
    try:
        analyst_headers = get_auth_headers(superuser_engine, analyst_uid)
        senior_headers = get_auth_headers(superuser_engine, senior_uid)

        case_id = _seed_case(superuser_engine, "OPEN", assigned_analyst_id=senior_uid)

        # analyst should get 404 for unassigned case
        res = client.get(f"/cases/{case_id}/audit-trail", headers=analyst_headers)
        assert res.status_code == 404

        # senior analyst can see all cases
        res = client.get(f"/cases/{case_id}/audit-trail", headers=senior_headers)
        assert res.status_code == 200

    finally:
        if case_id:
            with superuser_engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM audit_events WHERE case_id = :cid"),
                    {"cid": case_id},
                )
                conn.execute(
                    text("DELETE FROM cases WHERE case_id = :cid"),
                    {"cid": case_id},
                )
                conn.execute(
                    text(
                        "DELETE FROM alerts WHERE alert_id IN "
                        "(SELECT alert_id FROM cases WHERE case_id = :cid)"
                    ),
                    {"cid": case_id},
                )
        _cleanup_user(superuser_engine, analyst_uid)
        _cleanup_user(superuser_engine, senior_uid)
