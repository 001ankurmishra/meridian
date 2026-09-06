"""Test suite for alert intake (F1 — create_alert_and_case).

Defines all fixtures locally. No tests/conftest.py dependency.
pytest-xdist is NOT in pyproject.toml — no parallel test execution assumed.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest
from sqlalchemy import Engine, create_engine, text

from meridian.case_management.alert_intake import (
    AlertIntakeResult,
    create_alert_and_case,
)
from meridian.case_management.errors import AlertValidationError

# ---------------------------------------------------------------------------
# Fixtures (all local to this file)
# ---------------------------------------------------------------------------

ADVISORY_LOCK_KEY = 7_299_301_482  # fixed bigint for the rollback test


@pytest.fixture
def superuser_engine() -> Generator[Engine, None, None]:
    """Engine using the migrator/superuser role (DATABASE_URL)."""
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://meridian_user:meridian_pass@localhost:5432/meridian_db",
    )
    engine = create_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def app_engine() -> Generator[Engine, None, None]:
    """Engine using the least-privilege application role (APP_DATABASE_URL)."""
    db_url = os.environ.get(
        "APP_DATABASE_URL",
        "postgresql+psycopg://meridian_app:meridian_app_pass@localhost:5432/meridian_db",
    )
    engine = create_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def clean_alerts_and_cases(
    superuser_engine: Engine,
) -> Generator[None, None, None]:
    """Delete alerts and cases (FK-safe order) before and after each test."""
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))
    yield
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))


@pytest.fixture(autouse=True)
def _defensive_grant_cases_insert(superuser_engine: Engine) -> None:
    """Restore INSERT on cases to meridian_app before every test.

    Protects against a previous interrupted rollback test leaving the
    privilege revoked.
    """
    with superuser_engine.begin() as conn:
        conn.execute(text("GRANT INSERT ON cases TO meridian_app"))


# ---------------------------------------------------------------------------
# Helper to create a test customer + account + transaction via superuser
# ---------------------------------------------------------------------------


def _seed_customer(
    superuser_engine: Engine,
    *,
    customer_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert a minimal customer row and return its ID."""
    cid = customer_id or uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers (customer_id, full_name, is_synthetic, "
                "created_at) VALUES (:cid, :name, true, :now)"
            ),
            {
                "cid": cid,
                "name": f"Test Customer {cid}",
                "now": datetime.now(timezone.utc),
            },
        )
    return cid


def _seed_account(
    superuser_engine: Engine,
    customer_id: uuid.UUID,
    *,
    account_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert a minimal account row and return its ID."""
    aid = account_id or uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (account_id, customer_id, status, created_at) "
                "VALUES (:aid, :cid, 'active', :now)"
            ),
            {"aid": aid, "cid": customer_id, "now": datetime.now(timezone.utc)},
        )
    return aid


def _seed_transaction(
    superuser_engine: Engine,
    source_account_id: uuid.UUID | None,
    destination_account_id: uuid.UUID | None,
    *,
    transaction_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert a minimal transaction row and return its ID."""
    tid = transaction_id or uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions (transaction_id, source_account_id, "
                "destination_account_id, amount, currency, created_at) "
                "VALUES (:tid, :src, :dst, 1000.00, 'INR', :now)"
            ),
            {
                "tid": tid,
                "src": source_account_id,
                "dst": destination_account_id,
                "now": datetime.now(timezone.utc),
            },
        )
    return tid


def _cleanup_seeded_data(superuser_engine: Engine, customer_id: uuid.UUID) -> None:
    """Remove seeded test data for a specific customer (FK-safe order)."""
    with superuser_engine.begin() as conn:
        # Wipe all cases and alerts to avoid cross-customer FK issues
        # when transactions are shared between customers.
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))
        # Delete transactions referencing this customer's accounts
        conn.execute(
            text(
                "DELETE FROM transactions WHERE source_account_id IN "
                "(SELECT account_id FROM accounts WHERE customer_id = :cid) "
                "OR destination_account_id IN "
                "(SELECT account_id FROM accounts WHERE customer_id = :cid)"
            ),
            {"cid": customer_id},
        )
        conn.execute(
            text("DELETE FROM accounts WHERE customer_id = :cid"),
            {"cid": customer_id},
        )
        conn.execute(
            text("DELETE FROM customers WHERE customer_id = :cid"),
            {"cid": customer_id},
        )


