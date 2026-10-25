"""Tests for screening_results database persistence layer.

Covers:
1. Migration upgrade and downgrade (pinned prior revision 4573f3e20e1c).
2. Database CHECK constraints (outcome, reason_code, candidate_count).
3. Database UNIQUE constraints and integrity error propagation.
4. Role permissions for meridian_app (SELECT/INSERT allowed, UPDATE/DELETE denied).
5. Persistence function happy paths (CANDIDATE_MATCHES_FOUND, NO_CANDIDATE_MATCH,
   NOT_PERFORMED).
6. Persistence function refusal paths (missing/mismatched agent_run, non-SUCCESS
   status, invalid inputs).
7. Transaction semantics (caller-owned connection and transaction control).
8. Sensitive-name guard (no customer or watchlist name leakage in exceptions).
9. Architecture/import guard (no orchestrator/dispatch imports, no agent_runs writes).
"""

from __future__ import annotations

import ast
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, cast

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from meridian.agents.sanctions.types import (
    MATCHING_RULE_ID,
    AbstentionReason,
    ScreeningOutcome,
)
from meridian.loader.watchlist_corpus import get_synthetic_watchlist_corpus
from meridian.loader.watchlist_ingest import ingest_watchlist_version
from meridian.orchestration.sanctions_agent_dispatch import (
    PINNED_WATCHLIST_NAME,
    PINNED_WATCHLIST_VERSION,
    run_sanctions_agent,
)
from meridian.orchestration.screening_results_persistence import (
    AgentRunGuardError,
    InvalidScreeningResultInputError,
    record_screening_result,
)
from tests.db_cleanup import clean_investigation_run_dependencies

PRIOR_MIGRATION_REVISION = "4573f3e20e1c"
CURRENT_MIGRATION_REVISION = ScriptDirectory.from_config(
    Config("alembic.ini")
).get_current_head()


# -----------------------------------------------------------------------------
# Test Fixtures and Helpers
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_screening_results_table(
    superuser_engine: Engine,
) -> Generator[None, None, None]:
    """Ensure screening_results table is clean before and after each test."""
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM screening_results"))
    yield
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM screening_results"))


def _seed_customer(
    superuser_engine: Engine, full_name: str = "Test Customer"
) -> uuid.UUID:
    """Seed a synthetic customer record."""
    cid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers "
                "(customer_id, full_name, is_synthetic, created_at) "
                "VALUES (:cid, :name, true, :now)"
            ),
            {"cid": cid, "name": full_name, "now": datetime.now(timezone.utc)},
        )
    return cid


def _seed_alert_case_investigation(
    superuser_engine: Engine, customer_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed alert, case, and investigation_run hierarchy."""
    aid = uuid.uuid4()
    case_id = uuid.uuid4()
    inv_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, created_at) "
                "VALUES (:aid, :cid, :now)"
            ),
            {"aid": aid, "cid": customer_id, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status, opened_at, created_at) "
                "VALUES (:case_id, :aid, 'OPEN', :now, :now)"
            ),
            {"case_id": case_id, "aid": aid, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO investigation_runs ("
                "investigation_run_id, case_id, status, started_at, created_at"
                ") VALUES (:inv_id, :case_id, 'IN_PROGRESS', :now, :now)"
            ),
            {"inv_id": inv_id, "case_id": case_id, "now": now},
        )
    return aid, case_id, inv_id


def _seed_agent_run(
    superuser_engine: Engine,
    investigation_run_id: uuid.UUID,
    agent_name: str = "SanctionsAgent",
    status: str = "SUCCESS",
) -> uuid.UUID:
    """Seed an agent_runs record with specified attributes."""
    ar_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_runs ("
                "agent_run_id, investigation_run_id, agent_name, tool_calls, "
                "status, started_at, completed_at"
                ") VALUES ("
                ":ar_id, :inv_id, :name, '{}'::jsonb, :status, :now, :now"
                ")"
            ),
            {
                "ar_id": ar_id,
                "inv_id": investigation_run_id,
                "name": agent_name,
                "status": status,
                "now": now,
            },
        )
    return ar_id


def _cleanup_test_data(superuser_engine: Engine, customer_id: uuid.UUID) -> None:
    """Clean up seeded investigation hierarchy and customer."""
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM screening_results"))
        clean_investigation_run_dependencies(conn)
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(
            text("DELETE FROM customers WHERE customer_id = :cid"),
            {"cid": customer_id},
        )


def _load_synthetic_watchlist_if_needed(loader_role_engine: Engine) -> None:
    """Ingest synthetic watchlist for tests that run sanctions dispatch."""
    corpus = get_synthetic_watchlist_corpus()
    ingest_watchlist_version(loader_role_engine, corpus)


# -----------------------------------------------------------------------------
# 1. Migration Upgrade and Downgrade Tests
# -----------------------------------------------------------------------------


def test_migration_downgrade_and_upgrade(superuser_engine: Engine) -> None:
    """Verify downgrade to pinned prior revision and re-upgrade to head."""
    alembic_cfg = Config("alembic.ini")

    # Verify table currently exists
    with superuser_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM screening_results")).scalar()
        assert count == 0

    # Downgrade to explicitly pinned prior revision
    command.downgrade(alembic_cfg, PRIOR_MIGRATION_REVISION)

    with superuser_engine.connect() as conn:
        with pytest.raises(Exception):
            conn.execute(text("SELECT * FROM screening_results"))

    # Re-upgrade to head
    command.upgrade(alembic_cfg, "head")

    with superuser_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM screening_results")).scalar()
        assert count == 0


def test_migration_table_schema_and_constraints(
    superuser_engine: Engine,
) -> None:
    """Verify columns, data types, foreign keys, and check constraints."""
    with superuser_engine.connect() as conn:
        columns = conn.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = 'screening_results'"
            )
        ).fetchall()
        col_map = {row[0]: (row[1], row[2]) for row in columns}

        expected_columns = {
            "screening_result_id": ("uuid", "NO"),
            "investigation_run_id": ("uuid", "NO"),
            "agent_run_id": ("uuid", "NO"),
            "customer_id": ("uuid", "NO"),
            "outcome": ("text", "NO"),
            "reason_code": ("text", "YES"),
            "candidate_count": ("integer", "NO"),
            "watchlist_name": ("text", "NO"),
            "watchlist_version": ("text", "NO"),
            "matching_rule_id": ("text", "NO"),
            "normalization_version": ("text", "NO"),
            "created_at": ("timestamp with time zone", "NO"),
        }
        for col_name, (expected_type, expected_null) in expected_columns.items():
            assert col_name in col_map, f"Column {col_name} missing from table"
            assert col_map[col_name] == (expected_type, expected_null)

        # Unique constraints
        uniques = conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'screening_results'::regclass AND contype = 'u'"
            )
        ).fetchall()
        unique_names = {row[0] for row in uniques}
        assert "uq_screening_results_investigation_run_id" in unique_names
        assert "uq_screening_results_agent_run_id" in unique_names

        # Check constraints
        checks = conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'screening_results'::regclass AND contype = 'c'"
            )
        ).fetchall()
        check_names = {row[0] for row in checks}
        assert "chk_screening_results_outcome" in check_names
        assert "chk_screening_results_reason_code" in check_names
        assert "chk_screening_results_candidate_count" in check_names


# -----------------------------------------------------------------------------
# 2. Database CHECK Constraints Tests (Direct SQL)
# -----------------------------------------------------------------------------


def _raw_insert_sql(
    superuser_engine: Engine,
    *,
    inv_id: uuid.UUID,
    ar_id: uuid.UUID,
    cid: uuid.UUID,
    outcome: str,
    reason_code: str | None,
    candidate_count: int,
) -> None:
    """Helper to execute raw SQL insert bypassing Python validation."""
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO screening_results (
                    screening_result_id,
                    investigation_run_id,
                    agent_run_id,
                    customer_id,
                    outcome,
                    reason_code,
                    candidate_count,
                    watchlist_name,
                    watchlist_version,
                    matching_rule_id,
                    normalization_version,
                    created_at
                ) VALUES (
                    gen_random_uuid(), :inv_id, :ar_id, :cid,
                    :outcome, :reason_code, :candidate_count,
                    'test_list', 'v1', 'rule1', 'v1', now()
                )
                """
            ),
            {
                "inv_id": inv_id,
                "ar_id": ar_id,
                "cid": cid,
                "outcome": outcome,
                "reason_code": reason_code,
                "candidate_count": candidate_count,
            },
        )


