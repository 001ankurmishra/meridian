"""Test suite for amount deviation analysis (F3 Slice 1).

Defines all fixtures locally. No tests/conftest.py dependency.
pytest-xdist is NOT in pyproject.toml — no parallel test execution assumed.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Generator

import pytest
from sqlalchemy import Engine, create_engine, text

from meridian.agents.transaction.amount_deviation import (
    AmountDeviationComputed,
    AmountDeviationUnknown,
    compute_amount_deviation,
)
from meridian.agents.transaction.errors import (
    InvalidTransactionError,
    TransactionNotFoundError,
)

# ---------------------------------------------------------------------------
# Fixtures (all local to this file)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Seed helpers (duplicated from test_alert_intake.py by design)
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
    *,
    transaction_id: uuid.UUID | None = None,
    source_account_id: uuid.UUID | None = None,
    destination_account_id: uuid.UUID | None = None,
    amount: Decimal = Decimal("1000.00"),
    occurred_at: datetime | None = None,
) -> uuid.UUID:
    """Insert a transaction row with full control over columns."""
    tid = transaction_id or uuid.uuid4()
    ts = occurred_at or datetime.now(timezone.utc)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions "
                "(transaction_id, source_account_id, destination_account_id, "
                "amount, currency, occurred_at, created_at) "
                "VALUES (:tid, :src, :dst, :amt, 'INR', :occ, :now)"
            ),
            {
                "tid": tid,
                "src": source_account_id,
                "dst": destination_account_id,
                "amt": amount,
                "occ": ts,
                "now": datetime.now(timezone.utc),
            },
        )
    return tid


def _cleanup_seeded_data(superuser_engine: Engine, customer_id: uuid.UUID) -> None:
    """Remove seeded test data for a specific customer (FK-safe order)."""
    with superuser_engine.begin() as conn:
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
# TESTS
# ---------------------------------------------------------------------------


class TestAmountDeviation:
    """Integration tests against real PostgreSQL."""

    def test_happy_path(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Seed 3 qualifying historical txns (equal amounts) inside 90-day
        window, 1 older outside the window, and 1 alerted txn at larger amount.
        Assert average, deviation, count, and exact source_transaction_ids.
        """
        cid = _seed_customer(superuser_engine)
        try:
            acct_id = _seed_account(superuser_engine, cid)
            alerted_time = datetime.now(timezone.utc)

            # 3 qualifying: 30, 60, 80 days before alerted_time
            hist_ids: list[uuid.UUID] = []
            for days_back in [30, 60, 80]:
                tid = _seed_transaction(
                    superuser_engine,
                    source_account_id=acct_id,
                    amount=Decimal("3000.00"),
                    occurred_at=alerted_time - timedelta(days=days_back),
                )
                hist_ids.append(tid)

            # 1 outside window: 100 days back (proves exclusion)
            _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                amount=Decimal("3000.00"),
                occurred_at=alerted_time - timedelta(days=100),
            )

            # Alerted transaction at larger amount
            alerted_tid = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                amount=Decimal("15000.00"),
                occurred_at=alerted_time,
            )

            result = compute_amount_deviation(app_engine, alerted_tid)

            assert isinstance(result, AmountDeviationComputed)
            assert result.alerted_transaction_id == alerted_tid
            assert result.alerted_amount == Decimal("15000.00")
            assert result.historical_average == Decimal("3000.00")
            assert result.deviation_multiple == Decimal("5")
            assert result.historical_transaction_count == 3
            assert set(result.source_transaction_ids) == set(hist_ids)
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_worked_example_rahul_sharma(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Reproduce the worked-example arithmetic with locally seeded data.

        Six historical outgoing transactions at 30/60/90/120/150/180 days
        back (₹60,000 each). Only the 30/60/90-day transactions qualify
        in the 90-day trailing window — 3, not 6 —
        historical_average=60000, deviation_multiple≈16.33.
        """
        cid = _seed_customer(superuser_engine)
        try:
            acct_id = _seed_account(superuser_engine, cid)
            alerted_time = datetime.now(timezone.utc)

            # 6 historical outgoing transactions mirroring the worked example
            qualifying_ids: list[uuid.UUID] = []
            for days_back in [30, 60, 90, 120, 150, 180]:
                tid = _seed_transaction(
                    superuser_engine,
                    source_account_id=acct_id,
                    amount=Decimal("60000.00"),
                    occurred_at=alerted_time - timedelta(days=days_back),
                )
                # Only 30/60/90 fall within the 90-day window
                if days_back <= 90:
                    qualifying_ids.append(tid)

            # Alerted transaction: ₹980,000
            alerted_tid = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                amount=Decimal("980000.00"),
                occurred_at=alerted_time,
            )

            result = compute_amount_deviation(app_engine, alerted_tid)

            assert isinstance(result, AmountDeviationComputed)
            assert result.alerted_amount == Decimal("980000.00")
            assert result.historical_average == Decimal("60000.00")
            assert result.historical_transaction_count == 3
            # 980000 / 60000 = 16.333...
            expected_dev = Decimal("980000.00") / Decimal("60000.00")
            assert result.deviation_multiple == expected_dev
            assert set(result.source_transaction_ids) == set(qualifying_ids)
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_insufficient_history_returns_unknown(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Only the alerted transaction exists — no qualifying history."""
        cid = _seed_customer(superuser_engine)
        try:
            acct_id = _seed_account(superuser_engine, cid)
            alerted_tid = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                amount=Decimal("5000.00"),
                occurred_at=datetime.now(timezone.utc),
            )

            result = compute_amount_deviation(app_engine, alerted_tid)

            assert isinstance(result, AmountDeviationUnknown)
            assert result.alerted_transaction_id == alerted_tid
            assert "no qualifying" in result.reason
            # Verify no numeric average is accessible
            assert not hasattr(result, "historical_average")
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_boundary_excludes_older_than_90_days(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """A transaction at exactly alerted.occurred_at - 91 days excluded;
        one at exactly alerted.occurred_at - 90 days included.
        """
        cid = _seed_customer(superuser_engine)
        try:
            acct_id = _seed_account(superuser_engine, cid)
            alerted_time = datetime.now(timezone.utc)

            # Exactly 91 days back -> excluded
            _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                amount=Decimal("1000.00"),
                occurred_at=alerted_time - timedelta(days=91),
            )

            # Exactly 90 days back -> included
            included_tid = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                amount=Decimal("2000.00"),
                occurred_at=alerted_time - timedelta(days=90),
            )

            alerted_tid = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                amount=Decimal("5000.00"),
                occurred_at=alerted_time,
            )

            result = compute_amount_deviation(app_engine, alerted_tid)

            assert isinstance(result, AmountDeviationComputed)
            assert result.historical_transaction_count == 1
            assert result.source_transaction_ids == (included_tid,)
            assert result.historical_average == Decimal("2000.00")
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_boundary_excludes_transaction_at_alert_timestamp(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """A transaction with occurred_at == alerted.occurred_at excluded
        (strict < on the upper bound).
        """
        cid = _seed_customer(superuser_engine)
        try:
            acct_id = _seed_account(superuser_engine, cid)
            alerted_time = datetime.now(timezone.utc)

            # Same-timestamp transaction -> excluded
            _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                amount=Decimal("1000.00"),
                occurred_at=alerted_time,
            )

            alerted_tid = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                amount=Decimal("5000.00"),
                occurred_at=alerted_time,
            )

            result = compute_amount_deviation(app_engine, alerted_tid)

            assert isinstance(result, AmountDeviationUnknown)
            assert "no qualifying" in result.reason
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_incoming_transaction_excluded(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """A transaction where the customer's account is only
        destination_account_id does not count as outgoing.
        """
        cid = _seed_customer(superuser_engine)
        other_cid = _seed_customer(superuser_engine)
        try:
            cust_acct = _seed_account(superuser_engine, cid)
            other_acct = _seed_account(superuser_engine, other_cid)
            alerted_time = datetime.now(timezone.utc)

            # Incoming: other_acct -> cust_acct (should not count)
            _seed_transaction(
                superuser_engine,
                source_account_id=other_acct,
                destination_account_id=cust_acct,
                amount=Decimal("7000.00"),
                occurred_at=alerted_time - timedelta(days=10),
            )

            # Alerted: outgoing from cust_acct
            alerted_tid = _seed_transaction(
                superuser_engine,
                source_account_id=cust_acct,
                amount=Decimal("5000.00"),
                occurred_at=alerted_time,
            )

            result = compute_amount_deviation(app_engine, alerted_tid)

            # The incoming tx should not count, so no qualifying history
            assert isinstance(result, AmountDeviationUnknown)
            assert "no qualifying" in result.reason
        finally:
            _cleanup_seeded_data(superuser_engine, other_cid)
            _cleanup_seeded_data(superuser_engine, cid)

    def test_invalid_transaction_id_raises(self) -> None:
        """Malformed UUID string raises InvalidTransactionError before any
        DB query.
        """
        dummy_engine = create_engine("sqlite://")
        with pytest.raises(InvalidTransactionError, match="not a valid UUID"):
            compute_amount_deviation(
                dummy_engine,
                "not-a-uuid",  # type: ignore[arg-type]
            )

    def test_nonexistent_transaction_id_raises(
        self,
        app_engine: Engine,
    ) -> None:
        """Valid UUID format but no matching row -> TransactionNotFoundError."""
        fake_tid = uuid.uuid4()
        with pytest.raises(TransactionNotFoundError, match="does not exist"):
            compute_amount_deviation(app_engine, fake_tid)

    def test_null_source_account_raises(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """source_account_id IS NULL -> InvalidTransactionError."""
        cid = _seed_customer(superuser_engine)
        try:
            acct_id = _seed_account(superuser_engine, cid)
            # Transaction with NULL source (incoming-only)
            tid = _seed_transaction(
                superuser_engine,
                source_account_id=None,
                destination_account_id=acct_id,
                amount=Decimal("5000.00"),
                occurred_at=datetime.now(timezone.utc),
            )

            with pytest.raises(
                InvalidTransactionError, match="no source_account_id"
            ):
                compute_amount_deviation(app_engine, tid)
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_zero_historical_average_returns_unknown(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Qualifying historical transactions sum to zero ->
        AmountDeviationUnknown, not a division error or infinite value.
        """
        cid = _seed_customer(superuser_engine)
        try:
            acct_id = _seed_account(superuser_engine, cid)
            alerted_time = datetime.now(timezone.utc)

            # Two qualifying txns that average to zero
            _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                amount=Decimal("0.00"),
                occurred_at=alerted_time - timedelta(days=10),
            )
            _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                amount=Decimal("0.00"),
                occurred_at=alerted_time - timedelta(days=20),
            )

            alerted_tid = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                amount=Decimal("5000.00"),
                occurred_at=alerted_time,
            )

            result = compute_amount_deviation(app_engine, alerted_tid)

            assert isinstance(result, AmountDeviationUnknown)
            assert "zero" in result.reason
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_read_only_no_writes(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Snapshot row counts before/after compute_amount_deviation via
        app_engine; assert unchanged.
        """
        cid = _seed_customer(superuser_engine)
        try:
            acct_id = _seed_account(superuser_engine, cid)
            alerted_tid = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                amount=Decimal("5000.00"),
                occurred_at=datetime.now(timezone.utc),
            )

            # Snapshot counts before
            with superuser_engine.connect() as conn:
                tx_count_before = conn.execute(
                    text("SELECT count(*) FROM transactions")
                ).scalar()
                acct_count_before = conn.execute(
                    text("SELECT count(*) FROM accounts")
                ).scalar()
                cust_count_before = conn.execute(
                    text("SELECT count(*) FROM customers")
                ).scalar()

            # Run the function
            compute_amount_deviation(app_engine, alerted_tid)

            # Snapshot counts after
            with superuser_engine.connect() as conn:
                tx_count_after = conn.execute(
                    text("SELECT count(*) FROM transactions")
                ).scalar()
                acct_count_after = conn.execute(
                    text("SELECT count(*) FROM accounts")
                ).scalar()
                cust_count_after = conn.execute(
                    text("SELECT count(*) FROM customers")
                ).scalar()

            assert tx_count_before == tx_count_after
            assert acct_count_before == acct_count_after
            assert cust_count_before == cust_count_after
        finally:
            _cleanup_seeded_data(superuser_engine, cid)
