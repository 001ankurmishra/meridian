"""Test suite for transaction beneficiary age analysis (F3).

Defines all fixtures locally. No tests/conftest.py dependency.
pytest-xdist is NOT in pyproject.toml — no parallel test execution assumed.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Generator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Engine, create_engine, text

from meridian.agents.transaction.beneficiary_age import (
    REASON_ADDED_AFTER_TRANSACTION,
    REASON_ADDED_AT_MISSING,
    REASON_NO_BENEFICIARY_RECORD,
    REASON_NO_DESTINATION_ACCOUNT,
    BeneficiaryAgeComputed,
    BeneficiaryAgeUnknown,
    compute_beneficiary_age,
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
# Seed helpers (duplicated from sibling tests by design)
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


def _seed_beneficiary(
    superuser_engine: Engine,
    customer_id: uuid.UUID,
    account_id: uuid.UUID | None,
    added_at: datetime | None,
) -> uuid.UUID:
    """Insert a minimal beneficiary row and return its ID."""
    bid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO beneficiaries (beneficiary_id, customer_id, "
                "account_id, added_at, created_at) "
                "VALUES (:bid, :cid, :aid, :added_at, :now)"
            ),
            {
                "bid": bid,
                "cid": customer_id,
                "aid": account_id,
                "added_at": added_at,
                "now": datetime.now(timezone.utc),
            },
        )
    return bid


def _seed_transaction(
    superuser_engine: Engine,
    *,
    transaction_id: uuid.UUID | None = None,
    source_account_id: uuid.UUID | None = None,
    destination_account_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
) -> uuid.UUID:
    """Insert a minimal transaction row and return its ID."""
    tid = transaction_id or uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions (transaction_id, source_account_id, "
                "destination_account_id, amount, currency, occurred_at, "
                "source, created_at) "
                "VALUES (:tid, :src, :dst, :amt, :curr, :occ, 'synthetic', :now)"
            ),
            {
                "tid": tid,
                "src": source_account_id,
                "dst": destination_account_id,
                "amt": Decimal("100.00"),
                "curr": "USD",
                "occ": occurred_at or datetime.now(timezone.utc),
                "now": datetime.now(timezone.utc),
            },
        )
    return tid


def _cleanup_seeded_data(superuser_engine: Engine, customer_id: uuid.UUID) -> None:
    """Delete all accounts, beneficiaries, and transactions for a customer."""
    with superuser_engine.begin() as conn:
        accounts = conn.execute(
            text("SELECT account_id FROM accounts WHERE customer_id = :cid"),
            {"cid": customer_id},
        ).fetchall()
        for (aid,) in accounts:
            conn.execute(
                text(
                    "DELETE FROM transactions WHERE source_account_id = :aid "
                    "OR destination_account_id = :aid"
                ),
                {"aid": aid},
            )
        conn.execute(
            text("DELETE FROM beneficiaries WHERE customer_id = :cid"),
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
# Test Cases
# ---------------------------------------------------------------------------


class TestBeneficiaryAge:
    def test_basic_computation_and_zero_age(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Test cases 1 and 2: Basic age computation and exactly zero age."""
        cid = _seed_customer(superuser_engine)
        try:
            src_acct = _seed_account(superuser_engine, cid)
            dst_acct = _seed_account(superuser_engine, cid)

            # Case 1: age is 2 days
            occurred_1 = datetime.now(timezone.utc)
            added_1 = occurred_1 - timedelta(days=2)
            bid_1 = _seed_beneficiary(superuser_engine, cid, dst_acct, added_1)

            tid_1 = _seed_transaction(
                superuser_engine,
                source_account_id=src_acct,
                destination_account_id=dst_acct,
                occurred_at=occurred_1,
            )

            res_1 = compute_beneficiary_age(app_engine, tid_1)
            assert isinstance(res_1, BeneficiaryAgeComputed)
            assert res_1.alerted_transaction_id == tid_1
            assert res_1.source_account_id == src_acct
            assert res_1.destination_account_id == dst_acct
            assert res_1.beneficiary_added_at == added_1
            assert res_1.beneficiary_age == timedelta(days=2)
            assert res_1.beneficiary_ids == (bid_1,)

            # Cleanup for Case 2
            with superuser_engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM beneficiaries WHERE beneficiary_id = :bid"),
                    {"bid": bid_1},
                )

            # Case 2: zero age
            occurred_2 = datetime.now(timezone.utc)
            bid_2 = _seed_beneficiary(superuser_engine, cid, dst_acct, occurred_2)

            tid_2 = _seed_transaction(
                superuser_engine,
                source_account_id=src_acct,
                destination_account_id=dst_acct,
                occurred_at=occurred_2,
            )

            res_2 = compute_beneficiary_age(app_engine, tid_2)
            assert isinstance(res_2, BeneficiaryAgeComputed)
            assert res_2.beneficiary_added_at == occurred_2
            assert res_2.beneficiary_age == timedelta(0)
            assert res_2.beneficiary_ids == (bid_2,)

        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_multiple_beneficiaries(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Test case 3: Multiple beneficiaries, earliest non-null used, sorted IDs."""
        cid = _seed_customer(superuser_engine)
        try:
            src_acct = _seed_account(superuser_engine, cid)
            dst_acct = _seed_account(superuser_engine, cid)

            occurred = datetime.now(timezone.utc)

            # Multiple matching beneficiaries
            b_null = _seed_beneficiary(superuser_engine, cid, dst_acct, None)
            b_earliest = _seed_beneficiary(
                superuser_engine, cid, dst_acct, occurred - timedelta(days=5)
            )
            b_later = _seed_beneficiary(
                superuser_engine, cid, dst_acct, occurred - timedelta(days=1)
            )

            tid = _seed_transaction(
                superuser_engine,
                source_account_id=src_acct,
                destination_account_id=dst_acct,
                occurred_at=occurred,
            )

            res = compute_beneficiary_age(app_engine, tid)
            assert isinstance(res, BeneficiaryAgeComputed)
            assert res.beneficiary_added_at == occurred - timedelta(days=5)
            assert res.beneficiary_age == timedelta(days=5)

            # Check sorting
            expected_ids = tuple(
                sorted([b_null, b_earliest, b_later], key=lambda x: str(x))
            )
            assert res.beneficiary_ids == expected_ids

        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_all_null_added_at(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Test case 4: All matching beneficiaries have NULL added_at."""
        cid = _seed_customer(superuser_engine)
        try:
            src_acct = _seed_account(superuser_engine, cid)
            dst_acct = _seed_account(superuser_engine, cid)

            _seed_beneficiary(superuser_engine, cid, dst_acct, None)
            _seed_beneficiary(superuser_engine, cid, dst_acct, None)

            tid = _seed_transaction(
                superuser_engine,
                source_account_id=src_acct,
                destination_account_id=dst_acct,
            )

            res = compute_beneficiary_age(app_engine, tid)
            assert isinstance(res, BeneficiaryAgeUnknown)
            assert res.reason == REASON_ADDED_AT_MISSING

        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_added_after_transaction(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Test case 5: Earliest added_at is after the transaction."""
        cid = _seed_customer(superuser_engine)
        try:
            src_acct = _seed_account(superuser_engine, cid)
            dst_acct = _seed_account(superuser_engine, cid)

            occurred = datetime.now(timezone.utc)
            _seed_beneficiary(
                superuser_engine, cid, dst_acct, occurred + timedelta(days=1)
            )

            tid = _seed_transaction(
                superuser_engine,
                source_account_id=src_acct,
                destination_account_id=dst_acct,
                occurred_at=occurred,
            )

            res = compute_beneficiary_age(app_engine, tid)
            assert isinstance(res, BeneficiaryAgeUnknown)
            assert res.reason == REASON_ADDED_AFTER_TRANSACTION

        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_null_destination_account(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Test case 6: NULL destination account."""
        cid = _seed_customer(superuser_engine)
        try:
            src_acct = _seed_account(superuser_engine, cid)

            tid = _seed_transaction(
                superuser_engine,
                source_account_id=src_acct,
                destination_account_id=None,
            )

            res = compute_beneficiary_age(app_engine, tid)
            assert isinstance(res, BeneficiaryAgeUnknown)
            assert res.reason == REASON_NO_DESTINATION_ACCOUNT

        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_no_beneficiary_record(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Test case 7: No beneficiary record."""
        cid = _seed_customer(superuser_engine)
        try:
            src_acct = _seed_account(superuser_engine, cid)
            dst_acct = _seed_account(superuser_engine, cid)

            tid = _seed_transaction(
                superuser_engine,
                source_account_id=src_acct,
                destination_account_id=dst_acct,
            )

            res = compute_beneficiary_age(app_engine, tid)
            assert isinstance(res, BeneficiaryAgeUnknown)
            assert res.reason == REASON_NO_BENEFICIARY_RECORD

        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_different_customer(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Test case 8: Beneficiary with same account but different customer."""
        cid1 = _seed_customer(superuser_engine)
        cid2 = _seed_customer(superuser_engine)
        try:
            src_acct = _seed_account(superuser_engine, cid1)
            dst_acct = _seed_account(superuser_engine, cid2)

            # Seed beneficiary for customer 2, but the transaction is from customer 1
            _seed_beneficiary(
                superuser_engine, cid2, dst_acct, datetime.now(timezone.utc)
            )

            tid = _seed_transaction(
                superuser_engine,
                source_account_id=src_acct,
                destination_account_id=dst_acct,
            )

            res = compute_beneficiary_age(app_engine, tid)
            assert isinstance(res, BeneficiaryAgeUnknown)
            assert res.reason == REASON_NO_BENEFICIARY_RECORD

        finally:
            _cleanup_seeded_data(superuser_engine, cid1)
            _cleanup_seeded_data(superuser_engine, cid2)

    def test_different_account(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Test case 9: Beneficiary with same customer but different account."""
        cid = _seed_customer(superuser_engine)
        try:
            src_acct = _seed_account(superuser_engine, cid)
            dst_acct = _seed_account(superuser_engine, cid)
            other_dst = _seed_account(superuser_engine, cid)

            _seed_beneficiary(
                superuser_engine, cid, other_dst, datetime.now(timezone.utc)
            )

            tid = _seed_transaction(
                superuser_engine,
                source_account_id=src_acct,
                destination_account_id=dst_acct,
            )

            res = compute_beneficiary_age(app_engine, tid)
            assert isinstance(res, BeneficiaryAgeUnknown)
            assert res.reason == REASON_NO_BENEFICIARY_RECORD

        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_invalid_inputs(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Test cases 10-13: Missing, invalid UUID, null source, unresolvable source."""
        cid = _seed_customer(superuser_engine)
        try:
            # Case 11: invalid UUID string
            with pytest.raises(InvalidTransactionError):
                compute_beneficiary_age(app_engine, "not-a-uuid")

            # Case 10: missing transaction
            with pytest.raises(TransactionNotFoundError):
                compute_beneficiary_age(app_engine, uuid.uuid4())

            # Case 12: NULL source account
            dst_acct = _seed_account(superuser_engine, cid)
            t_null_src = _seed_transaction(
                superuser_engine,
                source_account_id=None,
                destination_account_id=dst_acct,
            )
            with pytest.raises(InvalidTransactionError):
                compute_beneficiary_age(app_engine, t_null_src)

            # Case 13: unresolvable source account
            dummy_engine = MagicMock()
            mock_conn = MagicMock()
            dummy_engine.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.side_effect = [
                ("some-txn-id", uuid.uuid4(), uuid.uuid4(), datetime.now(timezone.utc)),
                None,
            ]
            with pytest.raises(InvalidTransactionError, match="cannot be resolved"):
                compute_beneficiary_age(dummy_engine, uuid.uuid4())

        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_read_only_and_determinism(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Test cases 14 and 15: Read-only behavior and determinism."""
        cid = _seed_customer(superuser_engine)
        try:
            src_acct = _seed_account(superuser_engine, cid)
            dst_acct = _seed_account(superuser_engine, cid)

            occurred = datetime.now(timezone.utc)
            _seed_beneficiary(
                superuser_engine, cid, dst_acct, occurred - timedelta(days=2)
            )

            tid = _seed_transaction(
                superuser_engine,
                source_account_id=src_acct,
                destination_account_id=dst_acct,
                occurred_at=occurred,
            )

            def get_counts(engine: Engine) -> dict[str, int]:
                with engine.connect() as conn:
                    return {
                        "transactions": conn.scalar(
                            text("SELECT count(*) FROM transactions")
                        ),
                        "accounts": conn.scalar(text("SELECT count(*) FROM accounts")),
                        "beneficiaries": conn.scalar(
                            text("SELECT count(*) FROM beneficiaries")
                        ),
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

            result1 = compute_beneficiary_age(app_engine, tid)
            result2 = compute_beneficiary_age(app_engine, tid)

            # determinism
            assert result1 == result2

            counts_after = get_counts(superuser_engine)

            # read-only
            assert counts_before == counts_after

        finally:
            _cleanup_seeded_data(superuser_engine, cid)

    def test_v02_corpus(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Test case 16: v0.2 corpus structural test.
        Runs computation on every target transaction in the fixture corpus.
        """
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
                result = compute_beneficiary_age(app_engine, target_tid)

                # must return one of the two types without failing
                assert isinstance(
                    result, (BeneficiaryAgeComputed, BeneficiaryAgeUnknown)
                )

        finally:
            # ensure subsequent tests have a clean environment
            clear_data(superuser_engine)