def test_db_check_constraint_invalid_outcome(superuser_engine: Engine) -> None:
    """Database rejects unsupported outcome values."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with pytest.raises(IntegrityError) as excinfo:
            _raw_insert_sql(
                superuser_engine,
                inv_id=inv_id,
                ar_id=ar_id,
                cid=cid,
                outcome="INVALID_OUTCOME",
                reason_code=None,
                candidate_count=0,
            )
        assert "chk_screening_results_outcome" in str(excinfo.value)
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_db_check_constraint_reason_code_non_null_for_non_abstention(
    superuser_engine: Engine,
) -> None:
    """Database rejects non-NULL reason_code when outcome is not NOT_PERFORMED."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with pytest.raises(IntegrityError) as excinfo:
            _raw_insert_sql(
                superuser_engine,
                inv_id=inv_id,
                ar_id=ar_id,
                cid=cid,
                outcome="NO_CANDIDATE_MATCH",
                reason_code="CUSTOMER_NAME_MISSING",
                candidate_count=0,
            )
        assert "chk_screening_results_reason_code" in str(excinfo.value)
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_db_check_constraint_missing_reason_code_for_not_performed(
    superuser_engine: Engine,
) -> None:
    """Database rejects NULL reason_code when outcome is NOT_PERFORMED."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with pytest.raises(IntegrityError) as excinfo:
            _raw_insert_sql(
                superuser_engine,
                inv_id=inv_id,
                ar_id=ar_id,
                cid=cid,
                outcome="NOT_PERFORMED",
                reason_code=None,
                candidate_count=0,
            )
        assert "chk_screening_results_reason_code" in str(excinfo.value)
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_db_check_constraint_invalid_reason_code(superuser_engine: Engine) -> None:
    """Database rejects invalid reason_code values."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with pytest.raises(IntegrityError) as excinfo:
            _raw_insert_sql(
                superuser_engine,
                inv_id=inv_id,
                ar_id=ar_id,
                cid=cid,
                outcome="NOT_PERFORMED",
                reason_code="UNKNOWN_REASON_CODE",
                candidate_count=0,
            )
        assert "chk_screening_results_reason_code" in str(excinfo.value)
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_db_check_constraint_negative_candidate_count(
    superuser_engine: Engine,
) -> None:
    """Database rejects negative candidate_count values."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with pytest.raises(IntegrityError) as excinfo:
            _raw_insert_sql(
                superuser_engine,
                inv_id=inv_id,
                ar_id=ar_id,
                cid=cid,
                outcome="NO_CANDIDATE_MATCH",
                reason_code=None,
                candidate_count=-1,
            )
        assert "chk_screening_results_candidate_count" in str(excinfo.value)
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_db_check_constraint_zero_count_for_candidate_matches_found(
    superuser_engine: Engine,
) -> None:
    """Database rejects candidate_count = 0 for CANDIDATE_MATCHES_FOUND."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with pytest.raises(IntegrityError) as excinfo:
            _raw_insert_sql(
                superuser_engine,
                inv_id=inv_id,
                ar_id=ar_id,
                cid=cid,
                outcome="CANDIDATE_MATCHES_FOUND",
                reason_code=None,
                candidate_count=0,
            )
        assert "chk_screening_results_candidate_count" in str(excinfo.value)
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_db_check_constraint_positive_count_for_no_match(
    superuser_engine: Engine,
) -> None:
    """Database rejects candidate_count > 0 for NO_CANDIDATE_MATCH."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with pytest.raises(IntegrityError) as excinfo:
            _raw_insert_sql(
                superuser_engine,
                inv_id=inv_id,
                ar_id=ar_id,
                cid=cid,
                outcome="NO_CANDIDATE_MATCH",
                reason_code=None,
                candidate_count=2,
            )
        assert "chk_screening_results_candidate_count" in str(excinfo.value)
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_db_check_constraint_positive_count_for_not_performed(
    superuser_engine: Engine,
) -> None:
    """Database rejects candidate_count > 0 for NOT_PERFORMED."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with pytest.raises(IntegrityError) as excinfo:
            _raw_insert_sql(
                superuser_engine,
                inv_id=inv_id,
                ar_id=ar_id,
                cid=cid,
                outcome="NOT_PERFORMED",
                reason_code="CUSTOMER_NAME_MISSING",
                candidate_count=1,
            )
        assert "chk_screening_results_candidate_count" in str(excinfo.value)
    finally:
        _cleanup_test_data(superuser_engine, cid)


# -----------------------------------------------------------------------------
# 3. Database UNIQUE Constraints Tests
# -----------------------------------------------------------------------------


def test_db_unique_constraint_investigation_run_id(
    superuser_engine: Engine, app_role_engine: Engine
) -> None:
    """Database rejects second screening_results row for same investigation_run_id."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id_1 = _seed_agent_run(superuser_engine, inv_id)
        ar_id_2 = _seed_agent_run(superuser_engine, inv_id)

        with app_role_engine.connect() as conn:
            with conn.begin():
                record_screening_result(
                    conn,
                    investigation_run_id=inv_id,
                    agent_run_id=ar_id_1,
                    customer_id=cid,
                    outcome="NO_CANDIDATE_MATCH",
                    reason_code=None,
                    candidate_count=0,
                    watchlist_name="test_list",
                    watchlist_version="v1",
                    matching_rule_id="exact_norm_name_v1",
                    normalization_version="v1",
                )

            # Second attempt with same investigation_run_id propagates IntegrityError
            with conn.begin():
                with pytest.raises(IntegrityError) as excinfo:
                    record_screening_result(
                        conn,
                        investigation_run_id=inv_id,
                        agent_run_id=ar_id_2,
                        customer_id=cid,
                        outcome="NO_CANDIDATE_MATCH",
                        reason_code=None,
                        candidate_count=0,
                        watchlist_name="test_list",
                        watchlist_version="v1",
                        matching_rule_id="exact_norm_name_v1",
                        normalization_version="v1",
                    )
                assert "uq_screening_results_investigation_run_id" in str(excinfo.value)
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_db_unique_constraint_agent_run_id(
    superuser_engine: Engine, app_role_engine: Engine
) -> None:
    """Database rejects second screening_results row for same agent_run_id."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id_1 = _seed_alert_case_investigation(superuser_engine, cid)
        _, _, inv_id_2 = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id_1)

        with app_role_engine.connect() as conn:
            with conn.begin():
                record_screening_result(
                    conn,
                    investigation_run_id=inv_id_1,
                    agent_run_id=ar_id,
                    customer_id=cid,
                    outcome="NO_CANDIDATE_MATCH",
                    reason_code=None,
                    candidate_count=0,
                    watchlist_name="test_list",
                    watchlist_version="v1",
                    matching_rule_id="exact_norm_name_v1",
                    normalization_version="v1",
                )

            # Attempt raw insert with same agent_run_id and different inv_id
            with pytest.raises(IntegrityError) as excinfo:
                _raw_insert_sql(
                    superuser_engine,
                    inv_id=inv_id_2,
                    ar_id=ar_id,
                    cid=cid,
                    outcome="NO_CANDIDATE_MATCH",
                    reason_code=None,
                    candidate_count=0,
                )
            assert "uq_screening_results_agent_run_id" in str(excinfo.value)
    finally:
        _cleanup_test_data(superuser_engine, cid)


# -----------------------------------------------------------------------------
# 4. Privilege Tests for meridian_app
# -----------------------------------------------------------------------------


def test_app_role_privileges(superuser_engine: Engine, app_role_engine: Engine) -> None:
    """meridian_app has SELECT and INSERT only; UPDATE and DELETE are denied."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)
        res_id = uuid.uuid4()

        with app_role_engine.connect() as conn:
            # 1. INSERT succeeds
            conn.execute(
                text(
                    """
                    INSERT INTO screening_results (
                        screening_result_id,
                        investigation_run_id,
                        agent_run_id,
                        customer_id,
                        outcome,
                        reason_code,
                        candidate_count,
                        watchlist_name,
                        watchlist_version,
                        matching_rule_id,
                        normalization_version,
                        created_at
                    ) VALUES (
                        :res_id, :inv_id, :ar_id, :cid,
                        'NO_CANDIDATE_MATCH', NULL, 0, 'test_list', 'v1',
                        'exact_norm_name_v1', 'v1', now()
                    )
                    """
                ),
                {"res_id": res_id, "inv_id": inv_id, "ar_id": ar_id, "cid": cid},
            )
            conn.commit()

            # 2. SELECT succeeds
            count = conn.execute(
                text(
                    "SELECT count(*) FROM screening_results "
                    "WHERE screening_result_id = :rid"
                ),
                {"rid": res_id},
            ).scalar()
            assert count == 1

            # 3. UPDATE fails with permission denied
            with pytest.raises(Exception) as excinfo:
                conn.execute(
                    text(
                        "UPDATE screening_results SET candidate_count = 5 "
                        "WHERE screening_result_id = :rid"
                    ),
                    {"rid": res_id},
                )
                conn.commit()
            assert "permission denied" in str(excinfo.value).lower()
            conn.rollback()

            # 4. DELETE fails with permission denied
            with pytest.raises(Exception) as excinfo:
                conn.execute(
                    text(
                        "DELETE FROM screening_results WHERE screening_result_id = :rid"
                    ),
                    {"rid": res_id},
                )
                conn.commit()
            assert "permission denied" in str(excinfo.value).lower()
            conn.rollback()
    finally:
        _cleanup_test_data(superuser_engine, cid)


def _restore_outer_env(
    outer_orig_user: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restore the outer APP_DB_USER environment variable."""
    if outer_orig_user is not None:
        monkeypatch.setenv("APP_DB_USER", outer_orig_user)
    else:
        monkeypatch.delenv("APP_DB_USER", raising=False)


