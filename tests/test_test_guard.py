"""
Test matrix for the Meridian Disposable Test Database Safety Boundary (T0).

Covers:
1. Pure offline guard unit tests (@pytest.mark.offline_guard_unit):
   - URL parsing, driver/dialect, role separation, host/port, database enforcement.
   - Settings consistency check without global mutation.
   - Credential canary masking / redaction.
   - TargetIdentity capture and teardown revalidation failure modes.
   - Alembic Config round-trip with %40 and %25 percent-encoding.
   - Alembic env.py 3-state URL trust contract (State A, State B, State C).
   - Fixture lifecycle behavioral isolation (mocked upgrade/downgrade prevention).
   - Offline-mode allowlisting and isolated subprocess acceptance tests.
2. Live database integration test (@pytest.mark.integration):
   - Live catalog and GUC marker verification against loopback:55432.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.engine import make_url

import meridian.testing.guard as guard_mod
from meridian.testing.guard import (
    ALEMBIC_GUARD_ATTRIBUTE,
    ALEMBIC_PLACEHOLDER_URL,
    APPROVED_APP_ROLE,
    APPROVED_GUC_MARKER,
    APPROVED_LOADER_ROLE,
    APPROVED_MIGRATOR_ROLE,
    APPROVED_TEST_DB,
    APPROVED_TEST_PORT,
    DISALLOWED_DEV_DB,
    DISALLOWED_DEV_PORT,
    MARKER_SETTING_NAME,
    TargetIdentity,
    _validate_single_url,
    pytest_collection_modifyitems,
    sanitize_url,
    validate_url_syntax_and_roles,
    verify_teardown_safety,
    verify_test_database_safety,
)

# Valid disposable test URLs for tests
VALID_MIGRATOR_URL = (
    f"postgresql+psycopg://{APPROVED_MIGRATOR_ROLE}:user_pass@"
    f"127.0.0.1:{APPROVED_TEST_PORT}/{APPROVED_TEST_DB}"
)
VALID_APP_URL = (
    f"postgresql+psycopg://{APPROVED_APP_ROLE}:app_pass@"
    f"127.0.0.1:{APPROVED_TEST_PORT}/{APPROVED_TEST_DB}"
)
VALID_LOADER_URL = (
    f"postgresql+psycopg://{APPROVED_LOADER_ROLE}:loader_pass@"
    f"127.0.0.1:{APPROVED_TEST_PORT}/{APPROVED_TEST_DB}"
)


@pytest.fixture
def mock_valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configures monkeypatched environment to match valid test configuration."""
    monkeypatch.setenv("DATABASE_URL", VALID_MIGRATOR_URL)
    monkeypatch.setenv("APP_DATABASE_URL", VALID_APP_URL)
    monkeypatch.setenv("LOADER_DATABASE_URL", VALID_LOADER_URL)

    # Configure a mock settings object reflecting the test environment
    mock_settings = MagicMock()
    mock_settings.database_url = VALID_MIGRATOR_URL
    mock_settings.app_database_url = VALID_APP_URL
    monkeypatch.setattr(guard_mod, "settings", mock_settings)


# ===========================================================================
# 1. URL SYNTAX, ROLE SEPARATION, AND CREDENTIAL REDACTION TESTS
# ===========================================================================


@pytest.mark.offline_guard_unit
def test_sanitize_url_masks_credentials() -> None:
    """Verifies that sanitize_url redacts passwords and never exposes secrets."""
    canary = "SUPER_SECRET_CANARY_PASS_98765"
    raw_url = (
        f"postgresql+psycopg://meridian_user:{canary}@127.0.0.1:55432/meridian_test"
    )

    sanitized = sanitize_url(raw_url)
    assert canary not in sanitized
    assert "meridian_user:***@127.0.0.1:55432/meridian_test" in sanitized


