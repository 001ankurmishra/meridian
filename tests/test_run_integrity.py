"""Real PostgreSQL admission and concurrent HTTP invocation tests."""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from meridian.agents.policy.policy_agent import PolicyEvidenceInsufficient
from meridian.api.cases import get_engine
from meridian.identity.authentication import get_auth_engine
from meridian.main import app
from meridian.orchestration.errors import InvestigationError
from meridian.orchestration.investigation_run import create_investigation_run
from tests.auth_helpers import get_auth_headers
from tests.db_cleanup import clean_investigation_run_dependencies
from tests.test_human_decisions import _seed_case, _seed_user


@pytest.fixture
def case_context(superuser_engine, app_role_engine):
    actor = _seed_user(superuser_engine, "senior_analyst")
    case = _seed_case(superuser_engine, "OPEN")
    headers = get_auth_headers(superuser_engine, actor)
    app.dependency_overrides[get_engine] = lambda: app_role_engine
    app.dependency_overrides[get_auth_engine] = lambda: app_role_engine
    try:
        yield case, headers
    finally:
        app.dependency_overrides.clear()
        with superuser_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM audit_events WHERE case_id=:cid"), {"cid": case}
            )
            ids = (
                conn.execute(
                    text(
                        "SELECT investigation_run_id FROM investigation_runs "
                        "WHERE case_id=:cid"
                    ),
                    {"cid": case},
                )
                .scalars()
                .all()
            )
            for run in ids:
                clean_investigation_run_dependencies(conn, run)
            conn.execute(text("DELETE FROM cases WHERE case_id=:cid"), {"cid": case})


@pytest.mark.parametrize(
    "status", ["IN_PROGRESS", "COMPLETE", "INCOMPLETE_INSUFFICIENT_EVIDENCE"]
)
def test_sequential_non_failed_run_is_rejected(
    case_context, app_role_engine, superuser_engine, status
):
    case, _ = case_context
    first = create_investigation_run(app_role_engine, case)
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE investigation_runs SET status=:s WHERE case_id=:cid"),
            {"s": status, "cid": case},
        )
    with pytest.raises(InvestigationError, match="non-failed"):
        create_investigation_run(app_role_engine, case)
    with app_role_engine.connect() as conn:
        assert conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id=:cid"
            ),
            {"cid": case},
        ).scalars().all() == [first.investigation_run_id]


def test_failed_retry_preserves_history_and_closed_case_rejects(
    case_context, app_role_engine, superuser_engine
):
    case, _ = case_context
    first = create_investigation_run(app_role_engine, case)
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE investigation_runs SET status='FAILED' WHERE case_id=:c"),
            {"c": case},
        )
    second = create_investigation_run(app_role_engine, case)
    assert second.investigation_run_id != first.investigation_run_id
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE investigation_runs SET status='FAILED' WHERE case_id=:c"),
            {"c": case},
        )
        conn.execute(
            text("UPDATE cases SET status='ESCALATED' WHERE case_id=:c"), {"c": case}
        )
    with pytest.raises(InvestigationError, match="not OPEN"):
        create_investigation_run(app_role_engine, case)


def test_concurrent_http_requests_start_only_one_run(case_context, app_role_engine):
    case, headers = case_context
    barrier = threading.Barrier(2)

    def synchronized_start(engine, case_id):
        # Both real requests have passed the old preliminary case SELECT.
        barrier.wait(timeout=10)
        return create_investigation_run(engine, case_id)

    def request():
        with TestClient(app) as client:
            return client.post(f"/cases/{case}/investigate", headers=headers)

    with (
        patch(
            "meridian.orchestration.investigation_orchestrator.create_investigation_run",
            side_effect=synchronized_start,
        ),
        patch(
            "meridian.orchestration.investigation_orchestrator.run_policy_agent",
            return_value=PolicyEvidenceInsufficient(),
        ),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        futures = [pool.submit(request) for _ in range(2)]
        responses = [f.result(timeout=20) for f in futures]
    assert sorted(r.status_code for r in responses) == [200, 422]
    assert next(r for r in responses if r.status_code == 200).json()["status"] == (
        "INCOMPLETE_INSUFFICIENT_EVIDENCE"
    )
    with app_role_engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM investigation_runs WHERE case_id=:c"),
                {"c": case},
            ).scalar_one()
            == 1
        )


def test_legacy_ambiguous_reports_are_rejected(case_context, superuser_engine):
    case, headers = case_context
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO investigation_runs "
                "(investigation_run_id,case_id,status,started_at,created_at) "
                "SELECT gen_random_uuid(),:c,'COMPLETE',now(),now() "
                "FROM generate_series(1,2)"
            ),
            {"c": case},
        )
    with TestClient(app) as client:
        response = client.get(f"/cases/{case}/report", headers=headers)
    assert response.status_code == 422
    assert response.json()["detail"] == "Ambiguous investigation history."
