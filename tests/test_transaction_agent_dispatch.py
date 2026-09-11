"""Tests for transaction_agent_dispatch."""
# ruff: noqa: E501

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from meridian.agents.transaction.amount_deviation import (
    AmountDeviationComputed,
    AmountDeviationUnknown,
)
from meridian.agents.transaction.errors import InvalidTransactionError
from meridian.orchestration.transaction_agent_dispatch import (
    TransactionAgentDispatchResult,
    run_transaction_agent,
)


def _seed_customer(superuser_engine: Engine) -> uuid.UUID:
    cid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers (customer_id, full_name, is_synthetic, created_at) "
                "VALUES (:cid, 'Test Customer', true, :now)"
            ),
            {"cid": cid, "now": datetime.now(timezone.utc)},
        )
    return cid


def _seed_account(superuser_engine: Engine, customer_id: uuid.UUID) -> uuid.UUID:
    aid = uuid.uuid4()
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
    amount: Decimal = Decimal("100.0"),
    days_ago: int = 0,
) -> uuid.UUID:
    tid = uuid.uuid4()
    import datetime as dt
    occurred_at = datetime.now(timezone.utc)
    if days_ago > 0:
        occurred_at -= dt.timedelta(days=days_ago)

    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions (transaction_id, source_account_id, amount, currency, occurred_at, created_at) "
                "VALUES (:tid, :src, :amount, 'INR', :occ, :now)"
            ),
            {
                "tid": tid,
                "src": source_account_id,
                "amount": amount,
                "occ": occurred_at,
                "now": datetime.now(timezone.utc),
            },
        )
    return tid


def _seed_alert_case(
    superuser_engine: Engine, customer_id: uuid.UUID, transaction_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    alert_id = uuid.uuid4()
    case_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, transaction_id, created_at) "
                "VALUES (:aid, :cid, :tid, :now)"
            ),
            {"aid": alert_id, "cid": customer_id, "tid": transaction_id, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status, opened_at, created_at) "
                "VALUES (:case_id, :aid, 'OPEN', :now, :now)"
            ),
            {"case_id": case_id, "aid": alert_id, "now": now},
        )
    return alert_id, case_id


def _cleanup_seeded_data(superuser_engine: Engine, customer_id: uuid.UUID) -> None:
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_runs"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(
            text(
                "DELETE FROM transactions WHERE source_account_id IN "
                "(SELECT account_id FROM accounts WHERE customer_id = :cid)"
            ),
            {"cid": customer_id},
        )
        conn.execute(text("DELETE FROM accounts WHERE customer_id = :cid"), {"cid": customer_id})
        conn.execute(text("DELETE FROM customers WHERE customer_id = :cid"), {"cid": customer_id})