def _get_current_alembic_revision(engine: Engine) -> str | None:
    """Return the current revision identifier recorded in Alembic."""
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            return context.get_current_revision()
    except Exception:
        return None


def _diagnose_role_existence(
    superuser_engine: Engine,
    quoted_role: str | None,
) -> str:
    """Non-destructive diagnostic to inspect role presence without altering state."""
    if quoted_role is None:
        return "No temporary role specified"
    try:
        with superuser_engine.connect() as conn:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM pg_catalog.pg_roles WHERE quote_ident(rolname) = :qr"
                ),
                {"qr": quoted_role},
            ).scalar()
            return (
                f"role {quoted_role} exists in pg_roles"
                if exists
                else f"role {quoted_role} not present in pg_roles"
            )
    except Exception as exc:
        return f"could not inspect pg_roles for {quoted_role}: {exc}"


def _cleanup_migration_and_role(
    alembic_cfg: Config,
    superuser_engine: Engine,
    outer_orig_user: str | None,
    quoted_role: str | None,
    monkeypatch: pytest.MonkeyPatch,
    *,
    migration_entered: bool = True,
    migration_setup_completed: bool = True,
) -> list[Exception]:
    """Execute cleanup sequence: state-aware migration recovery and safe role drop.

    Returns a list of any exceptions encountered during cleanup.
    """
    cleanup_errors: list[Exception] = []
    database_restored = False
    is_recognized_state = False

    # 1. Determine actual Alembic revision before performing any recovery operation
    current_rev = _get_current_alembic_revision(superuser_engine)

    if current_rev is None:
        role_diag = _diagnose_role_existence(superuser_engine, quoted_role)
        cleanup_errors.append(
            RuntimeError(
                "Database Alembic revision could not be determined; database state "
                "is unverified and manual recovery is required. Skipping migration "
                f"recovery and destructive role cleanup. Diagnostic: {role_diag}."
            )
        )
    elif current_rev not in (CURRENT_MIGRATION_REVISION, PRIOR_MIGRATION_REVISION):
        role_diag = _diagnose_role_existence(superuser_engine, quoted_role)
        cleanup_errors.append(
            RuntimeError(
                f"Database in unexpected Alembic revision '{current_rev}'; "
                "database state is unverified and manual recovery is required. "
                "Skipping migration recovery and destructive role cleanup. "
                f"Diagnostic: {role_diag}."
            )
        )
    elif not migration_entered:
        # Test setup failed before entering migration lifecycle (e.g. role creation).
        # Database was never modified by migration operations.
        if current_rev == CURRENT_MIGRATION_REVISION:
            database_restored = True
            is_recognized_state = True
        else:
            role_diag = _diagnose_role_existence(superuser_engine, quoted_role)
            cleanup_errors.append(
                RuntimeError(
                    f"Test did not enter migration lifecycle but database is at "
                    f"'{current_rev}' instead of '{CURRENT_MIGRATION_REVISION}'; "
                    "database state is unverified and manual recovery is required. "
                    "Skipping migration recovery and destructive role cleanup. "
                    f"Diagnostic: {role_diag}."
                )
            )
    elif migration_entered and not migration_setup_completed:
        # Test entered migration lifecycle but setup failed partially.
        is_recognized_state = True
        if current_rev == PRIOR_MIGRATION_REVISION:
            # Downgrade already succeeded in setup; restore outer env before upgrade.
            _restore_outer_env(outer_orig_user, monkeypatch)
            try:
                command.upgrade(alembic_cfg, "head")
                database_restored = True
            except Exception as exc:
                cleanup_errors.append(exc)
        elif current_rev == CURRENT_MIGRATION_REVISION:
            # Downgrade never changed revision in setup; database is still at head.
            _restore_outer_env(outer_orig_user, monkeypatch)
            database_restored = True
    else:
        # Full migration setup completed: downgrade from test role and re-upgrade
        # with outer env.
        is_recognized_state = True
        downgrade_succeeded = False
        try:
            command.downgrade(alembic_cfg, PRIOR_MIGRATION_REVISION)
            downgrade_succeeded = True
        except Exception as exc:
            cleanup_errors.append(exc)

        # Restore actual outer environment state before attempting final upgrade
        _restore_outer_env(outer_orig_user, monkeypatch)

        # Attempt final upgrade ONLY if downgrade succeeded
        if downgrade_succeeded:
            try:
                command.upgrade(alembic_cfg, "head")
                database_restored = True
            except Exception as exc:
                cleanup_errors.append(exc)
        else:
            cleanup_errors.append(
                RuntimeError(
                    "Database restoration could not be confirmed: cleanup downgrade "
                    "failed and final upgrade was skipped."
                )
            )

    # 2. Always ensure outer environment state is restored
    _restore_outer_env(outer_orig_user, monkeypatch)

    # 3. Independent safe temporary-role deletion: DROP OWNED, then DROP ROLE IF EXISTS
    # Destructive role cleanup is ONLY performed when the database is in an
    # explicitly recognized recovery state. When revision is unknown or unexpected,
    # destructive role cleanup is skipped because DROP OWNED could drop objects in
    # an unverified state.
    if quoted_role is not None and is_recognized_state:
        try:
            with superuser_engine.begin() as conn:
                conn.execute(text(f"DROP OWNED BY {quoted_role}"))
        except Exception as exc:
            cleanup_errors.append(exc)

        try:
            with superuser_engine.begin() as conn:
                conn.execute(text(f"DROP ROLE IF EXISTS {quoted_role}"))
        except Exception as exc:
            cleanup_errors.append(exc)

    # 4. Post-recovery verification of head revision and privileges
    final_rev = _get_current_alembic_revision(superuser_engine)
    if final_rev != CURRENT_MIGRATION_REVISION:
        cleanup_errors.append(
            RuntimeError(
                f"Database revision unverified: expected "
                f"'{CURRENT_MIGRATION_REVISION}', found '{final_rev}'."
            )
        )
    elif database_restored and not cleanup_errors:
        try:
            with superuser_engine.connect() as conn:
                app_privs = conn.execute(
                    text(
                        "SELECT privilege_type FROM "
                        "information_schema.table_privileges "
                        "WHERE table_name = 'screening_results' "
                        "AND grantee = 'meridian_app'"
                    )
                ).fetchall()
                app_priv_types = {row[0] for row in app_privs}
                assert "SELECT" in app_priv_types
                assert "INSERT" in app_priv_types
                assert "UPDATE" not in app_priv_types
                assert "DELETE" not in app_priv_types
        except Exception as exc:
            cleanup_errors.append(exc)

    return cleanup_errors


def _handle_test_and_cleanup_exceptions(
    test_body_exc: BaseException | None,
    cleanup_errors: list[Exception],
) -> None:
    """Report test-body and cleanup exceptions without masking either."""
    if test_body_exc is not None and cleanup_errors:
        try:
            raise BaseExceptionGroup(
                "Test body failed and subsequent cleanup operations failed",
                [test_body_exc, *cleanup_errors],
            )
        except BaseExceptionGroup:
            raise
        except BaseException:
            # If aggregation itself fails, preserve the original test failure
            raise test_body_exc
    if test_body_exc is not None:
        raise test_body_exc
    if cleanup_errors:
        if len(cleanup_errors) == 1:
            raise cleanup_errors[0]
        raise ExceptionGroup(
            f"{len(cleanup_errors)} cleanup operations failed",
            cleanup_errors,
        )