# ---------------------------------------------------------------------------
# UNIT TESTS (no DB required)
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Unit tests for input validation — no database connection needed."""

    def test_missing_customer_id(self) -> None:
        """Test 1: None customer_id -> AlertValidationError."""
        with pytest.raises(AlertValidationError, match="customer_id is required"):
            create_alert_and_case(
                engine=create_engine("sqlite://"),  # never reached
                customer_id=None,  # type: ignore[arg-type]
                alert_type="large_transaction",
                alert_reasons=["reason"],
            )

    @pytest.mark.parametrize(
        "bad_type,desc",
        [
            ("", "empty string"),
            ("   ", "whitespace only"),
            (None, "None"),  # type: ignore[list-item]
        ],
        ids=["empty", "whitespace", "none"],
    )
    def test_empty_alert_type(self, bad_type: str, desc: str) -> None:
        """Test 2: Bad alert_type -> AlertValidationError."""
        with pytest.raises(AlertValidationError):
            create_alert_and_case(
                engine=create_engine("sqlite://"),
                customer_id=uuid.uuid4(),
                alert_type=bad_type,  # type: ignore[arg-type]
                alert_reasons=["reason"],
            )

    def test_alert_reasons_none(self) -> None:
        """Test 3: None alert_reasons -> AlertValidationError."""
        with pytest.raises(AlertValidationError, match="must be a dict or list"):
            create_alert_and_case(
                engine=create_engine("sqlite://"),
                customer_id=uuid.uuid4(),
                alert_type="large_transaction",
                alert_reasons=None,  # type: ignore[arg-type]
            )

    def test_alert_reasons_empty_dict(self) -> None:
        """Test 4: Empty dict alert_reasons -> AlertValidationError."""
        with pytest.raises(AlertValidationError, match="must not be empty"):
            create_alert_and_case(
                engine=create_engine("sqlite://"),
                customer_id=uuid.uuid4(),
                alert_type="large_transaction",
                alert_reasons={},
            )

    def test_alert_reasons_empty_list(self) -> None:
        """Test 5: Empty list alert_reasons -> AlertValidationError."""
        with pytest.raises(AlertValidationError, match="must not be empty"):
            create_alert_and_case(
                engine=create_engine("sqlite://"),
                customer_id=uuid.uuid4(),
                alert_type="large_transaction",
                alert_reasons=[],
            )

    def test_alert_reasons_not_json_serializable(self) -> None:
        """Test 6: Non-JSON-serializable alert_reasons -> AlertValidationError."""
        with pytest.raises(AlertValidationError, match="not JSON-serializable"):
            create_alert_and_case(
                engine=create_engine("sqlite://"),
                customer_id=uuid.uuid4(),
                alert_type="large_transaction",
                alert_reasons=[{"bad_value": {1, 2, 3}}],  # type: ignore[list-item]
            )

    def test_alert_reasons_plain_list_accepted(self) -> None:
        """Test 7: Plain list alert_reasons passes validation (no schema imposed).

        We test the validation layer directly: if it passes validation,
        it would only fail at the DB-access stage (which we don't reach
        with a dummy engine).
        """
        # A plain list should pass validation — the error we expect is NOT
        # an AlertValidationError, but rather a connection/DB error because
        # we're using a dummy engine. If validation rejected it, we'd get
        # AlertValidationError.
        with pytest.raises(Exception) as exc_info:
            create_alert_and_case(
                engine=create_engine("sqlite://"),
                customer_id=uuid.uuid4(),
                alert_type="large_transaction",
                alert_reasons=["large_transaction", "new_beneficiary"],
            )
        # Must NOT be a validation error — it should fail on DB access
        assert not isinstance(exc_info.value, AlertValidationError)

    def test_malformed_uuid_string(self) -> None:
        """Test 8: Malformed UUID strings -> AlertValidationError."""
        # Malformed customer_id
        with pytest.raises(AlertValidationError, match="not a valid UUID"):
            create_alert_and_case(
                engine=create_engine("sqlite://"),
                customer_id="not-a-uuid",  # type: ignore[arg-type]
                alert_type="large_transaction",
                alert_reasons=["reason"],
            )

        # Malformed transaction_id
        with pytest.raises(AlertValidationError, match="not a valid UUID"):
            create_alert_and_case(
                engine=create_engine("sqlite://"),
                customer_id=uuid.uuid4(),
                alert_type="large_transaction",
                alert_reasons=["reason"],
                transaction_id="also-not-a-uuid",  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# INTEGRATION TESTS (real Postgres)
# ---------------------------------------------------------------------------


class TestIntegration:
    """Integration tests against real PostgreSQL."""

    def test_valid_alert_no_transaction(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        clean_alerts_and_cases: None,
    ) -> None:
        """Test 9: Valid alert without transaction_id."""
        cid = _seed_customer(superuser_engine)
        try:
            result = create_alert_and_case(
                engine=app_engine,
                customer_id=cid,
                alert_type="large_transaction",
                alert_reasons=["large_transaction"],
            )
            assert isinstance(result, AlertIntakeResult)
            assert isinstance(result.alert_id, uuid.UUID)
            assert isinstance(result.case_id, uuid.UUID)

            with superuser_engine.connect() as conn:
                # Verify exactly one alert row
                alert_row = conn.execute(
                    text(
                        "SELECT alert_id, customer_id "
                        "FROM alerts WHERE alert_id = :aid"
                    ),
                    {"aid": result.alert_id},
                ).fetchone()
                assert alert_row is not None
                assert alert_row[1] == cid

                # Verify exactly one case row, linked to the alert
                case_row = conn.execute(
                    text(
                        "SELECT case_id, alert_id, status FROM cases "
                        "WHERE case_id = :cid"
                    ),
                    {"cid": result.case_id},
                ).fetchone()
                assert case_row is not None
                assert case_row[1] == result.alert_id
                assert case_row[2] == "OPEN"
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_valid_alert_transaction_owned_via_source(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        clean_alerts_and_cases: None,
    ) -> None:
        """Test 10: Customer owns transaction via source account."""
        cid = _seed_customer(superuser_engine)
        other_cid = _seed_customer(superuser_engine)
        try:
            src_aid = _seed_account(superuser_engine, cid)
            dst_aid = _seed_account(superuser_engine, other_cid)
            tid = _seed_transaction(superuser_engine, src_aid, dst_aid)

            result = create_alert_and_case(
                engine=app_engine,
                customer_id=cid,
                transaction_id=tid,
                alert_type="large_transaction",
                alert_reasons={"reason": "source_owned"},
            )
            assert isinstance(result, AlertIntakeResult)
        finally:
            _cleanup_seeded_data(superuser_engine, other_cid)
            _cleanup_seeded_data(superuser_engine, cid)

    def test_valid_alert_transaction_owned_via_destination(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        clean_alerts_and_cases: None,
    ) -> None:
        """Test 11: Customer owns transaction via destination account only."""
        cid = _seed_customer(superuser_engine)
        other_cid = _seed_customer(superuser_engine)
        try:
            src_aid = _seed_account(superuser_engine, other_cid)
            dst_aid = _seed_account(superuser_engine, cid)
            tid = _seed_transaction(superuser_engine, src_aid, dst_aid)

            result = create_alert_and_case(
                engine=app_engine,
                customer_id=cid,
                transaction_id=tid,
                alert_type="large_transaction",
                alert_reasons={"reason": "destination_owned"},
            )
            assert isinstance(result, AlertIntakeResult)
        finally:
            _cleanup_seeded_data(superuser_engine, other_cid)
            _cleanup_seeded_data(superuser_engine, cid)

    def test_nonexistent_customer_id(
        self,
        app_engine: Engine,
        superuser_engine: Engine,
        clean_alerts_and_cases: None,
    ) -> None:
        """Test 12: Nonexistent customer_id -> AlertValidationError, zero rows."""
        fake_cid = uuid.uuid4()
        with pytest.raises(AlertValidationError, match="does not exist"):
            create_alert_and_case(
                engine=app_engine,
                customer_id=fake_cid,
                alert_type="large_transaction",
                alert_reasons=["reason"],
            )
        # Verify zero rows persisted
        with superuser_engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM alerts WHERE customer_id = :cid"),
                {"cid": fake_cid},
            ).scalar()
            assert count == 0

    def test_nonexistent_transaction_id(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        clean_alerts_and_cases: None,
    ) -> None:
        """Test 13: Valid customer, nonexistent transaction -> AlertValidationError."""
        cid = _seed_customer(superuser_engine)
        try:
            fake_tid = uuid.uuid4()
            with pytest.raises(AlertValidationError, match="does not exist"):
                create_alert_and_case(
                    engine=app_engine,
                    customer_id=cid,
                    transaction_id=fake_tid,
                    alert_type="large_transaction",
                    alert_reasons=["reason"],
                )
            # Verify zero rows
            with superuser_engine.connect() as conn:
                count = conn.execute(
                    text("SELECT count(*) FROM alerts WHERE customer_id = :cid"),
                    {"cid": cid},
                ).scalar()
                assert count == 0
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_transaction_belongs_to_different_customer(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        clean_alerts_and_cases: None,
    ) -> None:
        """Test 14: Transaction belongs to Customer B, called with Customer A."""
        cust_a = _seed_customer(superuser_engine)
        cust_b = _seed_customer(superuser_engine)
        try:
            acct_b = _seed_account(superuser_engine, cust_b)
            _seed_account(superuser_engine, cust_a)  # so cust_a exists with an account
            tid = _seed_transaction(superuser_engine, acct_b, None)

            with pytest.raises(
                AlertValidationError,
                match="does not exist or does not belong",
            ):
                create_alert_and_case(
                    engine=app_engine,
                    customer_id=cust_a,
                    transaction_id=tid,
                    alert_type="large_transaction",
                    alert_reasons=["reason"],
                )
            # Verify zero rows
            with superuser_engine.connect() as conn:
                count = conn.execute(
                    text("SELECT count(*) FROM alerts WHERE customer_id = :cid"),
                    {"cid": cust_a},
                ).scalar()
                assert count == 0
        finally:
            _cleanup_seeded_data(superuser_engine, cust_b)
            _cleanup_seeded_data(superuser_engine, cust_a)

    def test_source_system_omitted_persists_null(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        clean_alerts_and_cases: None,
    ) -> None:
        """Test 15: Omitting source_system persists NULL."""
        cid = _seed_customer(superuser_engine)
        try:
            result = create_alert_and_case(
                engine=app_engine,
                customer_id=cid,
                alert_type="test_alert",
                alert_reasons=["test"],
                # source_system intentionally omitted
            )
            with superuser_engine.connect() as conn:
                val = conn.execute(
                    text("SELECT source_system FROM alerts WHERE alert_id = :aid"),
                    {"aid": result.alert_id},
                ).scalar()
                assert val is None
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_source_system_supplied_persists_exact_value(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        clean_alerts_and_cases: None,
    ) -> None:
        """Test 16: Supplied source_system persists exactly."""
        cid = _seed_customer(superuser_engine)
        try:
            result = create_alert_and_case(
                engine=app_engine,
                customer_id=cid,
                alert_type="test_alert",
                alert_reasons=["test"],
                source_system="synthetic-monitoring-generator",
            )
            with superuser_engine.connect() as conn:
                val = conn.execute(
                    text("SELECT source_system FROM alerts WHERE alert_id = :aid"),
                    {"aid": result.alert_id},
                ).scalar()
                assert val == "synthetic-monitoring-generator"
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_raised_at_omitted_generates_utc_now(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        clean_alerts_and_cases: None,
    ) -> None:
        """Test 17: Omitted raised_at generates a UTC-now timestamp."""
        cid = _seed_customer(superuser_engine)
        try:
            before = datetime.now(timezone.utc)
            result = create_alert_and_case(
                engine=app_engine,
                customer_id=cid,
                alert_type="test_alert",
                alert_reasons=["test"],
            )
            after = datetime.now(timezone.utc)

            with superuser_engine.connect() as conn:
                val = conn.execute(
                    text("SELECT raised_at FROM alerts WHERE alert_id = :aid"),
                    {"aid": result.alert_id},
                ).scalar()
                assert val is not None
                assert val.tzinfo is not None  # timezone-aware
                lo = before - timedelta(seconds=5)
                hi = after + timedelta(seconds=5)
                assert lo <= val <= hi
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_raised_at_supplied_persists_exact_value(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        clean_alerts_and_cases: None,
    ) -> None:
        """Test 18: Supplied raised_at persists exactly."""
        cid = _seed_customer(superuser_engine)
        try:
            specific_time = datetime(2025, 6, 15, 12, 30, 0, tzinfo=timezone.utc)
            result = create_alert_and_case(
                engine=app_engine,
                customer_id=cid,
                alert_type="test_alert",
                alert_reasons=["test"],
                raised_at=specific_time,
            )
            with superuser_engine.connect() as conn:
                val = conn.execute(
                    text("SELECT raised_at FROM alerts WHERE alert_id = :aid"),
                    {"aid": result.alert_id},
                ).scalar()
                assert val == specific_time
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_rollback_on_real_db_failure(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        clean_alerts_and_cases: None,
    ) -> None:
        """Test 19: Real PostgreSQL permission failure causes full rollback.

        Uses the unmodified production create_alert_and_case(). The alerts
        INSERT succeeds (meridian_app has INSERT on alerts), but the cases
        INSERT fails because we REVOKE INSERT ON cases FROM meridian_app.
        The entire transaction (including the alerts row) must be rolled back.
        """
        # Create a test-specific customer
        cid = _seed_customer(superuser_engine)

        # Use ONE long-lived superuser connection for privilege control
        su_conn = superuser_engine.connect()
        try:
            # 1-2. Acquire advisory lock on the superuser connection
            su_conn.execute(
                text(f"SELECT pg_advisory_lock({ADVISORY_LOCK_KEY})")
            )

            # 3. REVOKE INSERT on cases from meridian_app
            su_conn.execute(text("REVOKE INSERT ON cases FROM meridian_app"))
            su_conn.commit()

            # 4. Call the real production function — expects permission denied
            with pytest.raises(Exception) as exc_info:
                create_alert_and_case(
                    engine=app_engine,
                    customer_id=cid,
                    alert_type="rollback_test",
                    alert_reasons=["testing_rollback"],
                )

            # 5. Assert the exception was raised (permission denied)
            assert "permission denied" in str(exc_info.value).lower()

            # 6. Verify rollback using a FRESH, SEPARATE connection
            verify_engine = create_engine(
                os.environ.get(
                    "DATABASE_URL",
                    "postgresql+psycopg://meridian_user:meridian_pass@localhost:5432/meridian_db",
                )
            )
            try:
                with verify_engine.connect() as verify_conn:
                    alert_count = verify_conn.execute(
                        text(
                            "SELECT count(*) FROM alerts "
                            "WHERE customer_id = :cid"
                        ),
                        {"cid": cid},
                    ).scalar()
                    assert alert_count == 0, (
                        f"Expected 0 orphan alerts after rollback, found {alert_count}"
                    )
            finally:
                verify_engine.dispose()

        finally:
            # 7. GRANT INSERT back and release advisory lock (mandatory finally)
            su_conn.execute(text("GRANT INSERT ON cases TO meridian_app"))
            su_conn.execute(
                text(f"SELECT pg_advisory_unlock({ADVISORY_LOCK_KEY})")
            )
            su_conn.commit()
            # 8. Close the superuser connection
            su_conn.close()
            _cleanup_seeded_data(superuser_engine, cid)

    def test_worked_example_rahul_sharma(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        clean_alerts_and_cases: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test 20: End-to-end with the Rahul Sharma worked example."""
        from meridian.loader.main import main

        # loader main() requires these environment variables
        db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://meridian_user:meridian_pass@localhost:5432/meridian_db",
        )
        loader_url = os.environ.get(
            "LOADER_DATABASE_URL",
            "postgresql+psycopg://meridian_loader:meridian_loader_pass@localhost:5432/meridian_db",
        )
        monkeypatch.setenv("DATABASE_URL", db_url)
        monkeypatch.setenv("LOADER_DATABASE_URL", loader_url)

        main()

        # Recompute IDs via the identical derivation from worked_example.py
        rahul_id = uuid.uuid5(uuid.NAMESPACE_OID, "rahul_sharma")
        suspicious_tx_id = uuid.uuid5(uuid.NAMESPACE_OID, "rahul_to_tech_sol_tx")

        try:
            result = create_alert_and_case(
                engine=app_engine,
                customer_id=rahul_id,
                transaction_id=suspicious_tx_id,
                alert_type="large_transaction",
                alert_reasons=["large_transaction", "new_beneficiary"],
            )

            assert isinstance(result, AlertIntakeResult)

            with superuser_engine.connect() as conn:
                # Verify alert
                alert_row = conn.execute(
                    text(
                        "SELECT customer_id, transaction_id FROM alerts "
                        "WHERE alert_id = :aid"
                    ),
                    {"aid": result.alert_id},
                ).fetchone()
                assert alert_row is not None
                assert alert_row[0] == rahul_id
                assert alert_row[1] == suspicious_tx_id

                # Verify case links to alert
                case_row = conn.execute(
                    text("SELECT alert_id FROM cases WHERE case_id = :cid"),
                    {"cid": result.case_id},
                ).fetchone()
                assert case_row is not None
                assert case_row[0] == result.alert_id
        finally:
            # Clean up ALL loader data to prevent test isolation failures
            # in test_db_migrations.py which expects an empty database.
            with superuser_engine.begin() as conn:
                conn.execute(text("TRUNCATE TABLE customers CASCADE"))
