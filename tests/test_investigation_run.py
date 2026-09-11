"""Tests for investigation_run."""
# ruff: noqa: E501

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import Engine, text

from meridian.orchestration.investigation_run import (
    InvestigationRunResult,
    create_investigation_run,
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


def _seed_transaction(superuser_engine: Engine, source_account_id: uuid.UUID | None) -> uuid.UUID:
    tid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions (transaction_id, source_account_id, amount, currency, occurred_at, created_at) "
                "VALUES (:tid, :src, 100.0, 'INR', :now, :now)"
            ),
            {
                "tid": tid,
                "src": source_account_id,
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


def test_create_investigation_run_success(app_role_engine: Engine, superuser_engine: Engine) -> None:
    """Test successful creation of investigation run."""
    cid = _seed_customer(superuser_engine)
    try:
        aid = _seed_account(superuser_engine, cid)
        tid = _seed_transaction(superuser_engine, aid)
        _, case_id = _seed_alert_case(superuser_engine, cid, tid)

        result = create_investigation_run(app_role_engine, case_id)

        assert isinstance(result, InvestigationRunResult)
        assert result.case_id == case_id
        assert result.status == "IN_PROGRESS"
        assert result.started_at is not None
        assert isinstance(result.investigation_run_id, uuid.UUID)

        # Verify db record
        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT case_id, status, started_at, created_at, completed_at "
                    "FROM investigation_runs WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": result.investigation_run_id}
            ).fetchall()
            assert len(rows) == 1
            row = rows[0]
            assert row[0] == case_id
            assert row[1] == "IN_PROGRESS"
            assert row[2] == result.started_at
            assert row[3] == result.started_at
            assert row[4] is None

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_create_investigation_run_invalid_case(app_role_engine: Engine) -> None:
    """Test creation with invalid case_id fails FK constraint."""
    invalid_case_id = uuid.uuid4()
    with pytest.raises(Exception) as excinfo:
        create_investigation_run(app_role_engine, invalid_case_id)
    assert "foreign key constraint" in str(excinfo.value).lower()
