"""Integration and static configuration tests for Docker Compose APP_DATABASE_URL.

Verifies:
1. Static Compose configuration: app service receives APP_DATABASE_URL with
   application-role credentials, matching the database init configuration.
2. Runtime application-role integration: validated test database credentials work
   through the real engine, authentication, and POST /cases route without
   dependency overrides, verifying non-superuser role and clean teardown.
3. Missing application URL fails closed: verifies RuntimeError propagates from
   get_app_engine() without falling back to DATABASE_URL.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
import sqlalchemy as sa
import yaml  # type: ignore[import-untyped]
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from meridian.api.cases import get_engine
from meridian.config import settings
from meridian.identity.authentication import get_auth_engine
from meridian.identity.tokens import issue_token
from meridian.main import app
from meridian.testing.guard import (
    APPROVED_TEST_DB,
    APPROVED_TEST_PORT,
    verify_test_database_safety,
)


def parse_compose_env_list_or_map(env_data: Any) -> Dict[str, str]:
    """Parse Compose environment block supporting either a dict or list of strings."""
    result: Dict[str, str] = {}
    if isinstance(env_data, dict):
        for k, v in env_data.items():
            result[str(k)] = str(v) if v is not None else ""
    elif isinstance(env_data, list):
        for item in env_data:
            if isinstance(item, str):
                if "=" in item:
                    k, v = item.split("=", 1)
                    result[k] = v
                elif ":" in item:
                    k, v = item.split(":", 1)
                    result[k.strip()] = v.strip()
    return result


def resolve_compose_interpolation(
    val: str, env: Dict[str, str] | None = None
) -> str:
    """Resolve ${VAR} and ${VAR:-default} per Compose interpolation semantics."""
    if env is None:
        env = dict(os.environ)

    pattern = re.compile(r"\$\{([A-Za-z0-9_]+)(?::-([^}]*))?\}")

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default_val = match.group(2)
        env_val = env.get(var_name)
        if env_val is not None and env_val != "":
            return env_val
        if default_val is not None:
            return default_val
        return ""

    return pattern.sub(_replace, val)


def test_compose_app_receives_app_role_url() -> None:
    """Test 1: Static Compose configuration.

    Asserts that docker-compose.yml configures APP_DATABASE_URL for the app
    service with application-role credentials, distinct from superuser, and
    matching db service interpolation.
    """
    compose_path = Path(__file__).resolve().parent.parent / "docker-compose.yml"
    assert compose_path.is_file(), f"docker-compose.yml not found at {compose_path}"

    with compose_path.open("r", encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)

    services = compose_data.get("services", {})
    assert "app" in services, "app service missing from docker-compose.yml"
    assert "db" in services, "db service missing from docker-compose.yml"

    app_env_raw = parse_compose_env_list_or_map(services["app"].get("environment"))
    db_env_raw = parse_compose_env_list_or_map(services["db"].get("environment"))

    # Assert LOADER_DATABASE_URL is absent from app service
    assert "LOADER_DATABASE_URL" not in app_env_raw, (
        "LOADER_DATABASE_URL must not be supplied to app service"
    )

    # Assert APP_DATABASE_URL is present in app service
    assert "APP_DATABASE_URL" in app_env_raw, (
        "APP_DATABASE_URL missing from app service environment"
    )
    raw_app_db_url = app_env_raw["APP_DATABASE_URL"]

    # Assert exact interpolation matching db service
    assert "${APP_DB_USER:-meridian_app}" in raw_app_db_url, (
        "APP_DATABASE_URL must use ${APP_DB_USER:-meridian_app} interpolation"
    )
    assert "${APP_DB_PASSWORD:-meridian_app_pass}" in raw_app_db_url, (
        "APP_DATABASE_URL must use ${APP_DB_PASSWORD:-meridian_app_pass} interpolation"
    )
    assert db_env_raw.get("APP_DB_USER") == "${APP_DB_USER:-meridian_app}", (
        "db service APP_DB_USER interpolation mismatch"
    )
    expected_db_pw = "${APP_DB_PASSWORD:-meridian_app_pass}"
    assert db_env_raw.get("APP_DB_PASSWORD") == expected_db_pw, (
        "db service APP_DB_PASSWORD interpolation mismatch"
    )

    # Resolve with empty env to test default Compose semantics
    empty_env: Dict[str, str] = {}
    resolved_app_url_str = resolve_compose_interpolation(raw_app_db_url, empty_env)
    resolved_db_name = resolve_compose_interpolation(
        db_env_raw.get("POSTGRES_DB", ""), empty_env
    )
    resolved_superuser = resolve_compose_interpolation(
        db_env_raw.get("POSTGRES_USER", ""), empty_env
    )
    resolved_app_user = resolve_compose_interpolation(
        db_env_raw.get("APP_DB_USER", ""), empty_env
    )
    resolved_app_pass = resolve_compose_interpolation(
        db_env_raw.get("APP_DB_PASSWORD", ""), empty_env
    )
    resolved_existing_db_url = resolve_compose_interpolation(
        app_env_raw.get("DATABASE_URL", ""), empty_env
    )

    app_url = make_url(resolved_app_url_str)
    existing_url = make_url(resolved_existing_db_url)

    assert app_url.drivername == "postgresql+psycopg"
    assert app_url.host == "db"
    assert app_url.port == 5432
    assert app_url.database == resolved_db_name == "meridian_db"
    assert app_url.username == resolved_app_user == "meridian_app"
    assert app_url.password == resolved_app_pass == "meridian_app_pass"

    # Username must differ from database superuser
    assert app_url.username != resolved_superuser
    # Username must differ from existing app DATABASE_URL username
    assert app_url.username != existing_url.username


def test_compose_app_url_works_through_real_engine_path(
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 2: Runtime application-role integration.

    Exercises the real configuration -> get_app_engine() -> authentication/API path
    against the guard-validated disposable test database without dependency overrides.
    """
    # 1. Safety verification
    target_identity, _ = verify_test_database_safety()
    assert target_identity.database == APPROVED_TEST_DB == "meridian_test"
    assert target_identity.port == APPROVED_TEST_PORT == 55432
    assert target_identity.normalized_host in {"127.0.0.1", "localhost"}
    assert target_identity.marker_value == "on"

    # 2. Derive Compose application role credentials from docker-compose.yml
    compose_path = Path(__file__).resolve().parent.parent / "docker-compose.yml"
    with compose_path.open("r", encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)
    app_env_raw = parse_compose_env_list_or_map(
        compose_data["services"]["app"]["environment"]
    )
    resolved_app_url_str = resolve_compose_interpolation(
        app_env_raw["APP_DATABASE_URL"], {}
    )
    compose_parsed = make_url(resolved_app_url_str)
    compose_app_user = compose_parsed.username or "meridian_app"
    compose_app_pass = compose_parsed.password or "meridian_app_pass"

    # 3. Construct URL pointing to the validated disposable test database
    test_app_url = (
        f"postgresql+psycopg://{compose_app_user}:{compose_app_pass}@"
        f"{target_identity.normalized_host}:{target_identity.port}/"
        f"{target_identity.database}"
    )

    # 4. Role verification: role connects, matches current_user, and is non-superuser
    role_check_engine = sa.create_engine(test_app_url, poolclass=sa.pool.NullPool)
    try:
        with role_check_engine.connect() as conn:
            current_user = conn.scalar(text("SELECT current_user;"))
            assert current_user == compose_app_user
            is_superuser = conn.scalar(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user;")
            )
            assert is_superuser is False
    finally:
        role_check_engine.dispose()

    # 5. Record baseline row counts before test writes
    with superuser_engine.connect() as conn:
        base_cases = conn.scalar(text("SELECT count(*) FROM cases;"))
        base_alerts = conn.scalar(text("SELECT count(*) FROM alerts;"))
        base_customers = conn.scalar(text("SELECT count(*) FROM customers;"))
        base_tokens = conn.scalar(text("SELECT count(*) FROM api_tokens;"))
        base_users = conn.scalar(text("SELECT count(*) FROM users;"))
        base_audit = conn.scalar(text("SELECT count(*) FROM audit_events;"))

    # Preserve and isolate dependency overrides across failure modes
    prior_overrides = dict(app.dependency_overrides)
    app.dependency_overrides.clear()

    user_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None
    alert_id: uuid.UUID | None = None

    try:
        try:
            # Seed test user with senior_analyst role
            user_id = uuid.uuid4()
            now = datetime.now(timezone.utc)
            with superuser_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO users (user_id, email, role, created_at) "
                        "VALUES (:uid, :email, 'senior_analyst', :now)"
                    ),
                    {
                        "uid": user_id,
                        "email": f"test_senior_{user_id}@example.com",
                        "now": now,
                    },
                )

            token = issue_token(
                superuser_engine, user_id, label="test-compose-runtime-token"
            )

            # Seed synthetic customer
            customer_id = uuid.uuid4()
            with superuser_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO customers ("
                        "customer_id, full_name, is_synthetic, created_at"
                        ") VALUES (:cid, :name, true, :now)"
                    ),
                    {
                        "cid": customer_id,
                        "name": f"Customer {customer_id}",
                        "now": now,
                    },
                )

            # Monkeypatch settings.app_database_url
            monkeypatch.setattr(settings, "app_database_url", test_app_url)

            # Clear LRU caches
            get_engine.cache_clear()
            get_auth_engine.cache_clear()

            # Assert engines resolve to application role
            assert get_engine().url.username == compose_app_user
            assert get_auth_engine().url.username == compose_app_user

            # Submit valid POST /cases request through TestClient
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {token.plaintext_token}"}
            payload = {
                "customer_id": str(customer_id),
                "alert_type": "rapid_movement",
                "alert_reasons": ["velocity_threshold"],
                "source_system": "compose-runtime-test",
            }

            res = client.post("/cases", json=payload, headers=headers)
            assert res.status_code == 201, f"POST /cases failed: {res.text}"

            res_data = res.json()
            case_id = uuid.UUID(res_data["case_id"])
            alert_id = uuid.UUID(res_data["alert_id"])

            # Verify rows persisted in DB using superuser_engine
            with superuser_engine.connect() as conn:
                alert_row = conn.execute(
                    text(
                        "SELECT customer_id, alert_type FROM alerts "
                        "WHERE alert_id = :aid"
                    ),
                    {"aid": alert_id},
                ).mappings().fetchone()
                assert alert_row is not None
                assert alert_row["customer_id"] == customer_id
                assert alert_row["alert_type"] == "rapid_movement"

                case_row = conn.execute(
                    text("SELECT alert_id, status FROM cases WHERE case_id = :cid"),
                    {"cid": case_id},
                ).mappings().fetchone()
                assert case_row is not None
                assert case_row["alert_id"] == alert_id
                assert case_row["status"] == "OPEN"

        finally:
            # Guaranteed cleanup in reverse FK dependency order
            with superuser_engine.begin() as conn:
                if case_id is not None:
                    conn.execute(
                        text("DELETE FROM audit_events WHERE case_id = :cid"),
                        {"cid": case_id},
                    )
                    conn.execute(
                        text("DELETE FROM cases WHERE case_id = :cid"),
                        {"cid": case_id},
                    )
                if alert_id is not None:
                    conn.execute(
                        text("DELETE FROM alerts WHERE alert_id = :aid"),
                        {"aid": alert_id},
                    )
                if customer_id is not None:
                    conn.execute(
                        text("DELETE FROM customers WHERE customer_id = :cid"),
                        {"cid": customer_id},
                    )
                if user_id is not None:
                    conn.execute(
                        text("DELETE FROM api_tokens WHERE user_id = :uid"),
                        {"uid": user_id},
                    )
                    conn.execute(
                        text("DELETE FROM users WHERE user_id = :uid"),
                        {"uid": user_id},
                    )

            # Verify table counts return to baseline
            with superuser_engine.connect() as conn:
                assert conn.scalar(text("SELECT count(*) FROM cases;")) == base_cases
                assert conn.scalar(text("SELECT count(*) FROM alerts;")) == base_alerts
                cur_c = conn.scalar(text("SELECT count(*) FROM customers;"))
                assert cur_c == base_customers
                cur_t = conn.scalar(text("SELECT count(*) FROM api_tokens;"))
                assert cur_t == base_tokens
                assert conn.scalar(text("SELECT count(*) FROM users;")) == base_users
                cur_a = conn.scalar(text("SELECT count(*) FROM audit_events;"))
                assert cur_a == base_audit
    finally:
        # Guaranteed global state restoration regardless of cleanup success
        get_engine.cache_clear()
        get_auth_engine.cache_clear()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prior_overrides)


