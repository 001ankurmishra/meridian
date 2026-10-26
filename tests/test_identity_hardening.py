"""Credential lifecycle, privilege boundaries and atomic decision regression tests."""

import os
import subprocess
import sys
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from meridian.api.cases import get_engine
from meridian.identity import tokens
from meridian.identity.authentication import get_auth_engine
from meridian.main import app
from meridian.review.decisions import record_human_decision
from meridian.review.errors import UnauthorizedDecisionError
from tests.test_human_decisions import _seed_case
from tests.test_identity_tokens import _cleanup_user, _seed_user


@pytest.fixture
def user(superuser_engine: Engine) -> Generator[uuid.UUID, None, None]:
    uid = _seed_user(superuser_engine, "senior_analyst")
    yield uid
    _cleanup_user(superuser_engine, uid)


@pytest.mark.parametrize("ttl", [0, -1, 169])
def test_invalid_token_lifetime(superuser_engine: Engine, user: uuid.UUID, ttl: int):
    with pytest.raises(ValueError, match="TTL"):
        tokens.issue_token(superuser_engine, user, ttl_hours=ttl)
    with superuser_engine.connect() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM api_tokens WHERE user_id = :uid"),
                {"uid": user},
            )
            == 0
        )


def test_current_role_and_deactivation(superuser_engine: Engine, user: uuid.UUID):
    token = tokens.issue_token(superuser_engine, user)
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET role = 'admin' WHERE user_id = :uid"), {"uid": user}
        )
    assert tokens.verify_token(superuser_engine, token.plaintext_token).role == "admin"
    assert tokens.deactivate_user(superuser_engine, user)
    assert not tokens.deactivate_user(superuser_engine, user)
    assert tokens.verify_token(superuser_engine, token.plaintext_token) is None
    with pytest.raises(ValueError, match="inactive"):
        tokens.issue_token(superuser_engine, user)
    with superuser_engine.connect() as conn:
        events = conn.execute(
            text(
                "SELECT actor_type, actor_id, action, input_summary, "
                "output_summary FROM audit_events WHERE "
                "input_summary->>'user_id' = :uid"
            ),
            {"uid": str(user)},
        ).all()
        assert len(events) == 2
        assert {row.action for row in events} == {"TOKEN_ISSUED", "USER_DEACTIVATED"}
        assert all(row.actor_id.startswith("database:") for row in events)
        assert token.plaintext_token not in repr(events)
        assert str(token.token_id) in repr(events)


def test_runtime_cannot_write_identity(app_role_engine: Engine, user: uuid.UUID):
    for table in ("users", "api_tokens"):
        with app_role_engine.connect() as conn:
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert not conn.scalar(
                    text(
                        "SELECT has_table_privilege(current_user, :table, :privilege)"
                    ),
                    {"table": table, "privilege": privilege},
                )
    with pytest.raises(DBAPIError):
        tokens.issue_token(app_role_engine, user)


@pytest.mark.parametrize("operation", ["issue", "revoke", "revoke_all", "deactivate"])
def test_identity_audit_failure_rolls_back(
    superuser_engine: Engine,
    user: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
):
    token = tokens.issue_token(superuser_engine, user)

    def fail(*args, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(tokens, "record_audit_event", fail)
    with pytest.raises(RuntimeError, match="injected"):
        if operation == "issue":
            tokens.issue_token(superuser_engine, user)
        elif operation == "revoke":
            tokens.revoke_token(superuser_engine, token.token_id)
        elif operation == "revoke_all":
            tokens.revoke_all_tokens_for_user(superuser_engine, user)
        else:
            tokens.deactivate_user(superuser_engine, user)
    assert tokens.verify_token(superuser_engine, token.plaintext_token) is not None
    with superuser_engine.connect() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM api_tokens WHERE user_id = :uid"),
                {"uid": user},
            )
            == 1
        )