def test_migration_upgrade_with_sql_significant_role(
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Migration safely handles role names with SQL-significant characters."""
    alembic_cfg = Config("alembic.ini")
    test_role = "test\"role'with;drop--space table"
    outer_orig_user = os.environ.get("APP_DB_USER")
    quoted: str | None = None
    test_body_exc: BaseException | None = None
    migration_entered = False
    migration_setup_completed = False

    try:
        with superuser_engine.begin() as conn:
            quoted = conn.execute(
                text("SELECT quote_ident(:r)"),
                {"r": test_role},
            ).scalar()
            conn.execute(text(f"CREATE ROLE {quoted} NOSUPERUSER NOLOGIN"))

        # Downgrade to prior revision
        migration_entered = True
        command.downgrade(alembic_cfg, PRIOR_MIGRATION_REVISION)

        # Set APP_DB_USER to the role with SQL-significant characters
        monkeypatch.setenv("APP_DB_USER", test_role)

        # Upgrade to head should succeed without syntax error or injection
        command.upgrade(alembic_cfg, "head")
        migration_setup_completed = True

        # Verify that SELECT and INSERT were granted to test_role
        with superuser_engine.connect() as conn:
            privs = conn.execute(
                text(
                    "SELECT privilege_type FROM information_schema.table_privileges "
                    "WHERE table_name = 'screening_results' AND grantee = :grantee"
                ),
                {"grantee": test_role},
            ).fetchall()
            priv_types = {row[0] for row in privs}
            assert "SELECT" in priv_types
            assert "INSERT" in priv_types
            assert "UPDATE" not in priv_types
            assert "DELETE" not in priv_types
    except BaseException as exc:
        test_body_exc = exc
    finally:
        cleanup_errors = _cleanup_migration_and_role(
            alembic_cfg=alembic_cfg,
            superuser_engine=superuser_engine,
            outer_orig_user=outer_orig_user,
            quoted_role=quoted,
            monkeypatch=monkeypatch,
            migration_entered=migration_entered,
            migration_setup_completed=migration_setup_completed,
        )
        _handle_test_and_cleanup_exceptions(test_body_exc, cleanup_errors)


@pytest.mark.parametrize("app_user_env", [None, "meridian_app"])
def test_migration_upgrade_default_and_explicit_app_user(
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    app_user_env: str | None,
) -> None:
    """Migration upgrade succeeds with APP_DB_USER unset or explicitly set."""
    alembic_cfg = Config("alembic.ini")
    outer_orig_user = os.environ.get("APP_DB_USER")
    test_body_exc: BaseException | None = None
    migration_entered = False
    migration_setup_completed = False

    try:
        # Downgrade to prior revision
        migration_entered = True
        command.downgrade(alembic_cfg, PRIOR_MIGRATION_REVISION)

        # Configure environment for this test case
        if app_user_env is not None:
            monkeypatch.setenv("APP_DB_USER", app_user_env)
        else:
            monkeypatch.delenv("APP_DB_USER", raising=False)

        # Upgrade to head under this environment configuration
        command.upgrade(alembic_cfg, "head")
        migration_setup_completed = True

        # Verify meridian_app has SELECT and INSERT
        with superuser_engine.connect() as conn:
            privs = conn.execute(
                text(
                    "SELECT privilege_type FROM "
                    "information_schema.table_privileges "
                    "WHERE table_name = 'screening_results' "
                    "AND grantee = 'meridian_app'"
                )
            ).fetchall()
            priv_types = {row[0] for row in privs}
            assert "SELECT" in priv_types
            assert "INSERT" in priv_types
            assert "UPDATE" not in priv_types
            assert "DELETE" not in priv_types
    except BaseException as exc:
        test_body_exc = exc
    finally:
        cleanup_errors = _cleanup_migration_and_role(
            alembic_cfg=alembic_cfg,
            superuser_engine=superuser_engine,
            outer_orig_user=outer_orig_user,
            quoted_role=None,
            monkeypatch=monkeypatch,
            migration_entered=migration_entered,
            migration_setup_completed=migration_setup_completed,
        )
        _handle_test_and_cleanup_exceptions(test_body_exc, cleanup_errors)


def test_cleanup_skips_upgrade_when_downgrade_fails(
    monkeypatch: pytest.MonkeyPatch,
    superuser_engine: Engine,
) -> None:
    """When cleanup downgrade fails, the final upgrade is skipped

    to avoid leaving the database in an uncertain state.
    """
    upgrade_called = False

    def fake_downgrade(cfg: Config, rev: str) -> None:
        raise RuntimeError("simulated downgrade error")

    def fake_upgrade(cfg: Config, rev: str) -> None:
        nonlocal upgrade_called
        upgrade_called = True

    monkeypatch.setattr(command, "downgrade", fake_downgrade)
    monkeypatch.setattr(command, "upgrade", fake_upgrade)

    alembic_cfg = Config("alembic.ini")
    errors = _cleanup_migration_and_role(
        alembic_cfg=alembic_cfg,
        superuser_engine=superuser_engine,
        outer_orig_user="meridian_app",
        quoted_role=None,
        monkeypatch=monkeypatch,
        migration_entered=True,
        migration_setup_completed=True,
    )

    assert not upgrade_called, "Upgrade must not be called when downgrade fails"
    assert any("simulated downgrade error" in str(e) for e in errors)
    assert any("Database restoration could not be confirmed" in str(e) for e in errors)


def test_cleanup_skips_migration_and_role_cleanup_when_revision_is_unexpected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup skips migration and destructive role cleanup on unexpected revision."""
    executed_statements: list[str] = []
    downgrade_called = False
    upgrade_called = False

    def fake_downgrade(cfg: Config, rev: str) -> None:
        nonlocal downgrade_called
        downgrade_called = True

    def fake_upgrade(cfg: Config, rev: str) -> None:
        nonlocal upgrade_called
        upgrade_called = True

    class FakeConn:
        def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> Any:
            executed_statements.append(str(stmt))
            return None

    class FakeBeginContext:
        def __enter__(self) -> FakeConn:
            return FakeConn()

        def __exit__(self, *args: Any) -> None:
            pass

    class FakeEngine:
        def begin(self) -> FakeBeginContext:
            return FakeBeginContext()

        def connect(self) -> FakeBeginContext:
            return FakeBeginContext()

    monkeypatch.setattr(command, "downgrade", fake_downgrade)
    monkeypatch.setattr(command, "upgrade", fake_upgrade)
    monkeypatch.setattr(
        "tests.test_screening_results_persistence._get_current_alembic_revision",
        lambda engine: "unexpected_rev_12345",
    )

    alembic_cfg = Config("alembic.ini")
    fake_engine = cast(Engine, FakeEngine())
    errors = _cleanup_migration_and_role(
        alembic_cfg=alembic_cfg,
        superuser_engine=fake_engine,
        outer_orig_user="meridian_app",
        quoted_role='"test_role"',
        monkeypatch=monkeypatch,
        migration_entered=True,
        migration_setup_completed=True,
    )

    assert not downgrade_called
    assert not upgrade_called
    assert not any("DROP OWNED" in s for s in executed_statements)
    assert not any("DROP ROLE" in s for s in executed_statements)
    assert any(
        "unexpected Alembic revision 'unexpected_rev_12345'" in str(e) for e in errors
    )
    assert any("manual recovery is required" in str(e) for e in errors)
    assert any("Database revision unverified" in str(e) for e in errors)


def test_cleanup_skips_migration_and_role_cleanup_when_revision_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup skips migration and role cleanup when revision cannot be determined."""
    executed_statements: list[str] = []
    downgrade_called = False
    upgrade_called = False

    def fake_downgrade(cfg: Config, rev: str) -> None:
        nonlocal downgrade_called
        downgrade_called = True

    def fake_upgrade(cfg: Config, rev: str) -> None:
        nonlocal upgrade_called
        upgrade_called = True

    class FakeConn:
        def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> Any:
            executed_statements.append(str(stmt))
            return None

    class FakeBeginContext:
        def __enter__(self) -> FakeConn:
            return FakeConn()

        def __exit__(self, *args: Any) -> None:
            pass

    class FakeEngine:
        def begin(self) -> FakeBeginContext:
            return FakeBeginContext()

        def connect(self) -> FakeBeginContext:
            return FakeBeginContext()

    monkeypatch.setattr(command, "downgrade", fake_downgrade)
    monkeypatch.setattr(command, "upgrade", fake_upgrade)
    monkeypatch.setattr(
        "tests.test_screening_results_persistence._get_current_alembic_revision",
        lambda engine: None,
    )

    alembic_cfg = Config("alembic.ini")
    fake_engine = cast(Engine, FakeEngine())
    errors = _cleanup_migration_and_role(
        alembic_cfg=alembic_cfg,
        superuser_engine=fake_engine,
        outer_orig_user="meridian_app",
        quoted_role='"test_role"',
        monkeypatch=monkeypatch,
        migration_entered=True,
        migration_setup_completed=True,
    )

    assert not downgrade_called
    assert not upgrade_called
    assert not any("DROP OWNED" in s for s in executed_statements)
    assert not any("DROP ROLE" in s for s in executed_statements)
    assert any("could not be determined" in str(e) for e in errors)
    assert any("manual recovery is required" in str(e) for e in errors)
    assert any("Database revision unverified" in str(e) for e in errors)


def test_cleanup_reports_error_when_cleanup_upgrade_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When cleanup upgrade fails, the failure is reported and DB is unverified."""
    upgrade_called = False

    def fake_downgrade(cfg: Config, rev: str) -> None:
        pass

    def fake_upgrade(cfg: Config, rev: str) -> None:
        nonlocal upgrade_called
        upgrade_called = True
        raise RuntimeError("simulated cleanup upgrade error")

    monkeypatch.setattr(command, "downgrade", fake_downgrade)
    monkeypatch.setattr(command, "upgrade", fake_upgrade)

    def fake_get_rev(engine: Engine) -> str | None:
        if upgrade_called:
            return PRIOR_MIGRATION_REVISION
        return CURRENT_MIGRATION_REVISION

    monkeypatch.setattr(
        "tests.test_screening_results_persistence._get_current_alembic_revision",
        fake_get_rev,
    )

    class FakeConn:
        def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> Any:
            return None

    class FakeBeginContext:
        def __enter__(self) -> FakeConn:
            return FakeConn()

        def __exit__(self, *args: Any) -> None:
            pass

    class FakeEngine:
        def begin(self) -> FakeBeginContext:
            return FakeBeginContext()

        def connect(self) -> FakeBeginContext:
            return FakeBeginContext()

    alembic_cfg = Config("alembic.ini")
    fake_engine = cast(Engine, FakeEngine())
    errors = _cleanup_migration_and_role(
        alembic_cfg=alembic_cfg,
        superuser_engine=fake_engine,
        outer_orig_user="meridian_app",
        quoted_role=None,
        monkeypatch=monkeypatch,
        migration_entered=True,
        migration_setup_completed=True,
    )

    assert upgrade_called
    assert any("simulated cleanup upgrade error" in str(e) for e in errors)
    assert any("Database revision unverified" in str(e) for e in errors)


def test_cleanup_attempts_drop_role_when_drop_owned_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DROP ROLE is attempted even if DROP OWNED fails."""
    executed_statements: list[str] = []

    class FakeConn:
        def execute(self, stmt: Any) -> None:
            sql_str = str(stmt)
            executed_statements.append(sql_str)
            if "DROP OWNED" in sql_str:
                raise RuntimeError("simulated DROP OWNED failure")

    class FakeBeginContext:
        def __enter__(self) -> FakeConn:
            return FakeConn()

        def __exit__(self, *args: Any) -> None:
            pass

    class FakeEngine:
        def begin(self) -> FakeBeginContext:
            return FakeBeginContext()

    monkeypatch.setattr(command, "downgrade", lambda cfg, rev: None)
    monkeypatch.setattr(command, "upgrade", lambda cfg, rev: None)
    monkeypatch.setattr(
        "tests.test_screening_results_persistence._get_current_alembic_revision",
        lambda engine: CURRENT_MIGRATION_REVISION,
    )

    alembic_cfg = Config("alembic.ini")
    fake_engine = cast(Engine, FakeEngine())
    errors = _cleanup_migration_and_role(
        alembic_cfg=alembic_cfg,
        superuser_engine=fake_engine,
        outer_orig_user="meridian_app",
        quoted_role='"test_role"',
        monkeypatch=monkeypatch,
        migration_entered=True,
        migration_setup_completed=True,
    )

    assert any("DROP OWNED" in s for s in executed_statements)
    assert any("DROP ROLE IF EXISTS" in s for s in executed_statements)
    assert len(errors) == 1
    assert "simulated DROP OWNED failure" in str(errors[0])


def test_cleanup_preserves_original_test_failure_when_cleanup_fails() -> None:
    """When both the test body and cleanup fail, both are reported

    without losing either via BaseExceptionGroup.
    """
    test_body_exc = AssertionError("primary assertion failure")
    cleanup_errors = [RuntimeError("secondary cleanup failure")]

    with pytest.raises(BaseExceptionGroup) as excinfo:
        _handle_test_and_cleanup_exceptions(test_body_exc, cleanup_errors)

    eg = excinfo.value
    assert len(eg.exceptions) == 2
    assert isinstance(eg.exceptions[0], AssertionError)
    assert str(eg.exceptions[0]) == "primary assertion failure"
    assert isinstance(eg.exceptions[1], RuntimeError)
    assert str(eg.exceptions[1]) == "secondary cleanup failure"


def test_cleanup_preserves_base_exception_when_cleanup_fails() -> None:
    """BaseException subclasses like KeyboardInterrupt are preserved.

    They are preserved in BaseExceptionGroup without raising TypeError.
    """
    test_body_exc = KeyboardInterrupt()
    cleanup_errors = [RuntimeError("secondary cleanup failure")]

    with pytest.raises(BaseExceptionGroup) as excinfo:
        _handle_test_and_cleanup_exceptions(test_body_exc, cleanup_errors)

    beg = excinfo.value
    assert len(beg.exceptions) == 2
    assert isinstance(beg.exceptions[0], KeyboardInterrupt)
    assert isinstance(beg.exceptions[1], RuntimeError)


def test_actual_migration_recovery_after_partial_setup_failure(
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When setup fails after downgrade, cleanup restores env and upgrades to head."""
    alembic_cfg = Config("alembic.ini")
    outer_orig_user = os.environ.get("APP_DB_USER")
    simulated_failure = RuntimeError("simulated setup failure after downgrade")
    test_body_exc: BaseException | None = None

    try:
        # Step 1: Successfully enter migration lifecycle and downgrade to prior revision
        command.downgrade(alembic_cfg, PRIOR_MIGRATION_REVISION)

        # Verify database is currently at prior revision
        assert (
            _get_current_alembic_revision(superuser_engine) == PRIOR_MIGRATION_REVISION
        )

        # Step 2: Simulate failure in setup before upgrade
        raise simulated_failure
    except BaseException as exc:
        test_body_exc = exc
    finally:
        # Step 3: Cleanup detects partial setup failure, restores outer env,
        # and upgrades to head
        cleanup_errors = _cleanup_migration_and_role(
            alembic_cfg=alembic_cfg,
            superuser_engine=superuser_engine,
            outer_orig_user=outer_orig_user,
            quoted_role=None,
            monkeypatch=monkeypatch,
            migration_entered=True,
            migration_setup_completed=False,
        )

    # Cleanup must succeed without errors
    assert cleanup_errors == []

    # Database must be restored to head revision
    assert _get_current_alembic_revision(superuser_engine) == CURRENT_MIGRATION_REVISION

    # meridian_app must have expected permissions
    with superuser_engine.connect() as conn:
        app_privs = conn.execute(
            text(
                "SELECT privilege_type FROM "
                "information_schema.table_privileges "
                "WHERE table_name = 'screening_results' "
                "AND grantee = 'meridian_app'"
            )
        ).fetchall()
        app_priv_types = {row[0] for row in app_privs}
        assert "SELECT" in app_priv_types
        assert "INSERT" in app_priv_types
        assert "UPDATE" not in app_priv_types
        assert "DELETE" not in app_priv_types

    # And exception handling preserves the original test failure
    with pytest.raises(RuntimeError, match="simulated setup failure after downgrade"):
        _handle_test_and_cleanup_exceptions(test_body_exc, cleanup_errors)


def test_actual_cleanup_when_setup_fails_before_migration_entered(
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When setup fails before entering migration, cleanup drops role safely."""
    alembic_cfg = Config("alembic.ini")
    outer_orig_user = os.environ.get("APP_DB_USER")
    test_role = "test_cleanup_pre_migration_role"
    test_body_exc: BaseException | None = None
    quoted: str | None = None

    try:
        with superuser_engine.begin() as conn:
            quoted = conn.execute(
                text("SELECT quote_ident(:r)"),
                {"r": test_role},
            ).scalar()
            conn.execute(text(f"CREATE ROLE {quoted} NOSUPERUSER NOLOGIN"))

        # Simulate setup failure before entering migration lifecycle
        raise RuntimeError("simulated setup failure before migration")
    except BaseException as exc:
        test_body_exc = exc
    finally:
        cleanup_errors = _cleanup_migration_and_role(
            alembic_cfg=alembic_cfg,
            superuser_engine=superuser_engine,
            outer_orig_user=outer_orig_user,
            quoted_role=quoted,
            monkeypatch=monkeypatch,
            migration_entered=False,
            migration_setup_completed=False,
        )

    assert cleanup_errors == []
    # Role must be dropped
    with superuser_engine.connect() as conn:
        role_exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
            {"r": test_role},
        ).scalar()
        assert role_exists is None

    # Database must remain at head
    assert _get_current_alembic_revision(superuser_engine) == CURRENT_MIGRATION_REVISION

    with pytest.raises(RuntimeError, match="simulated setup failure before migration"):
        _handle_test_and_cleanup_exceptions(test_body_exc, cleanup_errors)


def test_actual_cleanup_when_test_fails_after_setup_completed(
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When test fails after setup completes, cleanup restores head and drops role."""
    alembic_cfg = Config("alembic.ini")
    outer_orig_user = os.environ.get("APP_DB_USER")
    test_role = "test_cleanup_post_setup_role"
    test_body_exc: BaseException | None = None
    quoted: str | None = None
    migration_entered = False
    migration_setup_completed = False

    try:
        with superuser_engine.begin() as conn:
            quoted = conn.execute(
                text("SELECT quote_ident(:r)"),
                {"r": test_role},
            ).scalar()
            conn.execute(text(f"CREATE ROLE {quoted} NOSUPERUSER NOLOGIN"))

        migration_entered = True
        command.downgrade(alembic_cfg, PRIOR_MIGRATION_REVISION)

        monkeypatch.setenv("APP_DB_USER", test_role)
        command.upgrade(alembic_cfg, "head")
        migration_setup_completed = True

        # Simulate test assertion failure after full setup completed
        raise AssertionError("simulated test assertion failure after setup")
    except BaseException as exc:
        test_body_exc = exc
    finally:
        cleanup_errors = _cleanup_migration_and_role(
            alembic_cfg=alembic_cfg,
            superuser_engine=superuser_engine,
            outer_orig_user=outer_orig_user,
            quoted_role=quoted,
            monkeypatch=monkeypatch,
            migration_entered=migration_entered,
            migration_setup_completed=migration_setup_completed,
        )

    assert cleanup_errors == []

    # Role must be dropped
    with superuser_engine.connect() as conn:
        role_exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
            {"r": test_role},
        ).scalar()
        assert role_exists is None

    # Database must be at head revision
    assert _get_current_alembic_revision(superuser_engine) == CURRENT_MIGRATION_REVISION

    # Outer env must be restored
    if outer_orig_user is not None:
        assert os.environ.get("APP_DB_USER") == outer_orig_user
    else:
        assert "APP_DB_USER" not in os.environ

    # Original failure preserved
    with pytest.raises(
        AssertionError, match="simulated test assertion failure after setup"
    ):
        _handle_test_and_cleanup_exceptions(test_body_exc, cleanup_errors)


# -----------------------------------------------------------------------------
# 5. Function Happy Paths
# -----------------------------------------------------------------------------


def test_happy_path_candidate_matches_found_with_real_sanctions_agent(
    superuser_engine: Engine,
    app_role_engine: Engine,
    loader_role_engine: Engine,
) -> None:
    """Happy path: CANDIDATE_MATCHES_FOUND with a real SanctionsAgent run."""
    _load_synthetic_watchlist_if_needed(loader_role_engine)
    # Aurelius Vance is a known synthetic listed match
    cid = _seed_customer(superuser_engine, full_name="Aurelius Vance")
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        # Run real SanctionsAgent dispatch
        dispatch_result = run_sanctions_agent(app_role_engine, inv_id, cid)
        assert (
            dispatch_result.result.outcome == ScreeningOutcome.CANDIDATE_MATCHES_FOUND
        )
        assert len(dispatch_result.result.candidates) > 0

        # Retrieve real agent_run_id recorded by dispatch
        with superuser_engine.connect() as conn:
            ar_id = conn.execute(
                text(
                    "SELECT agent_run_id FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id "
                    "AND agent_name = 'SanctionsAgent'"
                ),
                {"inv_id": inv_id},
            ).scalar()
        assert ar_id is not None

        # Persist screening result via caller connection
        with app_role_engine.connect() as conn:
            with conn.begin():
                persisted_id = record_screening_result(
                    conn,
                    investigation_run_id=inv_id,
                    agent_run_id=ar_id,
                    customer_id=cid,
                    outcome=dispatch_result.result.outcome,
                    reason_code=dispatch_result.result.reason_code,
                    candidate_count=len(dispatch_result.result.candidates),
                    watchlist_name=dispatch_result.result.watchlist_name,
                    watchlist_version=dispatch_result.result.watchlist_version,
                    matching_rule_id=dispatch_result.result.matching_rule_id,
                    normalization_version=dispatch_result.result.normalization_version,
                )

            # Verify persisted row in DB
            row = conn.execute(
                text(
                    "SELECT outcome, reason_code, candidate_count, watchlist_name, "
                    "watchlist_version, matching_rule_id, normalization_version "
                    "FROM screening_results WHERE screening_result_id = :rid"
                ),
                {"rid": persisted_id},
            ).fetchone()
            assert row is not None
            assert row[0] == "CANDIDATE_MATCHES_FOUND"
            assert row[1] is None
            assert row[2] == len(dispatch_result.result.candidates)
            assert row[3] == PINNED_WATCHLIST_NAME
            assert row[4] == PINNED_WATCHLIST_VERSION
            assert row[5] == MATCHING_RULE_ID
            assert row[6] == "v1"
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_happy_path_no_candidate_match_with_real_sanctions_agent(
    superuser_engine: Engine,
    app_role_engine: Engine,
    loader_role_engine: Engine,
) -> None:
    """Happy path: NO_CANDIDATE_MATCH with a real SanctionsAgent run."""
    _load_synthetic_watchlist_if_needed(loader_role_engine)
    cid = _seed_customer(
        superuser_engine, full_name="Completely Unrelated NonMatch Customer"
    )
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        dispatch_result = run_sanctions_agent(app_role_engine, inv_id, cid)
        assert dispatch_result.result.outcome == ScreeningOutcome.NO_CANDIDATE_MATCH
        assert len(dispatch_result.result.candidates) == 0

        with superuser_engine.connect() as conn:
            ar_id = conn.execute(
                text(
                    "SELECT agent_run_id FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id "
                    "AND agent_name = 'SanctionsAgent'"
                ),
                {"inv_id": inv_id},
            ).scalar()
        assert ar_id is not None

        with app_role_engine.connect() as conn:
            with conn.begin():
                persisted_id = record_screening_result(
                    conn,
                    investigation_run_id=inv_id,
                    agent_run_id=ar_id,
                    customer_id=cid,
                    outcome=dispatch_result.result.outcome,
                    reason_code=dispatch_result.result.reason_code,
                    candidate_count=0,
                    watchlist_name=dispatch_result.result.watchlist_name,
                    watchlist_version=dispatch_result.result.watchlist_version,
                    matching_rule_id=dispatch_result.result.matching_rule_id,
                    normalization_version=dispatch_result.result.normalization_version,
                )

            row = conn.execute(
                text(
                    "SELECT outcome, reason_code, candidate_count "
                    "FROM screening_results WHERE screening_result_id = :rid"
                ),
                {"rid": persisted_id},
            ).fetchone()
            assert row is not None
            assert row[0] == "NO_CANDIDATE_MATCH"
            assert row[1] is None
            assert row[2] == 0
    finally:
        _cleanup_test_data(superuser_engine, cid)


@pytest.mark.parametrize(
    "reason_code",
    [
        AbstentionReason.CUSTOMER_NAME_MISSING,
        AbstentionReason.CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION,
        AbstentionReason.WATCHLIST_VERSION_NOT_LOADED,
    ],
)
def test_happy_path_not_performed_each_reason_code(
    superuser_engine: Engine,
    app_role_engine: Engine,
    reason_code: AbstentionReason,
) -> None:
    """Happy path: NOT_PERFORMED persisted with each allowed controlled reason code."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with app_role_engine.connect() as conn:
            with conn.begin():
                persisted_id = record_screening_result(
                    conn,
                    investigation_run_id=inv_id,
                    agent_run_id=ar_id,
                    customer_id=cid,
                    outcome=ScreeningOutcome.NOT_PERFORMED,
                    reason_code=reason_code,
                    candidate_count=0,
                    watchlist_name=PINNED_WATCHLIST_NAME,
                    watchlist_version=PINNED_WATCHLIST_VERSION,
                    matching_rule_id=MATCHING_RULE_ID,
                    normalization_version="v1",
                )

            row = conn.execute(
                text(
                    "SELECT outcome, reason_code, candidate_count "
                    "FROM screening_results WHERE screening_result_id = :rid"
                ),
                {"rid": persisted_id},
            ).fetchone()
            assert row is not None
            assert row[0] == "NOT_PERFORMED"
            assert row[1] == reason_code.value
            assert row[2] == 0
    finally:
        _cleanup_test_data(superuser_engine, cid)


# -----------------------------------------------------------------------------
# 6. Function Refusal Paths (Zero Rows Written)
# -----------------------------------------------------------------------------


def _assert_zero_screening_results(conn: Connection) -> None:
    """Assert zero rows exist in screening_results."""
    count = conn.execute(text("SELECT count(*) FROM screening_results")).scalar()
    assert count == 0


def test_refusal_missing_agent_run(
    superuser_engine: Engine, app_role_engine: Engine
) -> None:
    """Refusal: agent_run_id does not exist in agent_runs; writes nothing."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        missing_ar_id = uuid.uuid4()

        with app_role_engine.connect() as conn:
            with conn.begin():
                with pytest.raises(AgentRunGuardError) as excinfo:
                    record_screening_result(
                        conn,
                        investigation_run_id=inv_id,
                        agent_run_id=missing_ar_id,
                        customer_id=cid,
                        outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                        reason_code=None,
                        candidate_count=0,
                        watchlist_name=PINNED_WATCHLIST_NAME,
                        watchlist_version=PINNED_WATCHLIST_VERSION,
                        matching_rule_id=MATCHING_RULE_ID,
                        normalization_version="v1",
                    )
                assert "does not exist in agent_runs" in str(excinfo.value)
                _assert_zero_screening_results(conn)
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_refusal_wrong_agent_name(
    superuser_engine: Engine, app_role_engine: Engine
) -> None:
    """Refusal: agent_name is TransactionAgent instead of SanctionsAgent."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id, agent_name="TransactionAgent")

        with app_role_engine.connect() as conn:
            with conn.begin():
                with pytest.raises(AgentRunGuardError) as excinfo:
                    record_screening_result(
                        conn,
                        investigation_run_id=inv_id,
                        agent_run_id=ar_id,
                        customer_id=cid,
                        outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                        reason_code=None,
                        candidate_count=0,
                        watchlist_name=PINNED_WATCHLIST_NAME,
                        watchlist_version=PINNED_WATCHLIST_VERSION,
                        matching_rule_id=MATCHING_RULE_ID,
                        normalization_version="v1",
                    )
                assert "expected 'SanctionsAgent'" in str(excinfo.value)
                _assert_zero_screening_results(conn)
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_refusal_mismatched_investigation_run_id(
    superuser_engine: Engine, app_role_engine: Engine
) -> None:
    """Refusal: agent_run belongs to different investigation; writes nothing."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id_1 = _seed_alert_case_investigation(superuser_engine, cid)
        _, _, inv_id_2 = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id_1)

        with app_role_engine.connect() as conn:
            with conn.begin():
                with pytest.raises(AgentRunGuardError) as excinfo:
                    record_screening_result(
                        conn,
                        investigation_run_id=inv_id_2,
                        agent_run_id=ar_id,
                        customer_id=cid,
                        outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                        reason_code=None,
                        candidate_count=0,
                        watchlist_name=PINNED_WATCHLIST_NAME,
                        watchlist_version=PINNED_WATCHLIST_VERSION,
                        matching_rule_id=MATCHING_RULE_ID,
                        normalization_version="v1",
                    )
                assert "does not match supplied" in str(excinfo.value)
                _assert_zero_screening_results(conn)
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_refusal_failed_agent_run(
    superuser_engine: Engine, app_role_engine: Engine
) -> None:
    """Refusal: agent_run has status FAILED; writes nothing."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id, status="FAILED")

        with app_role_engine.connect() as conn:
            with conn.begin():
                with pytest.raises(AgentRunGuardError) as excinfo:
                    record_screening_result(
                        conn,
                        investigation_run_id=inv_id,
                        agent_run_id=ar_id,
                        customer_id=cid,
                        outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                        reason_code=None,
                        candidate_count=0,
                        watchlist_name=PINNED_WATCHLIST_NAME,
                        watchlist_version=PINNED_WATCHLIST_VERSION,
                        matching_rule_id=MATCHING_RULE_ID,
                        normalization_version="v1",
                    )
                assert "expected 'SUCCESS'" in str(excinfo.value)
                _assert_zero_screening_results(conn)
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_refusal_partial_agent_run(
    superuser_engine: Engine, app_role_engine: Engine
) -> None:
    """Refusal: agent_run has status PARTIAL; writes nothing."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id, status="PARTIAL")

        with app_role_engine.connect() as conn:
            with conn.begin():
                with pytest.raises(AgentRunGuardError) as excinfo:
                    record_screening_result(
                        conn,
                        investigation_run_id=inv_id,
                        agent_run_id=ar_id,
                        customer_id=cid,
                        outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                        reason_code=None,
                        candidate_count=0,
                        watchlist_name=PINNED_WATCHLIST_NAME,
                        watchlist_version=PINNED_WATCHLIST_VERSION,
                        matching_rule_id=MATCHING_RULE_ID,
                        normalization_version="v1",
                    )
                assert "expected 'SUCCESS'" in str(excinfo.value)
                _assert_zero_screening_results(conn)
    finally:
        _cleanup_test_data(superuser_engine, cid)


