"""Tests for SanctionsAgent dispatch (Task 24 Stage 1).

Verifies:
- Candidate and no-candidate screening outcomes.
- Controlled abstentions (CUSTOMER_NAME_MISSING,
  CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION,
  WATCHLIST_VERSION_NOT_LOADED) and their SUCCESS tracking status.
- Controlled abstention precedence (WATCHLIST_VERSION_NOT_LOADED over name).
- Nonexistent customer ID and invalid customer ID behavior (UNEXPECTED_ERROR).
- Nonexistent investigation-run behavior (tracking-layer foreign-key failure).
- Technical failures (WATCHLIST_INTEGRITY_VIOLATION,
  NORMALIZATION_VERSION_MISMATCH, DATABASE_ERROR, UNEXPECTED_ERROR)
  and FAILED tracking status with approved reason codes.
- Sanitization of screening-path errors, including canary strings in
  messages, arguments, and chained causes.
- Static tool-call metadata containing no customer or watchlist data.
- Pinned watchlist behavior (no latest-version lookup, env var override,
  or dynamic pins).
- Confirmation that record_agent_run() remains unchanged.
"""

from __future__ import annotations

import ast
import datetime as dt
import inspect
import uuid
from pathlib import Path
from typing import Any, Generator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from meridian.agents.sanctions.errors import (
    NormalizationVersionMismatch,
    WatchlistIntegrityViolation,
    WatchlistValidationError,
)
from meridian.agents.sanctions.types import (
    AbstentionReason,
    ScreeningOutcome,
)
from meridian.loader.watchlist_corpus import get_synthetic_watchlist_corpus
from meridian.loader.watchlist_ingest import ingest_watchlist_version
from meridian.orchestration.sanctions_agent_dispatch import (
    _SANCTIONS_AGENT_TOOL_CALLS,
    APPROVED_TECHNICAL_ERROR_CODES,
    PINNED_WATCHLIST_NAME,
    PINNED_WATCHLIST_VERSION,
    REASON_DATABASE_ERROR,
    REASON_NORMALIZATION_VERSION_MISMATCH,
    REASON_UNEXPECTED_ERROR,
    REASON_WATCHLIST_INTEGRITY_VIOLATION,
    SanctionsAgentDispatchResult,
    SanctionsDispatchError,
    run_sanctions_agent,
)
from tests.db_cleanup import clean_investigation_run_dependencies

CANARY_SECRET_NAME = "CanaryCustomerSecret 1980-05-14"
CANARY_SECRET_DOB = "1980-05-14"
CANARY_SECRET_SUBJ = "SUBJ-CANARY-999"


@pytest.fixture(autouse=True)
def clean_watchlist_entries(superuser_engine: Engine) -> Generator[None, None, None]:
    """Clean watchlist_entries before and after each test."""
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM watchlist_entries"))
    yield
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM watchlist_entries"))


def _seed_customer(
    superuser_engine: Engine,
    full_name: str | None = "Aurelius Vance",
    dob: dt.date | None = dt.date(1980, 5, 14),
) -> uuid.UUID:
    """Seed a synthetic customer for dispatch tests."""
    cid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers ("
                "    customer_id, full_name, date_of_birth, is_synthetic, created_at"
                ") VALUES ("
                "    :cid, :name, :dob, true, :now"
                ")"
            ),
            {
                "cid": cid,
                "name": full_name,
                "dob": dob,
                "now": dt.datetime.now(dt.timezone.utc),
            },
        )
    return cid


