"""Task 18 graph structure DB integration tests."""

import uuid
from decimal import Decimal
import pytest

from sqlalchemy import Engine, text

from meridian.agents.report.outcome import (
    GraphOutcome,
    InvestigationOutcome,
    PolicyOutcome,
    TransactionOutcome,
)
from meridian.agents.policy.policy_agent import PolicyAgentResult, PolicyEvidenceInsufficient
from meridian.agents.transaction.amount_deviation import AmountDeviationUnknown
from meridian.orchestration.investigation_orchestrator import orchestrate_investigation
from meridian.db.session import engine


# Fixtures are assumed to be loaded via conftest or the existing testing setup.
# We will mock the dispatch to return specific graph results for integration testing
# or rely on the actual DB state if we create synthetic records.

# Since we want to test atomicity and DB integration, we'll plant a test case.

@pytest.fixture
def investigation_setup(app_role_engine: Engine):
    """Set up a test case in the database."""
    case_id = uuid.uuid4()
    alert_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    tx_id = uuid.uuid4()
    
    with app_role_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers (customer_id, risk_rating, status) "
                "VALUES (:c, 'LOW', 'ACTIVE')"
            ),
            {"c": customer_id}
        )
        conn.execute(
            text(
                "INSERT INTO accounts (account_id, customer_id, currency, status, balance) "
                "VALUES (:a, :c, 'USD', 'ACTIVE', 100)"
            ),
            {"a": uuid.uuid4(), "c": customer_id}
        )
        conn.execute(
            text(
                "INSERT INTO transactions (transaction_id, source_account_id, target_account_id, amount, currency) "
                "VALUES (:t, :a, :b, 50, 'USD')"
            ),
            {"t": tx_id, "a": uuid.uuid4(), "b": uuid.uuid4()}
        )
        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, transaction_id, alert_type, status) "
                "VALUES (:a, :c, :t, 'test', 'NEW')"
            ),
            {"a": alert_id, "c": customer_id, "t": tx_id}
        )
        conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status) "
                "VALUES (:c, :a, 'OPEN')"
            ),
            {"c": case_id, "a": alert_id}
        )
        
    return case_id, customer_id, tx_id


def test_atomicity_rollback_on_error(app_role_engine: Engine, investigation_setup, monkeypatch):
    """Test T8 - atomicity. Inject failure after graph authoring."""
    case_id, customer_id, tx_id = investigation_setup
    
    original_execute = app_role_engine.execute if hasattr(app_role_engine, 'execute') else None
    
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
            text("SELECT investigation_run_id, status FROM investigation_runs WHERE case_id = :c"),
            {"c": case_id}
        ).fetchall()
        
        assert len(inv_runs) == 1
        inv_id = inv_runs[0][0]
        assert inv_runs[0][1] == "FAILED"
        
        ev_count = conn.execute(
            text("SELECT count(*) FROM evidence WHERE investigation_run_id = :i"),
            {"i": inv_id}
        ).scalar()
        assert ev_count == 0
        
        find_count = conn.execute(
            text("SELECT count(*) FROM findings WHERE investigation_run_id = :i"),
            {"i": inv_id}
        ).scalar()
        assert find_count == 0
        
        rec_count = conn.execute(
            text("SELECT count(*) FROM recommendations WHERE investigation_run_id = :i"),
            {"i": inv_id}
        ).scalar()
        assert rec_count == 0
        
        risk_count = conn.execute(
            text("SELECT count(*) FROM risk_signals WHERE investigation_run_id = :i"),
            {"i": inv_id}
        ).scalar()
        assert risk_count == 0