@pytest.mark.parametrize(
    ("bad_outcome", "bad_reason", "bad_count"),
    [
        ("BOGUS_OUTCOME", None, 0),
        ("CANDIDATE_MATCHES_FOUND", None, 0),  # zero count for match found
        ("CANDIDATE_MATCHES_FOUND", None, -2),  # negative count
        (
            "CANDIDATE_MATCHES_FOUND",
            "CUSTOMER_NAME_MISSING",
            3,
        ),  # reason with match
        ("NO_CANDIDATE_MATCH", "CUSTOMER_NAME_MISSING", 0),  # reason with no-match
        ("NO_CANDIDATE_MATCH", None, 1),  # positive count with no-match
        ("NOT_PERFORMED", None, 0),  # missing reason for not performed
        ("NOT_PERFORMED", "INVALID_REASON", 0),  # invalid reason
        ("NOT_PERFORMED", "CUSTOMER_NAME_MISSING", 2),  # positive count with abstention
        (12345, None, 0),  # non-string outcome
        ("NO_CANDIDATE_MATCH", 99999, 0),  # non-string reason_code
        (True, None, 0),  # bool outcome
        ("NOT_PERFORMED", True, 0),  # bool reason_code
    ],
)
def test_refusal_invalid_inputs_fail_before_insert(
    superuser_engine: Engine,
    app_role_engine: Engine,
    bad_outcome: Any,
    bad_reason: Any,
    bad_count: int,
) -> None:
    """Refusal: invalid inputs raise InvalidScreeningResultInputError in Python."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with app_role_engine.connect() as conn:
            with conn.begin():
                with pytest.raises(InvalidScreeningResultInputError):
                    record_screening_result(
                        conn,
                        investigation_run_id=inv_id,
                        agent_run_id=ar_id,
                        customer_id=cid,
                        outcome=bad_outcome,
                        reason_code=bad_reason,
                        candidate_count=bad_count,
                        watchlist_name=PINNED_WATCHLIST_NAME,
                        watchlist_version=PINNED_WATCHLIST_VERSION,
                        matching_rule_id=MATCHING_RULE_ID,
                        normalization_version="v1",
                    )
                _assert_zero_screening_results(conn)
    finally:
        _cleanup_test_data(superuser_engine, cid)


# -----------------------------------------------------------------------------
# 7. Transaction Semantics Tests
# -----------------------------------------------------------------------------


def test_transaction_semantics_caller_rollback(
    superuser_engine: Engine, app_role_engine: Engine
) -> None:
    """Row is discarded when caller transaction rolls back."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with app_role_engine.connect() as conn:
            trans = conn.begin()
            res_id = record_screening_result(
                conn,
                investigation_run_id=inv_id,
                agent_run_id=ar_id,
                customer_id=cid,
                outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                reason_code=None,
                candidate_count=0,
                watchlist_name=PINNED_WATCHLIST_NAME,
                watchlist_version=PINNED_WATCHLIST_VERSION,
                matching_rule_id=MATCHING_RULE_ID,
                normalization_version="v1",
            )
            # Visible through same connection before commit/rollback
            visible = conn.execute(
                text(
                    "SELECT count(*) FROM screening_results "
                    "WHERE screening_result_id = :rid"
                ),
                {"rid": res_id},
            ).scalar()
            assert visible == 1

            trans.rollback()

        # After rollback, row does not exist in DB
        with superuser_engine.connect() as conn:
            persisted = conn.execute(
                text(
                    "SELECT count(*) FROM screening_results "
                    "WHERE screening_result_id = :rid"
                ),
                {"rid": res_id},
            ).scalar()
            assert persisted == 0
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_transaction_semantics_caller_commit(
    superuser_engine: Engine, app_role_engine: Engine
) -> None:
    """Row persists when caller transaction commits."""
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with app_role_engine.connect() as conn:
            trans = conn.begin()
            res_id = record_screening_result(
                conn,
                investigation_run_id=inv_id,
                agent_run_id=ar_id,
                customer_id=cid,
                outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                reason_code=None,
                candidate_count=0,
                watchlist_name=PINNED_WATCHLIST_NAME,
                watchlist_version=PINNED_WATCHLIST_VERSION,
                matching_rule_id=MATCHING_RULE_ID,
                normalization_version="v1",
            )
            trans.commit()

        with superuser_engine.connect() as conn:
            persisted = conn.execute(
                text(
                    "SELECT count(*) FROM screening_results "
                    "WHERE screening_result_id = :rid"
                ),
                {"rid": res_id},
            ).scalar()
            assert persisted == 1
    finally:
        _cleanup_test_data(superuser_engine, cid)