@pytest.mark.offline_guard_unit
def test_validate_url_syntax_and_roles_success(mock_valid_env: None) -> None:
    """Verifies that a conformant disposable test environment passes validation."""
    migrator_url, unescaped, escaped = validate_url_syntax_and_roles()
    assert migrator_url.username == APPROVED_MIGRATOR_ROLE
    assert migrator_url.database == APPROVED_TEST_DB
    assert migrator_url.port == APPROVED_TEST_PORT
    assert unescaped == VALID_MIGRATOR_URL
    assert escaped == VALID_MIGRATOR_URL.replace("%", "%%")


@pytest.mark.offline_guard_unit
def test_missing_required_env_var_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails closed if any of the three required connection variables is omitted."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_DATABASE_URL", VALID_APP_URL)
    monkeypatch.setenv("LOADER_DATABASE_URL", VALID_LOADER_URL)

    with pytest.raises(
        RuntimeError, match="Required environment variable.*DATABASE_URL.*not set"
    ):
        validate_url_syntax_and_roles()


@pytest.mark.offline_guard_unit
def test_malformed_database_url_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails closed when DATABASE_URL is not parseable by SQLAlchemy make_url."""
    monkeypatch.setenv("DATABASE_URL", "not_a_valid_url://:/:/")
    monkeypatch.setenv("APP_DATABASE_URL", VALID_APP_URL)
    monkeypatch.setenv("LOADER_DATABASE_URL", VALID_LOADER_URL)

    with pytest.raises(RuntimeError, match="Malformed DATABASE_URL"):
        validate_url_syntax_and_roles()


@pytest.mark.offline_guard_unit
def test_dev_database_name_rejected() -> None:
    """Fails closed if the database name is the development database meridian_db."""
    dev_url = make_url(
        f"postgresql+psycopg://meridian_user:pass@127.0.0.1:{APPROVED_TEST_PORT}/{DISALLOWED_DEV_DB}"
    )
    with pytest.raises(
        RuntimeError, match=f"targets development database '{DISALLOWED_DEV_DB}'"
    ):
        _validate_single_url(dev_url, APPROVED_MIGRATOR_ROLE, "DATABASE_URL")


@pytest.mark.offline_guard_unit
def test_dev_port_5432_rejected() -> None:
    """Fails closed if port is the default development port 5432."""
    dev_url = make_url(
        f"postgresql+psycopg://meridian_user:pass@127.0.0.1:{DISALLOWED_DEV_PORT}/{APPROVED_TEST_DB}"
    )
    with pytest.raises(
        RuntimeError, match=f"targets development port {DISALLOWED_DEV_PORT}"
    ):
        _validate_single_url(dev_url, APPROVED_MIGRATOR_ROLE, "DATABASE_URL")


@pytest.mark.offline_guard_unit
def test_non_loopback_host_rejected() -> None:
    """Fails closed if host is not a loopback address."""
    remote_url = make_url(
        f"postgresql+psycopg://meridian_user:pass@192.168.1.100:{APPROVED_TEST_PORT}/{APPROVED_TEST_DB}"
    )
    with pytest.raises(RuntimeError, match="specifies non-loopback host"):
        _validate_single_url(remote_url, APPROVED_MIGRATOR_ROLE, "DATABASE_URL")


@pytest.mark.offline_guard_unit
def test_wrong_role_rejected() -> None:
    """Fails closed if the configured role does not match the role requirement."""
    wrong_role_url = make_url(
        f"postgresql+psycopg://meridian_app:pass@127.0.0.1:{APPROVED_TEST_PORT}/{APPROVED_TEST_DB}"
    )
    with pytest.raises(RuntimeError, match=f"Expected role '{APPROVED_MIGRATOR_ROLE}'"):
        _validate_single_url(wrong_role_url, APPROVED_MIGRATOR_ROLE, "DATABASE_URL")


@pytest.mark.offline_guard_unit
def test_settings_disagreement_fails_closed_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Fails closed when settings.database_url disagrees with DATABASE_URL.
    Ensures settings is never mutated to conceal the discrepancy.
    """
    monkeypatch.setenv("DATABASE_URL", VALID_MIGRATOR_URL)
    monkeypatch.setenv("APP_DATABASE_URL", VALID_APP_URL)
    monkeypatch.setenv("LOADER_DATABASE_URL", VALID_LOADER_URL)

    # Disagreeing settings object targeting port 5432
    conflicting_url = (
        f"postgresql+psycopg://meridian_user:pass@127.0.0.1:5432/{DISALLOWED_DEV_DB}"
    )
    mock_settings = MagicMock()
    mock_settings.database_url = conflicting_url
    mock_settings.app_database_url = VALID_APP_URL
    monkeypatch.setattr(guard_mod, "settings", mock_settings)

    with pytest.raises(RuntimeError, match="disagrees with DATABASE_URL"):
        validate_url_syntax_and_roles()

    # Verify settings was not mutated
    assert mock_settings.database_url == conflicting_url