def test_missing_app_database_url_fails_closed(
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 3: Missing application URL fails closed.

    Asserts that when APP_DATABASE_URL is absent (None), get_app_engine()
    raises RuntimeError, propagates through FastAPI without falling back to
    DATABASE_URL, and no partial state is persisted.
    """
    # 1. Safety check
    verify_test_database_safety()

    # 2. Record baseline row counts (including audit_events)
    with superuser_engine.connect() as conn:
        base_cases = conn.scalar(text("SELECT count(*) FROM cases;"))
        base_alerts = conn.scalar(text("SELECT count(*) FROM alerts;"))
        base_customers = conn.scalar(text("SELECT count(*) FROM customers;"))
        base_tokens = conn.scalar(text("SELECT count(*) FROM api_tokens;"))
        base_users = conn.scalar(text("SELECT count(*) FROM users;"))
        base_audit = conn.scalar(text("SELECT count(*) FROM audit_events;"))

    # Preserve and isolate dependency overrides across failure modes
    prior_overrides = dict(app.dependency_overrides)
    app.dependency_overrides.clear()

    user_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None

    try:
        try:
            # Seed test user with senior_analyst role and token
            user_id = uuid.uuid4()
            now = datetime.now(timezone.utc)
            with superuser_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO users (user_id, email, role, created_at) "
                        "VALUES (:uid, :email, 'senior_analyst', :now)"
                    ),
                    {
                        "uid": user_id,
                        "email": f"test_senior_{user_id}@example.com",
                        "now": now,
                    },
                )

            token = issue_token(
                superuser_engine, user_id, label="test-missing-app-url-token"
            )

            customer_id = uuid.uuid4()
            with superuser_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO customers ("
                        "customer_id, full_name, is_synthetic, created_at"
                        ") VALUES (:cid, :name, true, :now)"
                    ),
                    {
                        "cid": customer_id,
                        "name": f"Customer {customer_id}",
                        "now": now,
                    },
                )

            # Monkeypatch settings.app_database_url to None
            monkeypatch.setattr(settings, "app_database_url", None)

            # Clear LRU caches
            get_engine.cache_clear()
            get_auth_engine.cache_clear()

            # Confirm superuser database_url is present in settings (proves no fallback)
            assert settings.database_url is not None
            assert "meridian_user" in settings.database_url

            client = TestClient(app, raise_server_exceptions=True)
            headers = {"Authorization": f"Bearer {token.plaintext_token}"}
            payload = {
                "customer_id": str(customer_id),
                "alert_type": "rapid_movement",
                "alert_reasons": ["velocity_threshold"],
                "source_system": "test-fail-closed",
            }

            with pytest.raises(RuntimeError) as exc_info:
                client.post("/cases", json=payload, headers=headers)

            assert "APP_DATABASE_URL is not configured" in str(exc_info.value)

            # Verify failure originated in get_app_engine()
            frames = [f.name for f in exc_info.traceback]
            assert "get_app_engine" in frames, (
                f"Expected get_app_engine in traceback frames: {frames}"
            )

        finally:
            # Database cleanup
            with superuser_engine.begin() as conn:
                if customer_id is not None:
                    conn.execute(
                        text("DELETE FROM customers WHERE customer_id = :cid"),
                        {"cid": customer_id},
                    )
                if user_id is not None:
                    conn.execute(
                        text("DELETE FROM api_tokens WHERE user_id = :uid"),
                        {"uid": user_id},
                    )
                    conn.execute(
                        text("DELETE FROM users WHERE user_id = :uid"),
                        {"uid": user_id},
                    )

            with superuser_engine.connect() as conn:
                assert conn.scalar(text("SELECT count(*) FROM cases;")) == base_cases
                assert conn.scalar(text("SELECT count(*) FROM alerts;")) == base_alerts
                cur_c = conn.scalar(text("SELECT count(*) FROM customers;"))
                assert cur_c == base_customers
                cur_t = conn.scalar(text("SELECT count(*) FROM api_tokens;"))
                assert cur_t == base_tokens
                assert conn.scalar(text("SELECT count(*) FROM users;")) == base_users
                cur_a = conn.scalar(text("SELECT count(*) FROM audit_events;"))
                assert cur_a == base_audit
    finally:
        # Guaranteed global state restoration regardless of cleanup success
        get_engine.cache_clear()
        get_auth_engine.cache_clear()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prior_overrides)