# -----------------------------------------------------------------------------
# 8. Sensitive-Name Guard Tests
# -----------------------------------------------------------------------------


def test_sensitive_name_guard_no_canary_leakage_on_failure(
    superuser_engine: Engine, app_role_engine: Engine
) -> None:
    """Refusal and error exception messages must never leak customer or list names."""
    canary_customer = "CANARY_CUSTOMER_SECRET_XYZ"
    canary_watchlist = "CANARY_WATCHLIST_CONFIDENTIAL_123"

    cid = _seed_customer(superuser_engine, full_name=canary_customer)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        # 1. Test missing agent run guard failure
        missing_ar_id = uuid.uuid4()
        with app_role_engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                record_screening_result(
                    conn,
                    investigation_run_id=inv_id,
                    agent_run_id=missing_ar_id,
                    customer_id=cid,
                    outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                    reason_code=None,
                    candidate_count=0,
                    watchlist_name=canary_watchlist,
                    watchlist_version=PINNED_WATCHLIST_VERSION,
                    matching_rule_id=MATCHING_RULE_ID,
                    normalization_version="v1",
                )
            error_msg = str(excinfo.value)
            assert canary_customer not in error_msg
            assert canary_watchlist not in error_msg

        # 2. Test status mismatch guard failure
        failed_ar_id = _seed_agent_run(superuser_engine, inv_id, status="FAILED")
        with app_role_engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                record_screening_result(
                    conn,
                    investigation_run_id=inv_id,
                    agent_run_id=failed_ar_id,
                    customer_id=cid,
                    outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                    reason_code=None,
                    candidate_count=0,
                    watchlist_name=canary_watchlist,
                    watchlist_version=PINNED_WATCHLIST_VERSION,
                    matching_rule_id=MATCHING_RULE_ID,
                    normalization_version="v1",
                )
            error_msg = str(excinfo.value)
            assert canary_customer not in error_msg
            assert canary_watchlist not in error_msg

        # 3. Test input validation failure
        ar_id = _seed_agent_run(superuser_engine, inv_id)
        with app_role_engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                record_screening_result(
                    conn,
                    investigation_run_id=inv_id,
                    agent_run_id=ar_id,
                    customer_id=cid,
                    outcome="BOGUS_OUTCOME",
                    reason_code=None,
                    candidate_count=0,
                    watchlist_name=canary_watchlist,
                    watchlist_version=PINNED_WATCHLIST_VERSION,
                    matching_rule_id=MATCHING_RULE_ID,
                    normalization_version="v1",
                )
            error_msg = str(excinfo.value)
            assert canary_customer not in error_msg
            assert canary_watchlist not in error_msg
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_sensitive_canary_invalid_outcome_not_leaked(
    superuser_engine: Engine, app_role_engine: Engine
) -> None:
    """Invalid outcome values with sensitive canaries must not leak in errors."""
    canary_outcome = "SECRET_CANARY_OUTCOME_PAYLOAD_999"
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with app_role_engine.connect() as conn:
            # 1. Invalid outcome string containing sensitive canary
            with pytest.raises(InvalidScreeningResultInputError) as excinfo:
                record_screening_result(
                    conn,
                    investigation_run_id=inv_id,
                    agent_run_id=ar_id,
                    customer_id=cid,
                    outcome=canary_outcome,
                    reason_code=None,
                    candidate_count=0,
                    watchlist_name=PINNED_WATCHLIST_NAME,
                    watchlist_version=PINNED_WATCHLIST_VERSION,
                    matching_rule_id=MATCHING_RULE_ID,
                    normalization_version="v1",
                )
            error_msg = str(excinfo.value)
            assert canary_outcome not in error_msg
            assert "Unsupported outcome" in error_msg
            assert "must be one of" in error_msg

            # 2. Non-string outcome whose str/repr contains sensitive canary
            class CanaryOutcomeObject:
                def __str__(self) -> str:
                    return canary_outcome

                def __repr__(self) -> str:
                    return canary_outcome

            with pytest.raises(InvalidScreeningResultInputError) as excinfo:
                record_screening_result(
                    conn,
                    investigation_run_id=inv_id,
                    agent_run_id=ar_id,
                    customer_id=cid,
                    outcome=cast(Any, CanaryOutcomeObject()),
                    reason_code=None,
                    candidate_count=0,
                    watchlist_name=PINNED_WATCHLIST_NAME,
                    watchlist_version=PINNED_WATCHLIST_VERSION,
                    matching_rule_id=MATCHING_RULE_ID,
                    normalization_version="v1",
                )
            error_msg = str(excinfo.value)
            assert canary_outcome not in error_msg
            assert "outcome must be a str or ScreeningOutcome instance" in error_msg
    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_sensitive_canary_invalid_reason_code_not_leaked(
    superuser_engine: Engine, app_role_engine: Engine
) -> None:
    """Invalid reason_code with sensitive canaries must not leak in errors."""
    canary_reason = "SECRET_CANARY_REASON_CODE_PAYLOAD_888"
    cid = _seed_customer(superuser_engine)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)
        ar_id = _seed_agent_run(superuser_engine, inv_id)

        with app_role_engine.connect() as conn:
            # 1. Invalid reason_code string with outcome = NOT_PERFORMED
            with pytest.raises(InvalidScreeningResultInputError) as excinfo:
                record_screening_result(
                    conn,
                    investigation_run_id=inv_id,
                    agent_run_id=ar_id,
                    customer_id=cid,
                    outcome=ScreeningOutcome.NOT_PERFORMED,
                    reason_code=canary_reason,
                    candidate_count=0,
                    watchlist_name=PINNED_WATCHLIST_NAME,
                    watchlist_version=PINNED_WATCHLIST_VERSION,
                    matching_rule_id=MATCHING_RULE_ID,
                    normalization_version="v1",
                )
            error_msg = str(excinfo.value)
            assert canary_reason not in error_msg
            assert "Unsupported reason_code" in error_msg
            assert "must be one of" in error_msg

            # 2. Reason code provided when outcome is NO_CANDIDATE_MATCH
            with pytest.raises(InvalidScreeningResultInputError) as excinfo:
                record_screening_result(
                    conn,
                    investigation_run_id=inv_id,
                    agent_run_id=ar_id,
                    customer_id=cid,
                    outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                    reason_code=canary_reason,
                    candidate_count=0,
                    watchlist_name=PINNED_WATCHLIST_NAME,
                    watchlist_version=PINNED_WATCHLIST_VERSION,
                    matching_rule_id=MATCHING_RULE_ID,
                    normalization_version="v1",
                )
            error_msg = str(excinfo.value)
            assert canary_reason not in error_msg
            assert (
                "reason_code must be None when outcome is 'NO_CANDIDATE_MATCH'"
                in error_msg
            )

            # 3. Non-string reason_code with outcome = NO_CANDIDATE_MATCH
            class CanaryReasonObject:
                def __str__(self) -> str:
                    return canary_reason

                def __repr__(self) -> str:
                    return canary_reason

            with pytest.raises(InvalidScreeningResultInputError) as excinfo:
                record_screening_result(
                    conn,
                    investigation_run_id=inv_id,
                    agent_run_id=ar_id,
                    customer_id=cid,
                    outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
                    reason_code=cast(Any, CanaryReasonObject()),
                    candidate_count=0,
                    watchlist_name=PINNED_WATCHLIST_NAME,
                    watchlist_version=PINNED_WATCHLIST_VERSION,
                    matching_rule_id=MATCHING_RULE_ID,
                    normalization_version="v1",
                )
            error_msg = str(excinfo.value)
            assert canary_reason not in error_msg
            assert (
                "reason_code must be a str, AbstentionReason instance, or None"
                in error_msg
            )

            # 4. Non-string reason_code with outcome = NOT_PERFORMED
            with pytest.raises(InvalidScreeningResultInputError) as excinfo:
                record_screening_result(
                    conn,
                    investigation_run_id=inv_id,
                    agent_run_id=ar_id,
                    customer_id=cid,
                    outcome=ScreeningOutcome.NOT_PERFORMED,
                    reason_code=cast(Any, CanaryReasonObject()),
                    candidate_count=0,
                    watchlist_name=PINNED_WATCHLIST_NAME,
                    watchlist_version=PINNED_WATCHLIST_VERSION,
                    matching_rule_id=MATCHING_RULE_ID,
                    normalization_version="v1",
                )
            error_msg = str(excinfo.value)
            assert canary_reason not in error_msg
            assert (
                "reason_code must be a str, AbstentionReason instance, or None"
                in error_msg
            )
    finally:
        _cleanup_test_data(superuser_engine, cid)