def test_happy_path(app_role_engine: Engine, superuser_engine: Engine) -> None:
    """Use a real valid case_id and valid transaction_id with sufficient history."""
    cid = _seed_customer(superuser_engine)
    try:
        aid = _seed_account(superuser_engine, cid)
        # Seed history
        _seed_transaction(superuser_engine, aid, Decimal("50.0"), 10)
        _seed_transaction(superuser_engine, aid, Decimal("50.0"), 20)
        # Alerted transaction
        tid = _seed_transaction(superuser_engine, aid, Decimal("1000.0"), 0)
        _, case_id = _seed_alert_case(superuser_engine, cid, tid)

        dispatch_result = run_transaction_agent(app_role_engine, case_id, tid)

        assert isinstance(dispatch_result, TransactionAgentDispatchResult)
        assert isinstance(dispatch_result.result, AmountDeviationComputed)
        assert dispatch_result.result.alerted_transaction_id == tid
        assert dispatch_result.result.deviation_multiple == Decimal("20.0")

        # Verify investigation_runs row
        with superuser_engine.connect() as conn:
            inv_rows = conn.execute(
                text("SELECT status FROM investigation_runs WHERE investigation_run_id = :inv_id"),
                {"inv_id": dispatch_result.investigation_run_id},
            ).fetchall()
            assert len(inv_rows) == 1
            assert inv_rows[0][0] == "IN_PROGRESS"

            # Verify agent_runs row
            ar_rows = conn.execute(
                text("SELECT agent_name, status FROM agent_runs WHERE investigation_run_id = :inv_id"),
                {"inv_id": dispatch_result.investigation_run_id},
            ).fetchall()
            assert len(ar_rows) == 1
            assert ar_rows[0][0] == "TransactionAgent"
            assert ar_rows[0][1] == "SUCCESS"

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_domain_unknown(app_role_engine: Engine, superuser_engine: Engine) -> None:
    """Use a valid transaction that produces F3's unknown result."""
    cid = _seed_customer(superuser_engine)
    try:
        aid = _seed_account(superuser_engine, cid)
        # Alerted transaction but NO history
        tid = _seed_transaction(superuser_engine, aid, Decimal("1000.0"), 0)
        _, case_id = _seed_alert_case(superuser_engine, cid, tid)

        dispatch_result = run_transaction_agent(app_role_engine, case_id, tid)

        assert isinstance(dispatch_result, TransactionAgentDispatchResult)
        assert isinstance(dispatch_result.result, AmountDeviationUnknown)
        assert dispatch_result.result.alerted_transaction_id == tid
        assert "no qualifying historical" in dispatch_result.result.reason

        # Verify investigation_runs row is still IN_PROGRESS
        with superuser_engine.connect() as conn:
            inv_rows = conn.execute(
                text("SELECT status FROM investigation_runs WHERE investigation_run_id = :inv_id"),
                {"inv_id": dispatch_result.investigation_run_id},
            ).fetchall()
            assert len(inv_rows) == 1
            assert inv_rows[0][0] == "IN_PROGRESS"

            # Verify agent_runs row is SUCCESS
            ar_rows = conn.execute(
                text("SELECT agent_name, status FROM agent_runs WHERE investigation_run_id = :inv_id"),
                {"inv_id": dispatch_result.investigation_run_id},
            ).fetchall()
            assert len(ar_rows) == 1
            assert ar_rows[0][0] == "TransactionAgent"
            assert ar_rows[0][1] == "SUCCESS"

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_execution_failure(app_role_engine: Engine, superuser_engine: Engine) -> None:
    """Use an invalid transaction_id that causes the actual F3 exception."""
    cid = _seed_customer(superuser_engine)
    tid = None
    try:
        # Transaction with NULL source account
        tid = _seed_transaction(superuser_engine, None, Decimal("1000.0"), 0)
        _, case_id = _seed_alert_case(superuser_engine, cid, tid)

        with pytest.raises(InvalidTransactionError, match="no source_account_id"):
            run_transaction_agent(app_role_engine, case_id, tid)

        # We need to find the investigation_run_id to verify db state.
        # It's the only run for this case.
        with superuser_engine.connect() as conn:
            inv_rows = conn.execute(
                text("SELECT investigation_run_id, status FROM investigation_runs WHERE case_id = :cid"),
                {"cid": case_id},
            ).fetchall()
            assert len(inv_rows) == 1
            inv_id = inv_rows[0][0]
            assert inv_rows[0][1] == "IN_PROGRESS"

            # Verify agent_runs row is FAILED
            ar_rows = conn.execute(
                text("SELECT agent_name, status, error FROM agent_runs WHERE investigation_run_id = :inv_id"),
                {"inv_id": inv_id},
            ).fetchall()
            assert len(ar_rows) == 1
            assert ar_rows[0][0] == "TransactionAgent"
            assert ar_rows[0][1] == "FAILED"
            assert ar_rows[0][2] is not None
            assert "no source_account_id" in ar_rows[0][2]

    finally:
        _cleanup_seeded_data(superuser_engine, cid)
        if tid is not None:
            with superuser_engine.begin() as conn:
                conn.execute(text("DELETE FROM transactions WHERE transaction_id = :tid"), {"tid": tid})


def test_invalid_case(app_role_engine: Engine) -> None:
    """Use an invalid/nonexistent case_id."""
    invalid_case_id = uuid.uuid4()
    invalid_tid = uuid.uuid4()

    with pytest.raises(IntegrityError) as excinfo:
        run_transaction_agent(app_role_engine, invalid_case_id, invalid_tid)

    assert "foreign key constraint" in str(excinfo.value).lower()