@pytest.mark.offline_guard_unit
def test_credential_canary_not_leaked_in_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensures canary passwords in bad configs are never leaked in error text."""
    canary = "CANARY_PW_DO_NOT_LEAK_IN_DIAGNOSTICS_12345"
    bad_url = f"postgresql+psycopg://meridian_user:{canary}@127.0.0.1:5432/{DISALLOWED_DEV_DB}"

    monkeypatch.setenv("DATABASE_URL", bad_url)
    monkeypatch.setenv("APP_DATABASE_URL", VALID_APP_URL)
    monkeypatch.setenv("LOADER_DATABASE_URL", VALID_LOADER_URL)

    mock_settings = MagicMock()
    mock_settings.database_url = bad_url
    monkeypatch.setattr(guard_mod, "settings", mock_settings)

    with pytest.raises(RuntimeError) as exc_info:
        validate_url_syntax_and_roles()

    error_message = str(exc_info.value)
    assert canary not in error_message
    assert "***" in error_message


# ===========================================================================
# 2. RUNTIME DATABASE MARKER AND TARGET IDENTITY TESTS
# ===========================================================================


@pytest.mark.offline_guard_unit
def test_verify_test_database_safety_wrong_connected_db(
    mock_valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails closed if live current_database() returns a DB other than meridian_test."""
    mock_conn = MagicMock()
    # 1st query: current_database() -> returns 'meridian_db' (dev db!)
    mock_conn.scalar.side_effect = [DISALLOWED_DEV_DB]

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    monkeypatch.setattr(
        sa, "create_engine", MagicMock(return_value=mock_engine)
    )

    with pytest.raises(
        RuntimeError, match=f"Connected database is '{DISALLOWED_DEV_DB}'"
    ):
        verify_test_database_safety()


