"""Test suite for transaction velocity analysis (F3 Slice 2).

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

from meridian.agents.transaction.errors import (
    InvalidTransactionError,
    TransactionNotFoundError,
)
from meridian.agents.transaction.transaction_velocity import (
    TransactionVelocityComputed,
    compute_transaction_velocity,
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
    currency: str | None = "INR",
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
                "VALUES (:tid, :src, :dst, :amt, :curr, :occ, :now)"
            ),
            {
                "tid": tid,
                "src": source_account_id,
                "dst": destination_account_id,
                "amt": amount,
                "curr": currency,
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


class TestTransactionVelocity:
    """Integration tests against real PostgreSQL."""

    def test_alerted_transaction_alone(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        cid = _seed_customer(superuser_engine)
        try:
            acct_id = _seed_account(superuser_engine, cid)
            alerted_time = datetime.now(timezone.utc)
            alerted_tid = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                occurred_at=alerted_time,
            )

            result = compute_transaction_velocity(app_engine, alerted_tid)
            assert isinstance(result, TransactionVelocityComputed)
            assert result.transaction_count == 1
            assert result.source_transaction_ids == (alerted_tid,)
            assert result.alerted_transaction_id == alerted_tid
            assert result.source_account_id == acct_id
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_several_transactions_inside_window(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        cid = _seed_customer(superuser_engine)
        try:
            acct_id = _seed_account(superuser_engine, cid)
            alerted_time = datetime.now(timezone.utc)

            t1 = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                occurred_at=alerted_time - timedelta(hours=10),
            )
            t2 = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                occurred_at=alerted_time - timedelta(hours=5),
            )
            alerted_tid = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                occurred_at=alerted_time,
            )

            result = compute_transaction_velocity(app_engine, alerted_tid)
            assert result.transaction_count == 3
            # Ordered by occurred_at ASC, transaction_id ASC
            # Ordered by occurred_at ASC, transaction_id ASC
            # Wait, order is occurred_at ASC then ID ASC.
            # We inserted them in strict ascending time order.
            assert result.source_transaction_ids == (t1, t2, alerted_tid)
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_window_boundaries(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        cid = _seed_customer(superuser_engine)
        try:
            acct_id = _seed_account(superuser_engine, cid)
            alerted_time = datetime.now(timezone.utc)

            # exactly 24h before included
            t_24h = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                occurred_at=alerted_time - timedelta(hours=24),
            )

            # 24h + 1s before excluded
            _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                occurred_at=alerted_time - timedelta(hours=24, seconds=1),
            )

            # later than alerted excluded
            _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                occurred_at=alerted_time + timedelta(hours=1),
            )

            # same-timestamp included
            t_same = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                occurred_at=alerted_time,
            )

            alerted_tid = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                occurred_at=alerted_time,
            )

            result = compute_transaction_velocity(app_engine, alerted_tid)
            assert result.transaction_count == 3

            # Order: t_24h (oldest), then t_same/alerted_tid ordered by ID
            expected_same_time = sorted([t_same, alerted_tid], key=lambda x: str(x))
            assert result.source_transaction_ids == (
                t_24h,
                expected_same_time[0],
                expected_same_time[1],
            )
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_exclusions_and_inclusions(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        cid = _seed_customer(superuser_engine)
        other_cid = _seed_customer(superuser_engine)
        try:
            acct1 = _seed_account(superuser_engine, cid)
            acct2 = _seed_account(superuser_engine, cid)
            other_acct = _seed_account(superuser_engine, other_cid)

            alerted_time = datetime.now(timezone.utc)

            # another customer's outgoing txn excluded
            _seed_transaction(
                superuser_engine,
                source_account_id=other_acct,
                occurred_at=alerted_time - timedelta(hours=5),
            )

            # incoming-only excluded
            _seed_transaction(
                superuser_engine,
                source_account_id=other_acct,
                destination_account_id=acct1,
                occurred_at=alerted_time - timedelta(hours=2),
            )

            # a second account of the same customer included
            t_second_acct = _seed_transaction(
                superuser_engine,
                source_account_id=acct2,
                occurred_at=alerted_time - timedelta(hours=3),
            )

            alerted_tid = _seed_transaction(
                superuser_engine,
                source_account_id=acct1,
                occurred_at=alerted_time,
            )

            result = compute_transaction_velocity(app_engine, alerted_tid)
            assert result.transaction_count == 2
            assert result.source_transaction_ids == (t_second_acct, alerted_tid)
        finally:
            _cleanup_seeded_data(superuser_engine, other_cid)
            _cleanup_seeded_data(superuser_engine, cid)

    def test_invalid_inputs(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        cid = _seed_customer(superuser_engine)
        try:
            acct_id = _seed_account(superuser_engine, cid)
            alerted_time = datetime.now(timezone.utc)

            # transaction_id absent
            with pytest.raises(TransactionNotFoundError):
                compute_transaction_velocity(app_engine, uuid.uuid4())

            # invalid UUID string
            with pytest.raises(InvalidTransactionError):
                compute_transaction_velocity(app_engine, "not-a-uuid")

            # NULL source_account_id
            t_null_src = _seed_transaction(
                superuser_engine,
                source_account_id=None,
                destination_account_id=acct_id,
                occurred_at=alerted_time,
            )
            with pytest.raises(InvalidTransactionError):
                compute_transaction_velocity(app_engine, t_null_src)

            # unresolvable source account
            from unittest.mock import MagicMock
            dummy_engine = MagicMock()
            mock_conn = MagicMock()
            dummy_engine.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.side_effect = [
                ("some-txn-id", uuid.uuid4(), datetime.now(timezone.utc)),
                None
            ]
            with pytest.raises(InvalidTransactionError, match="cannot be resolved"):
                compute_transaction_velocity(dummy_engine, uuid.uuid4())
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_readonly_counts_and_determinism(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        cid = _seed_customer(superuser_engine)
        try:
            acct_id = _seed_account(superuser_engine, cid)
            alerted_time = datetime.now(timezone.utc)
            alerted_tid = _seed_transaction(
                superuser_engine,
                source_account_id=acct_id,
                occurred_at=alerted_time,
            )

            def get_counts(engine: Engine) -> dict[str, int]:
                with engine.connect() as conn:
                    return {
                        "transactions": conn.scalar(
                            text("SELECT count(*) FROM transactions")
                        ),
                        "accounts": conn.scalar(text("SELECT count(*) FROM accounts")),
                        "risk_signals": conn.scalar(
                            text("SELECT count(*) FROM risk_signals")
                        ),
                        "alerts": conn.scalar(text("SELECT count(*) FROM alerts")),
                        "cases": conn.scalar(text("SELECT count(*) FROM cases")),
                        "investigation_runs": conn.scalar(
                            text("SELECT count(*) FROM investigation_runs")
                        ),
                    }

            counts_before = get_counts(superuser_engine)

            result1 = compute_transaction_velocity(app_engine, alerted_tid)
            result2 = compute_transaction_velocity(app_engine, alerted_tid)

            # determinism
            assert result1 == result2

            counts_after = get_counts(superuser_engine)

            # read-only
            assert counts_before == counts_after
        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_v02_corpus(self, superuser_engine: Engine, app_engine: Engine) -> None:
        """Run the evaluation against the actual v02 deterministic corpus."""
        from meridian.fixtures.generator import generate_fixtures_v02
        from meridian.loader.main import clear_data, insert_data

        # ensure DB is loaded with fixtures
        res = generate_fixtures_v02("baseline_seed")
        clear_data(superuser_engine)
        insert_data(superuser_engine, res)

        try:
            manifest = res["manifest"]

            for fix in manifest["fixtures"]:
                if fix["scenario_class"] in ("reference", "worked_example"):
                    continue
                if fix.get("taxonomy") == "runtime_edge_case":
                    continue

                target_tid = fix["alert_spec"]["transaction_id"]
                result = compute_transaction_velocity(app_engine, target_tid)

                assert result.transaction_count >= 1
                assert uuid.UUID(target_tid) in result.source_transaction_ids
                assert result.alerted_transaction_id == uuid.UUID(target_tid)
        finally:
            clear_data(superuser_engine)