def _seed_alert_case_investigation(
    superuser_engine: Engine,
    customer_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed minimal alert, case, and investigation_run hierarchy."""
    alert_id = uuid.uuid4()
    case_id = uuid.uuid4()
    inv_id = uuid.uuid4()
    now = dt.datetime.now(dt.timezone.utc)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, alert_type, created_at) "
                "VALUES (:aid, :cid, 'SANCTIONS_SCREENING', :now)"
            ),
            {"aid": alert_id, "cid": customer_id, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status, opened_at, created_at) "
                "VALUES (:case_id, :aid, 'OPEN', :now, :now)"
            ),
            {"case_id": case_id, "aid": alert_id, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO investigation_runs ("
                "    investigation_run_id, case_id, status, started_at"
                ") VALUES ("
                "    :inv_id, :case_id, 'IN_PROGRESS', :now"
                ")"
            ),
            {"inv_id": inv_id, "case_id": case_id, "now": now},
        )
    return alert_id, case_id, inv_id


def _cleanup_test_data(superuser_engine: Engine, customer_id: uuid.UUID) -> None:
    """Clean investigation dependencies and test customer."""
    with superuser_engine.begin() as conn:
        clean_investigation_run_dependencies(conn)
        conn.execute(text("DELETE FROM audit_events"))
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(
            text("DELETE FROM customers WHERE customer_id = :cid"),
            {"cid": customer_id},
        )


def _load_synthetic_watchlist(loader_role_engine: Engine) -> None:
    """Load the pinned synthetic watchlist corpus."""
    corpus = get_synthetic_watchlist_corpus()
    ingest_watchlist_version(loader_role_engine, corpus)


# --------------------------------------------------------------------------
# Screening Outcomes (Candidate vs No Candidate)
# --------------------------------------------------------------------------


def test_dispatch_candidate_matches_found(
    app_role_engine: Engine,
    loader_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Customer matching a watchlist subject yields CANDIDATE_MATCHES_FOUND."""
    _load_synthetic_watchlist(loader_role_engine)
    cid = _seed_customer(superuser_engine, full_name="Aurelius Vance")
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        res = run_sanctions_agent(app_role_engine, inv_id, cid)

        assert isinstance(res, SanctionsAgentDispatchResult)
        assert res.investigation_run_id == inv_id
        assert res.result.outcome == ScreeningOutcome.CANDIDATE_MATCHES_FOUND
        assert res.result.reason_code is None
        assert len(res.result.candidates) > 0
        assert res.result.watchlist_name == PINNED_WATCHLIST_NAME
        assert res.result.watchlist_version == PINNED_WATCHLIST_VERSION

        # Verify DB record in agent_runs
        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, error, tool_calls, agent_name "
                    "FROM agent_runs WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "SUCCESS"
            assert rows[0][1] is None
            assert rows[0][2] == _SANCTIONS_AGENT_TOOL_CALLS
            assert rows[0][3] == "SanctionsAgent"

    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_dispatch_no_candidate_match(
    app_role_engine: Engine,
    loader_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Customer not matching any watchlist subject yields NO_CANDIDATE_MATCH."""
    _load_synthetic_watchlist(loader_role_engine)
    cid = _seed_customer(superuser_engine, full_name="Unique Unlisted Citizen")
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        res = run_sanctions_agent(app_role_engine, inv_id, cid)

        assert isinstance(res, SanctionsAgentDispatchResult)
        assert res.result.outcome == ScreeningOutcome.NO_CANDIDATE_MATCH
        assert res.result.reason_code is None
        assert len(res.result.candidates) == 0

        # Verify DB record in agent_runs
        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "SUCCESS"
            assert rows[0][1] is None

    finally:
        _cleanup_test_data(superuser_engine, cid)


# --------------------------------------------------------------------------
# Controlled Abstentions (SUCCESS status)
# --------------------------------------------------------------------------


def test_dispatch_abstention_customer_name_missing(
    app_role_engine: Engine,
    loader_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Customer with NULL name produces NOT_PERFORMED(CUSTOMER_NAME_MISSING)."""
    _load_synthetic_watchlist(loader_role_engine)
    cid = _seed_customer(superuser_engine, full_name=None)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        res = run_sanctions_agent(app_role_engine, inv_id, cid)

        assert res.result.outcome == ScreeningOutcome.NOT_PERFORMED
        assert res.result.reason_code == AbstentionReason.CUSTOMER_NAME_MISSING
        assert len(res.result.candidates) == 0

        # Status must be SUCCESS per ADR-0008 D8
        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "SUCCESS"
            assert rows[0][1] is None

    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_dispatch_abstention_customer_name_empty_after_normalization(
    app_role_engine: Engine,
    loader_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Whitespace-only name produces NOT_PERFORMED(CUSTOMER_NAME_EMPTY_...)."""
    _load_synthetic_watchlist(loader_role_engine)
    cid = _seed_customer(superuser_engine, full_name="   \t  \u00a0  ")
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        res = run_sanctions_agent(app_role_engine, inv_id, cid)

        assert res.result.outcome == ScreeningOutcome.NOT_PERFORMED
        assert (
            res.result.reason_code
            == AbstentionReason.CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION
        )
        assert len(res.result.candidates) == 0

        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "SUCCESS"
            assert rows[0][1] is None

    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_dispatch_abstention_watchlist_version_not_loaded(
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """When pinned watchlist version is empty, yields WATCHLIST_VERSION_NOT_LOADED."""
    # Ensure watchlist_entries has zero rows
    cid = _seed_customer(superuser_engine, full_name="Aurelius Vance")
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        res = run_sanctions_agent(app_role_engine, inv_id, cid)

        assert res.result.outcome == ScreeningOutcome.NOT_PERFORMED
        assert (
            res.result.reason_code
            == AbstentionReason.WATCHLIST_VERSION_NOT_LOADED
        )
        assert len(res.result.candidates) == 0

        # Status must be SUCCESS per ADR-0008 D8
        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "SUCCESS"
            assert rows[0][1] is None

    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_dispatch_abstention_precedence(
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """WATCHLIST_VERSION_NOT_LOADED takes precedence over CUSTOMER_NAME_MISSING."""
    # Watchlist is not loaded AND customer name is None
    cid = _seed_customer(superuser_engine, full_name=None)
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        res = run_sanctions_agent(app_role_engine, inv_id, cid)

        assert res.result.outcome == ScreeningOutcome.NOT_PERFORMED
        assert (
            res.result.reason_code
            == AbstentionReason.WATCHLIST_VERSION_NOT_LOADED
        )

        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "SUCCESS"
            assert rows[0][1] is None

    finally:
        _cleanup_test_data(superuser_engine, cid)


# --------------------------------------------------------------------------
# Customer Validation Failures (Technical Failures)
# --------------------------------------------------------------------------


def test_dispatch_nonexistent_customer_is_technical_failure(
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Nonexistent customer_id is a technical failure mapped to UNEXPECTED_ERROR."""
    dummy_cid = _seed_customer(superuser_engine, full_name="Temp")
    _, _, inv_id = _seed_alert_case_investigation(superuser_engine, dummy_cid)
    missing_cid = uuid.uuid4()

    try:
        with pytest.raises(SanctionsDispatchError) as exc_info:
            run_sanctions_agent(app_role_engine, inv_id, missing_cid)

        assert str(exc_info.value) == REASON_UNEXPECTED_ERROR
        assert exc_info.value.reason_code == REASON_UNEXPECTED_ERROR

        # Verify DB record in agent_runs
        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "FAILED"
            assert rows[0][1] == REASON_UNEXPECTED_ERROR

    finally:
        _cleanup_test_data(superuser_engine, dummy_cid)


def test_dispatch_invalid_customer_id_types(
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Invalid customer ID argument raises SanctionsDispatchError(UNEXPECTED_ERROR)."""
    dummy_cid = _seed_customer(superuser_engine, full_name="Temp")
    _, _, inv_id = _seed_alert_case_investigation(superuser_engine, dummy_cid)

    try:
        # 1. Non-UUID string
        with pytest.raises(SanctionsDispatchError) as exc1:
            run_sanctions_agent(app_role_engine, inv_id, "invalid-uuid-string")  # type: ignore[arg-type]
        assert str(exc1.value) == REASON_UNEXPECTED_ERROR

        # 2. None
        with pytest.raises(SanctionsDispatchError) as exc2:
            run_sanctions_agent(app_role_engine, inv_id, None)  # type: ignore[arg-type]
        assert str(exc2.value) == REASON_UNEXPECTED_ERROR

    finally:
        _cleanup_test_data(superuser_engine, dummy_cid)


# --------------------------------------------------------------------------
# Nonexistent Investigation Run Behavior (Tracking Layer)
# --------------------------------------------------------------------------


def test_dispatch_nonexistent_investigation_run_raises_db_error(
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Nonexistent investigation_run_id fails in record_agent_run() DB persistence.

    Asserts existing record_agent_run() behavior: raises DBAPIError / IntegrityError,
    persisting no row in agent_runs.
    """
    cid = _seed_customer(superuser_engine, full_name="Aurelius Vance")
    non_existent_inv_id = uuid.uuid4()

    try:
        with pytest.raises((SQLAlchemyError, DBAPIError)):
            run_sanctions_agent(app_role_engine, non_existent_inv_id, cid)

        # Confirm no agent_runs row exists
        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT agent_run_id FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": non_existent_inv_id},
            ).fetchall()
            assert len(rows) == 0

    finally:
        _cleanup_test_data(superuser_engine, cid)


# --------------------------------------------------------------------------
# Technical Screening Failures and Exception Sanitization
# --------------------------------------------------------------------------


def test_dispatch_watchlist_integrity_violation(
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WatchlistIntegrityViolation maps to WATCHLIST_INTEGRITY_VIOLATION."""
    cid = _seed_customer(superuser_engine, full_name="Aurelius Vance")
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        import meridian.orchestration.sanctions_agent_dispatch as dispatch_mod

        def _raise_integrity(*args: Any, **kwargs: Any) -> Any:
            raise WatchlistIntegrityViolation(f"corrupt {CANARY_SECRET_NAME}")

        monkeypatch.setattr(dispatch_mod, "read_watchlist_version", _raise_integrity)

        with pytest.raises(SanctionsDispatchError) as exc_info:
            run_sanctions_agent(app_role_engine, inv_id, cid)

        assert str(exc_info.value) == REASON_WATCHLIST_INTEGRITY_VIOLATION
        assert exc_info.value.reason_code == REASON_WATCHLIST_INTEGRITY_VIOLATION
        assert CANARY_SECRET_NAME not in str(exc_info.value)

        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "FAILED"
            assert rows[0][1] == REASON_WATCHLIST_INTEGRITY_VIOLATION

    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_dispatch_watchlist_validation_error(
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WatchlistValidationError maps to WATCHLIST_INTEGRITY_VIOLATION."""
    cid = _seed_customer(superuser_engine, full_name="Aurelius Vance")
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        import meridian.orchestration.sanctions_agent_dispatch as dispatch_mod

        def _raise_val(*args: Any, **kwargs: Any) -> Any:
            raise WatchlistValidationError("bad structure")

        monkeypatch.setattr(dispatch_mod, "read_watchlist_version", _raise_val)

        with pytest.raises(SanctionsDispatchError) as exc_info:
            run_sanctions_agent(app_role_engine, inv_id, cid)

        assert str(exc_info.value) == REASON_WATCHLIST_INTEGRITY_VIOLATION

        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "FAILED"
            assert rows[0][1] == REASON_WATCHLIST_INTEGRITY_VIOLATION

    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_dispatch_normalization_version_mismatch(
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NormalizationVersionMismatch maps to NORMALIZATION_VERSION_MISMATCH."""
    cid = _seed_customer(superuser_engine, full_name="Aurelius Vance")
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        import meridian.orchestration.sanctions_agent_dispatch as dispatch_mod

        def _raise_mismatch(*args: Any, **kwargs: Any) -> Any:
            raise NormalizationVersionMismatch("v2 not expected")

        monkeypatch.setattr(
            dispatch_mod, "match_customer_against_watchlist", _raise_mismatch
        )

        with pytest.raises(SanctionsDispatchError) as exc_info:
            run_sanctions_agent(app_role_engine, inv_id, cid)

        assert str(exc_info.value) == REASON_NORMALIZATION_VERSION_MISMATCH

        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "FAILED"
            assert rows[0][1] == REASON_NORMALIZATION_VERSION_MISMATCH

    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_dispatch_screening_database_error(
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLAlchemyError during screening maps to DATABASE_ERROR."""
    cid = _seed_customer(superuser_engine, full_name="Aurelius Vance")
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        import meridian.orchestration.sanctions_agent_dispatch as dispatch_mod

        def _raise_sql_err(*args: Any, **kwargs: Any) -> Any:
            raise SQLAlchemyError(f"syntax error select {CANARY_SECRET_NAME}")

        monkeypatch.setattr(dispatch_mod, "read_watchlist_version", _raise_sql_err)

        with pytest.raises(SanctionsDispatchError) as exc_info:
            run_sanctions_agent(app_role_engine, inv_id, cid)

        assert str(exc_info.value) == REASON_DATABASE_ERROR
        assert CANARY_SECRET_NAME not in str(exc_info.value)

        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "FAILED"
            assert rows[0][1] == REASON_DATABASE_ERROR

    finally:
        _cleanup_test_data(superuser_engine, cid)


def test_dispatch_unexpected_error(
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unhandled generic exception maps to UNEXPECTED_ERROR."""
    cid = _seed_customer(superuser_engine, full_name="Aurelius Vance")
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        import meridian.orchestration.sanctions_agent_dispatch as dispatch_mod

        def _raise_runtime(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(f"crash with secret: {CANARY_SECRET_NAME}")

        monkeypatch.setattr(
            dispatch_mod, "match_customer_against_watchlist", _raise_runtime
        )

        with pytest.raises(SanctionsDispatchError) as exc_info:
            run_sanctions_agent(app_role_engine, inv_id, cid)

        assert str(exc_info.value) == REASON_UNEXPECTED_ERROR
        assert CANARY_SECRET_NAME not in str(exc_info.value)

        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "FAILED"
            assert rows[0][1] == REASON_UNEXPECTED_ERROR

    finally:
        _cleanup_test_data(superuser_engine, cid)


# --------------------------------------------------------------------------
# Canary String Leak / Sanitization Guard
# --------------------------------------------------------------------------


def test_dispatch_canary_sanitization_guarantee(
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Distinctive canary strings must never leak into DB error or exception."""
    cid = _seed_customer(superuser_engine, full_name="Aurelius Vance")
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        import meridian.orchestration.sanctions_agent_dispatch as dispatch_mod

        class ChainedCanaryException(Exception):
            pass

        def _raise_nested_canary(*args: Any, **kwargs: Any) -> Any:
            cause = ChainedCanaryException(
                f"Cause leak: {CANARY_SECRET_NAME}, {CANARY_SECRET_DOB}"
            )
            exc = ValueError(f"Direct leak: {CANARY_SECRET_SUBJ}")
            exc.__cause__ = cause
            raise exc

        monkeypatch.setattr(
            dispatch_mod, "read_watchlist_version", _raise_nested_canary
        )

        with pytest.raises(SanctionsDispatchError) as exc_info:
            run_sanctions_agent(app_role_engine, inv_id, cid)

        err_str = str(exc_info.value)
        assert err_str in APPROVED_TECHNICAL_ERROR_CODES
        assert CANARY_SECRET_NAME not in err_str
        assert CANARY_SECRET_DOB not in err_str
        assert CANARY_SECRET_SUBJ not in err_str
        assert exc_info.value.__cause__ is None

        # Verify DB error column
        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            db_error = rows[0][1]
            assert db_error == REASON_UNEXPECTED_ERROR
            assert CANARY_SECRET_NAME not in db_error
            assert CANARY_SECRET_DOB not in db_error
            assert CANARY_SECRET_SUBJ not in db_error

    finally:
        _cleanup_test_data(superuser_engine, cid)


# --------------------------------------------------------------------------
# Static Tool Calls and Explicit Agent Run ID
# --------------------------------------------------------------------------


def test_dispatch_static_tool_calls_content() -> None:
    """Verify tool_calls metadata contains no customer, watchlist name, or results."""
    tool_calls = _SANCTIONS_AGENT_TOOL_CALLS
    assert tool_calls["tool"] == "sql_query"
    queries = tool_calls["queries"]
    assert isinstance(queries, list)
    assert len(queries) == 2

    # Prohibited patterns in static metadata
    prohibited = ["Aurelius", "Vance", "meridian_synthetic_watchlist", "v1", "MATCH"]
    for q in queries:
        for p in prohibited:
            assert p not in q, f"Prohibited string '{p}' in tool_calls query: {q}"


def test_dispatch_explicit_agent_run_id(
    app_role_engine: Engine,
    loader_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Explicit agent_run_id is passed and stored accurately in agent_runs."""
    _load_synthetic_watchlist(loader_role_engine)
    cid = _seed_customer(superuser_engine, full_name="Aurelius Vance")
    explicit_ar_id = uuid.uuid4()
    try:
        _, _, inv_id = _seed_alert_case_investigation(superuser_engine, cid)

        res = run_sanctions_agent(
            app_role_engine, inv_id, cid, agent_run_id=explicit_ar_id
        )
        assert res.result.outcome == ScreeningOutcome.CANDIDATE_MATCHES_FOUND

        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT agent_run_id, status FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == explicit_ar_id
            assert rows[0][1] == "SUCCESS"

    finally:
        _cleanup_test_data(superuser_engine, cid)


# --------------------------------------------------------------------------
# Architecture & Pinned Watchlist Invariants
# --------------------------------------------------------------------------


def test_pinned_watchlist_constants_and_ast_guards() -> None:
    """Ensure watchlist is pinned in code, without env lookups or dynamic parameters."""
    assert PINNED_WATCHLIST_NAME == "meridian_synthetic_watchlist"
    assert PINNED_WATCHLIST_VERSION == "v1"

    # Signature must not accept watchlist name or version
    sig = inspect.signature(run_sanctions_agent)
    params = list(sig.parameters.keys())
    assert "watchlist_name" not in params
    assert "watchlist_version" not in params
    assert params == ["engine", "investigation_run_id", "customer_id", "agent_run_id"]

    # AST check: no os.environ or os.getenv in dispatch module
    dispatch_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "meridian"
        / "orchestration"
        / "sanctions_agent_dispatch.py"
    )
    tree = ast.parse(dispatch_path.read_text(), filename=str(dispatch_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
            raise AssertionError(f"Dynamic env lookup found in dispatch: {node.attr}")


def test_record_agent_run_uses_bounded_errors() -> None:
    """Verify tracking persists bounded diagnostics without raw exception text."""
    tracking_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "meridian"
        / "orchestration"
        / "agent_run_tracking.py"
    )
    content = tracking_path.read_text()
    assert "def record_agent_run(" in content
    assert '"error": error_code(e),' in content
    assert '"error": str(e),' not in content
    assert "INSERT INTO agent_runs (" in content