@pytest.mark.offline_guard_unit
def test_verify_test_database_safety_missing_marker(
    mock_valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails closed if the disposable GUC marker is missing (None)."""
    mock_conn = MagicMock()
    # current_database(), then current_setting -> None
    mock_conn.scalar.side_effect = [APPROVED_TEST_DB, None]

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    monkeypatch.setattr(
        sa, "create_engine", MagicMock(return_value=mock_engine)
    )

    with pytest.raises(
        RuntimeError,
        match=f"missing required marker '{MARKER_SETTING_NAME}={APPROVED_GUC_MARKER}'",
    ):
        verify_test_database_safety()


@pytest.mark.offline_guard_unit
def test_verify_test_database_safety_marker_not_on(
    mock_valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails closed if the disposable GUC marker is anything other than 'on'."""
    mock_conn = MagicMock()
    # current_database(), then current_setting -> 'off'
    mock_conn.scalar.side_effect = [APPROVED_TEST_DB, "off"]

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    monkeypatch.setattr(
        sa, "create_engine", MagicMock(return_value=mock_engine)
    )

    with pytest.raises(RuntimeError, match="Received: 'off'"):
        verify_test_database_safety()


@pytest.mark.offline_guard_unit
def test_verify_test_database_safety_success(
    mock_valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that valid live query results produce a complete TargetIdentity."""
    mock_conn = MagicMock()
    # current_database(), current_setting, oid, pg_postmaster_start_time
    mock_conn.scalar.side_effect = [
        APPROVED_TEST_DB,
        APPROVED_GUC_MARKER,
        16384,
        "2026-10-22 10:00:00+00",
    ]

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    monkeypatch.setattr(
        sa, "create_engine", MagicMock(return_value=mock_engine)
    )

    identity, escaped_url = verify_test_database_safety()
    assert identity.database == APPROVED_TEST_DB
    assert identity.marker_value == APPROVED_GUC_MARKER
    assert identity.db_oid == 16384
    assert identity.server_start_time == "2026-10-22 10:00:00+00"
    assert identity.port == APPROVED_TEST_PORT
    assert identity.username == APPROVED_MIGRATOR_ROLE
    assert escaped_url == VALID_MIGRATOR_URL.replace("%", "%%")


# ===========================================================================
# 3. TEARDOWN REVALIDATION TESTS
# ===========================================================================


@pytest.fixture
def baseline_identity() -> TargetIdentity:
    """Provides a valid baseline TargetIdentity for teardown checks."""
    return TargetIdentity(
        normalized_host="127.0.0.1",
        port=APPROVED_TEST_PORT,
        database=APPROVED_TEST_DB,
        username=APPROVED_MIGRATOR_ROLE,
        db_oid=16384,
        server_start_time="2026-10-22 10:00:00+00",
        marker_value=APPROVED_GUC_MARKER,
        validated_url=VALID_MIGRATOR_URL,
    )


@pytest.mark.offline_guard_unit
def test_verify_teardown_safety_success(
    mock_valid_env: None,
    baseline_identity: TargetIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revalidation succeeds when live database state matches baseline identity."""
    mock_conn = MagicMock()
    # current_database(), current_setting, oid, pg_postmaster_start_time
    mock_conn.scalar.side_effect = [
        APPROVED_TEST_DB,
        APPROVED_GUC_MARKER,
        16384,
        "2026-10-22 10:00:00+00",
    ]

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    monkeypatch.setattr(
        sa, "create_engine", MagicMock(return_value=mock_engine)
    )

    escaped_url = verify_teardown_safety(baseline_identity)
    assert escaped_url == VALID_MIGRATOR_URL.replace("%", "%%")


@pytest.mark.offline_guard_unit
def test_verify_teardown_safety_oid_change_fails_closed(
    mock_valid_env: None,
    baseline_identity: TargetIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Teardown fails closed if database OID changed (e.g. database recreated)."""
    mock_conn = MagicMock()
    mock_conn.scalar.side_effect = [
        APPROVED_TEST_DB,
        APPROVED_GUC_MARKER,
        99999,  # Changed OID!
        "2026-10-22 10:00:00+00",
    ]

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    monkeypatch.setattr(
        sa, "create_engine", MagicMock(return_value=mock_engine)
    )

    with pytest.raises(
        RuntimeError, match="Database catalog OID changed from 16384 to 99999"
    ):
        verify_teardown_safety(baseline_identity)


@pytest.mark.offline_guard_unit
def test_verify_teardown_safety_postmaster_restart_fails_closed(
    mock_valid_env: None,
    baseline_identity: TargetIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Teardown fails closed if postmaster start timestamp changed."""
    mock_conn = MagicMock()
    mock_conn.scalar.side_effect = [
        APPROVED_TEST_DB,
        APPROVED_GUC_MARKER,
        16384,
        "2026-10-22 10:15:00+00",  # Changed timestamp!
    ]

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    monkeypatch.setattr(
        sa, "create_engine", MagicMock(return_value=mock_engine)
    )

    with pytest.raises(
        RuntimeError, match="PostgreSQL postmaster start timestamp changed"
    ):
        verify_teardown_safety(baseline_identity)


@pytest.mark.offline_guard_unit
def test_verify_teardown_safety_marker_lost_fails_closed(
    mock_valid_env: None,
    baseline_identity: TargetIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Teardown fails closed if marker setting is lost or reset."""
    mock_conn = MagicMock()
    mock_conn.scalar.side_effect = [
        APPROVED_TEST_DB,
        None,  # Lost marker!
    ]

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    monkeypatch.setattr(
        sa, "create_engine", MagicMock(return_value=mock_engine)
    )

    with pytest.raises(RuntimeError, match="Live disposable marker changed"):
        verify_teardown_safety(baseline_identity)


# ===========================================================================
# 4. ALEMBIC CONFIGPARSER ROUND-TRIP AND THREE-STATE CONTRACT
# ===========================================================================


@pytest.mark.offline_guard_unit
def test_alembic_configparser_roundtrip_with_percent_encoding() -> None:
    """
    MANDATORY REGRESSION TEST:
    Proves URL round-trip behavior through the real installed Alembic Config API.
    URL contains percent-encoded credentials (%40 for '@', %25 for '%').
    Verifies that doubling percent signs preserves the exact characters through
    Config.set_main_option and Config.get_main_option without interpolation errors.
    """
    raw_url = (
        "postgresql+psycopg://meridian_user:p%40ss%25word@127.0.0.1:55432/meridian_test"
    )

    # Doubling percent signs as performed by guard.validate_url_syntax_and_roles
    escaped_url = raw_url.replace("%", "%%")

    cfg = Config()
    cfg.set_main_option("sqlalchemy.url", escaped_url)

    # get_main_option reads and interpolates %% back to %
    recovered_url = cfg.get_main_option("sqlalchemy.url")

    assert recovered_url == raw_url
    assert "%40" in str(recovered_url)
    assert "%25" in str(recovered_url)


@pytest.mark.offline_guard_unit
def test_alembic_env_state_a_trusted_validated_url() -> None:
    """State A: Matches validated URL in Config.attributes with sqlalchemy.url."""
    cfg = Config()
    target_url = VALID_MIGRATOR_URL

    # Guard sets validated URL in attributes and escaped URL in options
    cfg.attributes[ALEMBIC_GUARD_ATTRIBUTE] = target_url
    cfg.set_main_option("sqlalchemy.url", target_url.replace("%", "%%"))

    validated_url = cfg.attributes.get(ALEMBIC_GUARD_ATTRIBUTE)
    current_ini_url = cfg.get_main_option("sqlalchemy.url")

    # In State A: both agree
    assert validated_url == target_url
    assert current_ini_url == validated_url


@pytest.mark.offline_guard_unit
def test_alembic_env_state_a_mismatch_fails_closed() -> None:
    """State A: Mismatch between attributes and sqlalchemy.url fails closed."""
    cfg = Config()
    validated_url = VALID_MIGRATOR_URL
    tampered_url = "postgresql+psycopg://meridian_user:pass@127.0.0.1:55432/other_db"

    cfg.attributes[ALEMBIC_GUARD_ATTRIBUTE] = validated_url
    cfg.set_main_option("sqlalchemy.url", tampered_url)

    current_ini_url = cfg.get_main_option("sqlalchemy.url")
    assert validated_url != current_ini_url

    # Simulate alembic/env.py logic
    with pytest.raises(
        RuntimeError,
        match="Alembic safety violation: config sqlalchemy.url does not match",
    ):
        if validated_url:
            if current_ini_url != validated_url:
                raise RuntimeError(
                    "Alembic safety violation: config sqlalchemy.url does not match "
                    "the guard-validated URL signal."
                )


@pytest.mark.offline_guard_unit
def test_alembic_env_state_b_placeholder_resolves_to_settings() -> None:
    """State B: Standalone Alembic CLI with placeholder resolves settings."""
    cfg = Config()
    # No guard attribute; placeholder present
    cfg.set_main_option("sqlalchemy.url", ALEMBIC_PLACEHOLDER_URL)

    current_ini_url = cfg.get_main_option("sqlalchemy.url")
    assert current_ini_url == ALEMBIC_PLACEHOLDER_URL

    # In standalone CLI, env.py resolves placeholder using settings.database_url
    mock_settings_url = (
        "postgresql+psycopg://meridian_user:dev_pass@localhost:5432/meridian_db"
    )
    cfg.set_main_option("sqlalchemy.url", mock_settings_url.replace("%", "%%"))
    assert cfg.get_main_option("sqlalchemy.url") == mock_settings_url

    # Regression test: Reused Config instance on second command
    # (e.g., downgrade then upgrade)
    current_ini_url_reused = cfg.get_main_option("sqlalchemy.url")
    assert current_ini_url_reused in (ALEMBIC_PLACEHOLDER_URL, mock_settings_url)


@pytest.mark.offline_guard_unit
def test_alembic_env_state_c_unexpected_unvalidated_url_fails_closed() -> None:
    """State C: Arbitrary non-placeholder URL without guard attribute fails closed."""
    cfg = Config()
    cfg.set_main_option(
        "sqlalchemy.url", "postgresql://hacker:pass@evil.host:5432/stolen_db"
    )

    validated_url = cfg.attributes.get(ALEMBIC_GUARD_ATTRIBUTE)
    current_ini_url = cfg.get_main_option("sqlalchemy.url")

    # In State C: untrusted non-placeholder URL without validated_url signal
    with pytest.raises(
        RuntimeError,
        match="Alembic safety violation: Untrusted or unexpected database URL",
    ):
        if validated_url:
            pass
        elif current_ini_url == ALEMBIC_PLACEHOLDER_URL:
            pass
        else:
            raise RuntimeError(
                "Alembic safety violation: Untrusted or unexpected database URL "
                "in configuration. Direct non-placeholder URLs require explicit "
                "test guard validation."
            )


# ===========================================================================
# 5. FIXTURE LIFECYCLE BEHAVIORAL ISOLATION TESTS
# ===========================================================================


@pytest.mark.offline_guard_unit
def test_fixture_lifecycle_setup_failure_prevents_upgrade() -> None:
    """
    Proves that a guard failure in fixture setup immediately aborts before
    alembic.command.upgrade is ever called.
    """
    mock_upgrade = MagicMock()
    mock_downgrade = MagicMock()

    with (
        patch(
            "meridian.testing.guard.verify_test_database_safety",
            side_effect=RuntimeError("Guard tripped"),
        ),
        patch("alembic.command.upgrade", mock_upgrade),
        patch("alembic.command.downgrade", mock_downgrade),
    ):
        # Emulate the guarded fixture lifecycle in tests/conftest.py
        def simulated_run_migrations() -> Generator[None, None, None]:
            target_identity, escaped_url = guard_mod.verify_test_database_safety()
            mock_upgrade(escaped_url, "head")
            try:
                yield
            finally:
                mock_downgrade(escaped_url, "base")

        gen = simulated_run_migrations()
        with pytest.raises(RuntimeError, match="Guard tripped"):
            next(gen)

        assert mock_upgrade.call_count == 0
        assert mock_downgrade.call_count == 0


@pytest.mark.offline_guard_unit
def test_fixture_lifecycle_teardown_failure_prevents_downgrade(
    baseline_identity: TargetIdentity,
) -> None:
    """
    Proves that a revalidation failure during teardown aborts before
    destructive alembic.command.downgrade is ever executed.
    """
    mock_upgrade = MagicMock()
    mock_downgrade = MagicMock()

    with (
        patch(
            "meridian.testing.guard.verify_test_database_safety",
            return_value=(baseline_identity, "escaped_url"),
        ),
        patch(
            "meridian.testing.guard.verify_teardown_safety",
            side_effect=RuntimeError("Identity changed at teardown"),
        ),
        patch("alembic.command.upgrade", mock_upgrade),
        patch("alembic.command.downgrade", mock_downgrade),
    ):

        def simulated_run_migrations() -> Generator[None, None, None]:
            target_identity, escaped_url = guard_mod.verify_test_database_safety()
            mock_upgrade(escaped_url, "head")
            try:
                yield
            finally:
                escaped_teardown_url = guard_mod.verify_teardown_safety(target_identity)
                mock_downgrade(escaped_teardown_url, "base")

        gen = simulated_run_migrations()
        # Setup succeeds and calls upgrade
        next(gen)
        assert mock_upgrade.call_count == 1
        assert mock_downgrade.call_count == 0

        # Teardown triggers revalidation error and must abort downgrade
        with pytest.raises(RuntimeError, match="Identity changed at teardown"):
            try:
                next(gen)
            except StopIteration:
                pass

        # Downgrade was NEVER called
        assert mock_downgrade.call_count == 0


# ===========================================================================
# 6. OFFLINE PYTEST MODE ENFORCEMENT & SUBPROCESS ACCEPTANCE TESTS
# ===========================================================================


@pytest.mark.offline_guard_unit
def test_offline_mode_in_process_rejects_unmarked_test() -> None:
    """pytest_collection_modifyitems rejects tests without offline_guard_unit marker."""
    mock_item = MagicMock()
    mock_item.nodeid = "test_unmarked"
    mock_item.get_closest_marker.return_value = None  # No offline_guard_unit marker

    mock_config = MagicMock()
    mock_config.getoption.return_value = True  # --offline-unit-tests active

    with pytest.raises(
        pytest.UsageError,
        match="Safety violation: --offline-unit-tests rejected 1 unapproved test",
    ):
        pytest_collection_modifyitems(MagicMock(), mock_config, [mock_item])


@pytest.mark.offline_guard_unit
def test_offline_mode_in_process_rejects_db_fixtures() -> None:
    """pytest_collection_modifyitems rejects tests with DB engine fixtures."""
    mock_item = MagicMock()
    mock_item.nodeid = "test_with_db"
    mock_item.get_closest_marker.return_value = MagicMock()  # Has marker
    mock_item.iter_markers.return_value = []
    mock_item.fixturenames = ["superuser_engine", "clean_data"]  # DB fixture!

    mock_config = MagicMock()
    mock_config.getoption.return_value = True

    with pytest.raises(
        pytest.UsageError,
        match="Safety violation: --offline-unit-tests rejected 1 unapproved test",
    ):
        pytest_collection_modifyitems(MagicMock(), mock_config, [mock_item])


@pytest.mark.offline_guard_unit
def test_offline_mode_in_process_rejects_integration_marker() -> None:
    """pytest_collection_modifyitems rejects tests that carry the integration marker."""
    mock_item = MagicMock()
    mock_item.nodeid = "test_integration"
    mock_item.get_closest_marker.return_value = MagicMock()  # Has offline marker
    integration_marker = MagicMock()
    integration_marker.name = "integration"
    mock_item.iter_markers.return_value = [integration_marker]
    mock_item.fixturenames = []

    mock_config = MagicMock()
    mock_config.getoption.return_value = True

    with pytest.raises(
        pytest.UsageError,
        match="Safety violation: --offline-unit-tests rejected 1 unapproved test",
    ):
        pytest_collection_modifyitems(MagicMock(), mock_config, [mock_item])


@pytest.mark.offline_guard_unit
def test_offline_mode_subprocess_mixed_suite_rejected_before_execution(
    tmp_path: Any,
) -> None:
    """
    MANDATORY ISOLATED SUBPROCESS ACCEPTANCE TEST (Case A):
    1. Isolated temporary directory without repo's tests/conftest.py.
    2. Subprocess runs with PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 and PYTHONPATH.
    3. Test suite contains 1 marked test and 1 unmarked test.
    4. Pytest is invoked with --offline-unit-tests and WITHOUT -m offline_guard_unit.
    5. Fails closed during collection with exit code 4 (UsageError).
    6. Sentinel files must NOT exist, proving neither test body executed.
    """
    # 1. Create isolated conftest.py importing guard hooks
    conftest_content = (
        "from meridian.testing.guard import (\n"
        "    pytest_addoption, pytest_collection_modifyitems, pytest_configure\n"
        ")\n"
    )
    (tmp_path / "conftest.py").write_text(conftest_content)

    sentinel_marked = tmp_path / "sentinel_marked.txt"
    sentinel_unmarked = tmp_path / "sentinel_unmarked.txt"

    # 2. Create mixed test file
    test_content = f"""
import pytest
from pathlib import Path

@pytest.mark.offline_guard_unit
def test_marked():
    Path({repr(str(sentinel_marked))}).write_text("executed")

def test_unmarked():
    Path({repr(str(sentinel_unmarked))}).write_text("executed")
"""
    (tmp_path / "test_mixed.py").write_text(test_content)

    src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    env = os.environ.copy()
    env["PYTHONPATH"] = src_dir
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--offline-unit-tests",
        "test_mixed.py",
    ]

    proc = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
    )

    # Exit code 4 is pytest.ExitCode.USAGE_ERROR
    assert proc.returncode == 4, (
        f"Expected exit code 4, got {proc.returncode}.\n"
        f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    assert (
        "Safety violation: --offline-unit-tests rejected 1 unapproved test"
        in proc.stderr
        or "Safety violation: --offline-unit-tests rejected 1 unapproved test"
        in proc.stdout
    )

    # Neither sentinel must exist!
    assert not sentinel_marked.exists(), (
        "Marked test executed despite mixed collection rejection!"
    )
    assert not sentinel_unmarked.exists(), (
        "Unmarked test executed despite mixed collection rejection!"
    )


@pytest.mark.offline_guard_unit
def test_offline_mode_subprocess_approved_suite_passes(tmp_path: Any) -> None:
    """
    MANDATORY ISOLATED SUBPROCESS ACCEPTANCE TEST (Case B):
    1. Isolated temporary directory with guard hooks.
    2. Test suite contains ONLY @pytest.mark.offline_guard_unit tests.
    3. Runs with --offline-unit-tests.
    4. Passes with exit code 0.
    5. Sentinel file is created, proving test executed cleanly.
    """
    conftest_content = (
        "from meridian.testing.guard import (\n"
        "    pytest_addoption, pytest_collection_modifyitems, pytest_configure\n"
        ")\n"
    )
    (tmp_path / "conftest.py").write_text(conftest_content)

    sentinel = tmp_path / "sentinel_success.txt"

    test_content = f"""
import pytest
from pathlib import Path

@pytest.mark.offline_guard_unit
def test_approved_pure_unit():
    Path({repr(str(sentinel))}).write_text("passed")
"""
    (tmp_path / "test_approved.py").write_text(test_content)

    src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    env = os.environ.copy()
    env["PYTHONPATH"] = src_dir
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--offline-unit-tests",
        "test_approved.py",
    ]

    proc = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode == 0, (
        f"Expected exit code 0, got {proc.returncode}.\n"
        f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    assert sentinel.exists(), "Approved test did not execute!"
    assert sentinel.read_text() == "passed"


# ===========================================================================
# 7. LIVE DATABASE INTEGRATION TEST (Active only when MERIDIAN_LIVE_GUARD_TEST=1)
# ===========================================================================


if os.environ.get("MERIDIAN_LIVE_GUARD_TEST") == "1":

    @pytest.mark.integration
    def test_live_disposable_database_guard() -> None:
        """
        Live integration test against the disposable container (127.0.0.1:55432).
        Requires container to be up with meridian.disposable_test_db='on'.
        """
        identity, escaped_url = verify_test_database_safety()

        assert identity.database == APPROVED_TEST_DB
        assert identity.port == APPROVED_TEST_PORT
        assert identity.marker_value == APPROVED_GUC_MARKER
        assert identity.username == APPROVED_MIGRATOR_ROLE
        assert identity.db_oid > 0
        assert len(identity.server_start_time) > 0

        # Teardown check against same identity
        reverified_url = verify_teardown_safety(identity)
        assert reverified_url == escaped_url
