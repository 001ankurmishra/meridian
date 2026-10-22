"""
Meridian Fail-Closed Test Database Safety Boundary.

Enforces strict isolation between development, production, and test databases:
1. Validates that all test connection URLs target exclusively the dedicated
   ephemeral test database (meridian_test on loopback port 55432).
2. Validates that required role separation (meridian_user, meridian_app,
   meridian_loader) is maintained across connection strings.
3. Asserts that effective settings match exported process environment variables.
4. Verifies the canonical disposable database marker
   (meridian.disposable_test_db = 'on') and records a verified TargetIdentity
   before allowing migrations or test execution.
5. Re-verifies TargetIdentity in teardown before permitting any destructive Alembic
   downgrade.
6. Enforces strict positive allowlisting for offline unit test execution.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Tuple

import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url

settings: Any = None


def _get_settings() -> Any:
    """Retrieves settings, loading meridian.config only when needed at runtime."""
    global settings
    if settings is not None:
        return settings
    try:
        from meridian.config import settings as app_settings

        return app_settings
    except Exception as e:
        raise RuntimeError(
            f"Test safety guard failed: Unable to load application settings: {e}"
        ) from e


# Canonical target invariants for Project Meridian ephemeral test database
APPROVED_TEST_DB: str = "meridian_test"
APPROVED_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost"})
APPROVED_TEST_PORT: int = 55432

APPROVED_MIGRATOR_ROLE: str = "meridian_user"
APPROVED_APP_ROLE: str = "meridian_app"
APPROVED_LOADER_ROLE: str = "meridian_loader"

APPROVED_GUC_MARKER: str = "on"
MARKER_SETTING_NAME: str = "meridian.disposable_test_db"

DISALLOWED_DEV_DB: str = "meridian_db"
DISALLOWED_DEV_PORT: int = 5432

ALEMBIC_GUARD_ATTRIBUTE: str = "meridian_guard_validated_url"
ALEMBIC_PLACEHOLDER_URL: str = "driver://user:pass@localhost/dbname"


@dataclass(frozen=True)
class TargetIdentity:
    """
    Immutable verified target identity captured during setup and checked
    at teardown.
    """

    normalized_host: str
    port: int
    database: str
    username: str
    db_oid: int
    server_start_time: str
    marker_value: str
    validated_url: str


def sanitize_url(raw_url: str | URL) -> str:
    """
    Renders a database URL with all credentials (passwords) redacted.
    Never exposes raw secrets in exceptions or logs.
    """
    if isinstance(raw_url, str):
        try:
            parsed = make_url(raw_url)
            return parsed.render_as_string(hide_password=True)
        except Exception:
            # If parsing fails, mask anything resembling user:pass@
            import re

            return re.sub(r"://([^:@]+):([^@]+)@", r"://\1:***@", raw_url)
    return raw_url.render_as_string(hide_password=True)


def validate_url_syntax_and_roles() -> Tuple[URL, str, str]:
    """
    Validates process environment variables and settings without connecting to DB.
    Fails closed if any variable is missing, malformed, targeting dev DB,
    or inconsistent.

    Returns:
        Tuple of (sa_url_obj, unescaped_migrator_url_str, configparser_escaped_url_str)
    """
    # 1. Require explicit presence of all 3 required database environment variables
    db_url_env = os.environ.get("DATABASE_URL")
    app_url_env = os.environ.get("APP_DATABASE_URL")
    loader_url_env = os.environ.get("LOADER_DATABASE_URL")

    missing = []
    if not db_url_env:
        missing.append("DATABASE_URL")
    if not app_url_env:
        missing.append("APP_DATABASE_URL")
    if not loader_url_env:
        missing.append("LOADER_DATABASE_URL")

    if missing:
        raise RuntimeError(
            f"Test safety guard failed: Required environment variable(s) {missing} "
            "are not set. All test database connection URLs must be explicitly "
            "configured."
        )

    assert db_url_env is not None
    assert app_url_env is not None
    assert loader_url_env is not None

    # 2. Parse and validate DATABASE_URL (migrator/superuser role)
    try:
        migrator_url = make_url(db_url_env)
    except Exception as e:
        raise RuntimeError(
            f"Test safety guard failed: Malformed DATABASE_URL: {e}"
        ) from e

    _validate_single_url(
        url=migrator_url,
        expected_role=APPROVED_MIGRATOR_ROLE,
        url_name="DATABASE_URL",
    )

    # 3. Parse and validate APP_DATABASE_URL (application runtime role)
    try:
        app_url = make_url(app_url_env)
    except Exception as e:
        raise RuntimeError(
            f"Test safety guard failed: Malformed APP_DATABASE_URL: {e}"
        ) from e

    _validate_single_url(
        url=app_url,
        expected_role=APPROVED_APP_ROLE,
        url_name="APP_DATABASE_URL",
    )

    # 4. Parse and validate LOADER_DATABASE_URL (data ingestion role)
    try:
        loader_url = make_url(loader_url_env)
    except Exception as e:
        raise RuntimeError(
            f"Test safety guard failed: Malformed LOADER_DATABASE_URL: {e}"
        ) from e

    _validate_single_url(
        url=loader_url,
        expected_role=APPROVED_LOADER_ROLE,
        url_name="LOADER_DATABASE_URL",
    )

    # 5. Assert consistency between os.environ and effective meridian.config.settings
    # Do NOT mutate settings; fail closed if settings disagrees with environment.
    effective_settings = _get_settings()
    try:
        settings_db_url = make_url(effective_settings.database_url)
    except Exception as e:
        raise RuntimeError(
            f"Test safety guard failed: Malformed settings.database_url: {e}"
        ) from e

    if (
        _normalize_host(settings_db_url.host) != _normalize_host(migrator_url.host)
        or settings_db_url.port != migrator_url.port
        or settings_db_url.database != migrator_url.database
        or settings_db_url.username != migrator_url.username
    ):
        raise RuntimeError(
            f"Test safety guard failed: settings.database_url "
            f"({sanitize_url(settings_db_url)}) disagrees with DATABASE_URL "
            f"({sanitize_url(migrator_url)}). Test environment variables must "
            "be exported before settings are loaded."
        )

    if effective_settings.app_database_url:
        try:
            settings_app_url = make_url(effective_settings.app_database_url)
            if (
                _normalize_host(settings_app_url.host) != _normalize_host(app_url.host)
                or settings_app_url.port != app_url.port
                or settings_app_url.database != app_url.database
                or settings_app_url.username != app_url.username
            ):
                raise RuntimeError(
                    f"Test safety guard failed: settings.app_database_url "
                    f"({sanitize_url(settings_app_url)}) disagrees with "
                    f"APP_DATABASE_URL ({sanitize_url(app_url)})."
                )
        except Exception as e:
            raise RuntimeError(
                f"Test safety guard failed: Malformed settings.app_database_url: {e}"
            ) from e

    # Render normalized unescaped and ConfigParser-escaped URL strings
    unescaped_str = migrator_url.render_as_string(hide_password=False)
    escaped_str = unescaped_str.replace("%", "%%")

    return migrator_url, unescaped_str, escaped_str


def _normalize_host(host: str | None) -> str:
    if host in {"127.0.0.1", "localhost"}:
        return "127.0.0.1"
    return host or ""


def _validate_single_url(url: URL, expected_role: str, url_name: str) -> None:
    sanitized = sanitize_url(url)

    # Disallow known development database and port
    if url.database == DISALLOWED_DEV_DB:
        raise RuntimeError(
            f"Test safety guard failed: {url_name} ({sanitized}) targets "
            f"development database '{DISALLOWED_DEV_DB}'. Expected dedicated "
            f"test database '{APPROVED_TEST_DB}'."
        )

    if url.port == DISALLOWED_DEV_PORT:
        raise RuntimeError(
            f"Test safety guard failed: {url_name} ({sanitized}) targets "
            f"development port {DISALLOWED_DEV_PORT}. Expected dedicated test "
            f"port {APPROVED_TEST_PORT}."
        )

    # Enforce loopback host
    if url.host not in APPROVED_LOOPBACK_HOSTS:
        raise RuntimeError(
            f"Test safety guard failed: {url_name} ({sanitized}) specifies "
            f"non-loopback host '{url.host}'. Only loopback "
            f"({list(APPROVED_LOOPBACK_HOSTS)}) is permitted."
        )

    # Enforce test port
    if url.port != APPROVED_TEST_PORT:
        raise RuntimeError(
            f"Test safety guard failed: {url_name} ({sanitized}) specifies port "
            f"{url.port}. Expected dedicated test port {APPROVED_TEST_PORT}."
        )

    # Enforce test database name
    if url.database != APPROVED_TEST_DB:
        raise RuntimeError(
            f"Test safety guard failed: {url_name} ({sanitized}) specifies database "
            f"'{url.database}'. Expected dedicated test database '{APPROVED_TEST_DB}'."
        )

    # Enforce required role
    if url.username != expected_role:
        raise RuntimeError(
            f"Test safety guard failed: {url_name} ({sanitized}) uses username "
            f"'{url.username}'. Expected role '{expected_role}'."
        )


def verify_test_database_safety(
    connect_timeout_seconds: int = 5,
) -> Tuple[TargetIdentity, str]:
    """
    Performs full pre-migration safety validation:
    1. Validates all URL syntax and roles (offline check).
    2. Opens a live connection to the candidate database using migrator credentials.
    3. Asserts current_database() == APPROVED_TEST_DB.
    4. Asserts disposable GUC marker == APPROVED_GUC_MARKER.
    5. Captures database OID and postmaster start timestamp.
    6. Returns (TargetIdentity, escaped_url_for_alembic).
    """
    migrator_url, unescaped_url, escaped_url = validate_url_syntax_and_roles()

    engine = sa.create_engine(
        migrator_url,
        connect_args={"connect_timeout": connect_timeout_seconds},
        poolclass=sa.pool.NullPool,
    )

    try:
        with engine.connect() as conn:
            # 1. Verify current database name
            current_db = conn.scalar(sa.text("SELECT current_database();"))
            if current_db != APPROVED_TEST_DB:
                raise RuntimeError(
                    f"Test safety guard failed: Connected database is '{current_db}', "
                    f"expected '{APPROVED_TEST_DB}'."
                )

            # 2. Verify canonical disposable marker
            marker = conn.scalar(
                sa.text(f"SELECT current_setting('{MARKER_SETTING_NAME}', true);")
            )
            if marker != APPROVED_GUC_MARKER:
                raise RuntimeError(
                    f"Test safety guard failed: Database '{current_db}' missing "
                    f"required marker '{MARKER_SETTING_NAME}={APPROVED_GUC_MARKER}'. "
                    f"Received: '{marker}'."
                )

            # 3. Capture catalog database OID
            db_oid = conn.scalar(
                sa.text(
                    "SELECT oid FROM pg_database WHERE datname = current_database();"
                )
            )
            if db_oid is None:
                raise RuntimeError(
                    "Test safety guard failed: Unable to retrieve database OID "
                    "from pg_database."
                )

            # 4. Capture server postmaster start timestamp
            postmaster_time = conn.scalar(sa.text("SELECT pg_postmaster_start_time();"))
            if postmaster_time is None:
                raise RuntimeError(
                    "Test safety guard failed: Unable to retrieve postmaster "
                    "start timestamp."
                )

        identity = TargetIdentity(
            normalized_host=_normalize_host(migrator_url.host),
            port=migrator_url.port or APPROVED_TEST_PORT,
            database=str(current_db),
            username=str(migrator_url.username),
            db_oid=int(db_oid),
            server_start_time=str(postmaster_time),
            marker_value=str(marker),
            validated_url=unescaped_url,
        )

        return identity, escaped_url
    finally:
        engine.dispose()


def verify_teardown_safety(
    expected_identity: TargetIdentity, connect_timeout_seconds: int = 5
) -> str:
    """
    Revalidates the target identity before permitting destructive Alembic teardown.
    Fails closed if the effective target, host, port, database, OID, postmaster
    start time, or marker has changed since setup.

    Returns:
        escaped_url_for_alembic
    """
    # 1. Re-validate current environment URL syntax
    migrator_url, unescaped_url, escaped_url = validate_url_syntax_and_roles()

    # 2. Check for host/port/database/role drift in environment
    if _normalize_host(migrator_url.host) != expected_identity.normalized_host:
        raise RuntimeError(
            f"Teardown safety aborted: Target host changed from "
            f"'{expected_identity.normalized_host}' to '{migrator_url.host}'."
        )
    if migrator_url.port != expected_identity.port:
        raise RuntimeError(
            f"Teardown safety aborted: Target port changed from "
            f"{expected_identity.port} to {migrator_url.port}."
        )
    if migrator_url.database != expected_identity.database:
        raise RuntimeError(
            f"Teardown safety aborted: Target database changed from "
            f"'{expected_identity.database}' to '{migrator_url.database}'."
        )
    if migrator_url.username != expected_identity.username:
        raise RuntimeError(
            f"Teardown safety aborted: Target username changed from "
            f"'{expected_identity.username}' to '{migrator_url.username}'."
        )

    # 3. Connect to live database and revalidate runtime catalog invariants
    engine = sa.create_engine(
        migrator_url,
        connect_args={"connect_timeout": connect_timeout_seconds},
        poolclass=sa.pool.NullPool,
    )

    try:
        with engine.connect() as conn:
            # Revalidate database name
            current_db = conn.scalar(sa.text("SELECT current_database();"))
            if current_db != expected_identity.database:
                raise RuntimeError(
                    f"Teardown safety aborted: Live database name changed from "
                    f"'{expected_identity.database}' to '{current_db}'."
                )

            # Revalidate canonical marker
            marker = conn.scalar(
                sa.text(f"SELECT current_setting('{MARKER_SETTING_NAME}', true);")
            )
            if marker != expected_identity.marker_value:
                raise RuntimeError(
                    f"Teardown safety aborted: Live disposable marker changed from "
                    f"'{expected_identity.marker_value}' to '{marker}'."
                )

            # Revalidate database OID
            current_oid = conn.scalar(
                sa.text(
                    "SELECT oid FROM pg_database WHERE datname = current_database();"
                )
            )
            if current_oid != expected_identity.db_oid:
                raise RuntimeError(
                    f"Teardown safety aborted: Database catalog OID changed from "
                    f"{expected_identity.db_oid} to {current_oid}. "
                    "Database may have been recreated."
                )

            # Revalidate postmaster start timestamp
            current_start_time = conn.scalar(
                sa.text("SELECT pg_postmaster_start_time();")
            )
            if str(current_start_time) != expected_identity.server_start_time:
                raise RuntimeError(
                    "Teardown safety aborted: PostgreSQL postmaster start timestamp "
                    f"changed from '{expected_identity.server_start_time}' to "
                    f"'{current_start_time}'. Server process restarted or "
                    "replaced during test session."
                )

        return escaped_url
    finally:
        engine.dispose()


# Pytest hook implementations for offline-mode allowlisting
def pytest_configure(config: Any) -> None:
    """Registers custom markers for test suite."""
    config.addinivalue_line(
        "markers",
        (
            "offline_guard_unit: Explicitly approved offline unit test without "
            "database access."
        ),
    )
    config.addinivalue_line(
        "markers",
        "integration: Tests requiring external or containerized services.",
    )


def pytest_addoption(parser: Any) -> None:
    """Registers --offline-unit-tests CLI option."""
    parser.addoption(
        "--offline-unit-tests",
        action="store_true",
        default=False,
        help=(
            "Run pure offline unit tests only. Rejects any unapproved or "
            "database-backed test."
        ),
    )


def pytest_collection_modifyitems(session: Any, config: Any, items: list[Any]) -> None:
    """
    Enforces strict positive allowlisting when --offline-unit-tests is active.
    Rejects mixed or unapproved test collections during collection before any test runs.
    """
    if config.getoption("--offline-unit-tests", default=False):
        unapproved: list[str] = []
        for item in items:
            # 1. Must have explicit marker @pytest.mark.offline_guard_unit
            marker = item.get_closest_marker("offline_guard_unit")
            if not marker:
                unapproved.append(item.nodeid)
                continue

            # 2. Must NOT have integration marker
            if any(m.name == "integration" for m in item.iter_markers()):
                unapproved.append(item.nodeid)
                continue

            # 3. Must NOT request any live database engine fixtures
            fixturenames = getattr(item, "fixturenames", [])
            db_fixtures = {
                "superuser_engine",
                "app_role_engine",
                "loader_role_engine",
                "app_engine",
                "live_server_url",
                "ui_smoke_engine",
            }
            if any(f in db_fixtures for f in fixturenames):
                unapproved.append(item.nodeid)
                continue

        if unapproved:
            import pytest

            sample = unapproved[:3]
            raise pytest.UsageError(
                f"Safety violation: --offline-unit-tests rejected {len(unapproved)} "
                f"unapproved test(s) (e.g. {sample}). Only tests explicitly marked "
                "'@pytest.mark.offline_guard_unit' without database fixtures or "
                "integration markers are permitted in offline mode."
            )