# -----------------------------------------------------------------------------
# 9. Architecture and Import Guard Tests
# -----------------------------------------------------------------------------


def test_architecture_persistence_module_boundaries() -> None:
    """Verify screening_results_persistence import and write boundaries."""
    persistence_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "meridian"
        / "orchestration"
        / "screening_results_persistence.py"
    )
    content = persistence_path.read_text()
    tree = ast.parse(content, filename=str(persistence_path))

    # AST check: no imports of investigation_orchestrator or sanctions_agent_dispatch
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "investigation_orchestrator" not in alias.name
                assert "sanctions_agent_dispatch" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            assert "investigation_orchestrator" not in module_name
            assert "sanctions_agent_dispatch" not in module_name

    # Check SQL operations: never writes to agent_runs
    assert "INSERT INTO agent_runs" not in content
    assert "UPDATE agent_runs" not in content
    assert "DELETE FROM agent_runs" not in content

    # Check caller-owned transaction semantics: no commit, rollback, or close calls
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in (
            "commit",
            "rollback",
            "close",
        ):
            raise AssertionError(f"persistence module must not call conn.{node.attr}()")


def test_migration_grant_script_no_unsafe_string_interpolation() -> None:
    """Verify migration grant script does not interpolate role name via f-strings."""
    migration_path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "e82f1b4a9c3d_create_screening_results_table.py"
    )
    content = migration_path.read_text()
    tree = ast.parse(content, filename=str(migration_path))

    upgrade_fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            upgrade_fn = node
            break
    assert upgrade_fn is not None, "upgrade() function not found in migration"

    # Verify grant_script assignment does not use FormattedValue (f-string)
    found_grant_script = False
    for node in ast.walk(upgrade_fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "grant_script":
                    found_grant_script = True
                    for sub_node in ast.walk(node.value):
                        assert not isinstance(sub_node, ast.JoinedStr), (
                            "grant_script must not use f-string interpolation"
                        )
                        assert not isinstance(sub_node, ast.FormattedValue), (
                            "grant_script must not use formatted values"
                        )
    assert found_grant_script, "grant_script assignment not found in upgrade()"
    assert "current_setting('meridian.app_role')" in content
    assert "set_config('meridian.app_role'" in content
