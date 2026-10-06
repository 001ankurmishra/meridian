"""Task 18 graph structure DB integration tests."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from meridian.orchestration.investigation_orchestrator import orchestrate_investigation
from tests.test_transaction_agent_dispatch import (
    _seed_account,
    _seed_customer,
    _seed_transaction,
)


# We also need a seed for alert. Let's just define it here.
def _seed_alert(superuser_engine: Engine, cid: uuid.UUID, tid: uuid.UUID) -> uuid.UUID:
    with superuser_engine.begin() as conn:
        aid = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, alert_type, transaction_id, created_at) "  # noqa: E501
                "VALUES (:aid, :cid, 'TEST', :tid, now())"
            ),
            {"aid": aid, "cid": cid, "tid": tid},
        )
        case_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status, opened_at, created_at) "
                "VALUES (:cid, :aid, 'OPEN', now(), now())"
            ),
            {"cid": case_id, "aid": aid},
        )
    return case_id


# Fixtures are assumed to be loaded via conftest or the existing testing setup.
# We will mock the dispatch to return specific graph results for integration testing
# or rely on the actual DB state if we create synthetic records.

# Since we want to test atomicity and DB integration, we'll plant a test case.


@pytest.fixture
def investigation_setup(superuser_engine: Engine):
    """Set up a test case in the database."""
    customer_id = _seed_customer(superuser_engine)
    account_id = _seed_account(superuser_engine, customer_id)
    tx_id = _seed_transaction(superuser_engine, account_id, Decimal("50.0"), 0)
    case_id = _seed_alert(superuser_engine, customer_id, tx_id)

    return case_id, customer_id, tx_id


def test_atomicity_rollback_on_error(
    app_role_engine: Engine, investigation_setup, monkeypatch
):
    """Test T8 - atomicity. Inject failure after graph authoring."""
    case_id, customer_id, tx_id = investigation_setup

    # We will mock the policy agent to raise an error so the transaction rolls back
    from meridian.orchestration import investigation_orchestrator

    def failing_policy_agent(*args, **kwargs):
        raise RuntimeError("Simulated failure")

    monkeypatch.setattr(
        investigation_orchestrator, "run_policy_agent", failing_policy_agent
    )

    with pytest.raises(RuntimeError, match="Simulated failure"):
        orchestrate_investigation(app_role_engine, case_id)

    # Verify no investigation artifacts survived
    with app_role_engine.connect() as conn:
        inv_runs = conn.execute(
            text(
                "SELECT investigation_run_id, status FROM investigation_runs WHERE case_id = :c"  # noqa: E501
            ),
            {"c": case_id},
        ).fetchall()

        assert len(inv_runs) == 1
        inv_id = inv_runs[0][0]
        assert inv_runs[0][1] == "FAILED"

        ev_count = conn.execute(
            text("SELECT count(*) FROM evidence WHERE investigation_run_id = :i"),
            {"i": inv_id},
        ).scalar()
        assert ev_count == 0

        find_count = conn.execute(
            text("SELECT count(*) FROM findings WHERE investigation_run_id = :i"),
            {"i": inv_id},
        ).scalar()
        assert find_count == 0

        rec_count = conn.execute(
            text(
                "SELECT count(*) FROM recommendations WHERE investigation_run_id = :i"
            ),
            {"i": inv_id},
        ).scalar()
        assert rec_count == 0

        risk_count = conn.execute(
            text("SELECT count(*) FROM risk_signals WHERE investigation_run_id = :i"),
            {"i": inv_id},
        ).scalar()
        assert risk_count == 0