def test_cli_requires_explicit_maintenance_credentials():
    env = dict(os.environ, PYTHONPATH=str(Path("src").resolve()))
    env.pop("MAINTENANCE_DATABASE_URL", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "meridian.identity.cli",
            "issue",
            "synthetic@example.com",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1
    assert "MAINTENANCE_DATABASE_URL" in result.stderr
    assert "Token:" not in result.stdout


def test_privileged_cli_provisions_and_revokes(
    superuser_engine: Engine, user: uuid.UUID
):
    env = dict(os.environ, MAINTENANCE_DATABASE_URL=os.environ["DATABASE_URL"],
               PYTHONPATH=str(Path("src").resolve()))
    command = [sys.executable, "-m", "meridian.identity.cli"]
    issued = subprocess.run(
        command + ["issue", f"test_{user}@example.com", "--ttl", "1"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert issued.returncode == 0
    token = next(
        line.split()[-1]
        for line in issued.stdout.splitlines()
        if line.startswith("Token: ")
    )
    info = tokens.verify_token(superuser_engine, token)
    assert info is not None
    revoked = subprocess.run(
        command + ["revoke", str(info.token_id)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert revoked.returncode == 0
    assert token not in revoked.stdout + revoked.stderr
    assert tokens.verify_token(superuser_engine, token) is None
    assert not tokens.revoke_token(superuser_engine, info.token_id)


@pytest.mark.parametrize(
    "actor_field", ["actor_user_id", "actor_id", "role", "user_id"]
)
def test_actor_identity_rejected_and_real_actor_audited(
    app_role_engine: Engine,
    superuser_engine: Engine,
    user: uuid.UUID,
    actor_field: str,
):
    case = _seed_case(superuser_engine, "OPEN")
    token = tokens.issue_token(superuser_engine, user)
    headers = {"Authorization": f"Bearer {token.plaintext_token}"}
    app.dependency_overrides[get_engine] = lambda: app_role_engine
    app.dependency_overrides[get_auth_engine] = lambda: app_role_engine
    try:
        client = TestClient(app)
        bad = client.post(
            f"/cases/{case}/decision",
            headers=headers,
            json={"action": "APPROVE", actor_field: str(uuid.uuid4())},
        )
        assert bad.status_code == 422
        with superuser_engine.connect() as conn:
            assert (
                conn.scalar(
                    text("SELECT status FROM cases WHERE case_id = :id"), {"id": case}
                )
                == "OPEN"
            )
        from tests.decision_helpers import seed_supported_report
        seed_supported_report(superuser_engine, case)
        response = client.post(
            f"/cases/{case}/decision", headers=headers, json={"action": "APPROVE"}
        )
        assert response.status_code == 200
        with superuser_engine.connect() as conn:
            assert conn.scalar(
                text("SELECT actor_id FROM audit_events WHERE case_id = :id"),
                {"id": case},
            ) == str(user)
    finally:
        app.dependency_overrides.clear()
        with superuser_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM audit_events WHERE case_id = :id"), {"id": case}
            )
            from tests.db_cleanup import clean_investigation_run_dependencies
            run_ids = conn.execute(text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id=:id"
            ), {"id": case}).scalars().all()
            for run_id in run_ids:
                clean_investigation_run_dependencies(conn, run_id)
            conn.execute(text("DELETE FROM cases WHERE case_id = :id"), {"id": case})


def test_decision_audit_failure_rolls_back_case(
    app_role_engine: Engine,
    superuser_engine: Engine,
    user: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
):
    from meridian.review import decisions
    from tests.db_cleanup import clean_investigation_run_dependencies
    from tests.decision_helpers import seed_supported_report

    case = _seed_case(superuser_engine, "OPEN")
    run = seed_supported_report(superuser_engine, case)

    def fail(*args, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(decisions, "record_audit_event", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            record_human_decision(app_role_engine, case, user, "APPROVE")
        with superuser_engine.connect() as conn:
            row = conn.execute(
                text("SELECT status, closed_at FROM cases WHERE case_id = :id"),
                {"id": case},
            ).one()
            assert row.status == "OPEN" and row.closed_at is None
            assert (
                conn.scalar(
                    text("SELECT count(*) FROM audit_events WHERE case_id = :id"),
                    {"id": case},
                )
                == 0
            )
        tokens.deactivate_user(superuser_engine, user)
        with pytest.raises(UnauthorizedDecisionError, match="inactive"):
            record_human_decision(app_role_engine, case, user, "APPROVE")
    finally:
        with superuser_engine.begin() as conn:
            clean_investigation_run_dependencies(conn, run)
            conn.execute(text("DELETE FROM cases WHERE case_id = :id"), {"id": case})
