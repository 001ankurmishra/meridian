"""Tests for F2 investigation orchestrator."""
# ruff: noqa: E501

import uuid
from decimal import Decimal
from typing import Any, Generator
from unittest.mock import patch

import pytest
from sqlalchemy import Engine, text

from meridian.agents.policy.policy_agent import (
    PolicyCitation,
    PolicyEvidenceFound,
    PolicyEvidenceInsufficient,
)
from meridian.agents.transaction.amount_deviation import (
    AmountDeviationComputed,
    AmountDeviationUnknown,
)
from meridian.agents.transaction.errors import InvalidTransactionError
from meridian.orchestration.investigation_orchestrator import orchestrate_investigation


def _seed_case_and_alert(
    superuser_engine: Engine,
    status: str = "OPEN",
    transaction_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Seed a test case and alert."""
    case_id = uuid.uuid4()
    alert_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers (customer_id, full_name, is_synthetic, created_at) "
                "VALUES (:cid, 'Test Customer', true, now())"
            ),
            {"cid": customer_id},
        )
        if transaction_id is not None:
            conn.execute(
                text(
                    "INSERT INTO transactions "
                    "(transaction_id, amount, currency, occurred_at, created_at) "
                    "VALUES (:tid, 100, 'INR', now(), now())"
                ),
                {"tid": transaction_id},
            )
        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, transaction_id, alert_type, created_at) "
                "VALUES (:aid, :cid, :tid, 'TEST_ALERT', now())"
            ),
            {"aid": alert_id, "cid": customer_id, "tid": transaction_id},
        )
        conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status, opened_at, created_at) "
                "VALUES (:cid, :aid, :status, now(), now())"
            ),
            {"cid": case_id, "aid": alert_id, "status": status},
        )
    return case_id


def _assert_terminal_state(
    engine: Engine, case_id: uuid.UUID, expected_status: str
) -> None:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT status, completed_at FROM investigation_runs WHERE case_id = :cid"
            ),
            {"cid": case_id},
        ).fetchall()
        assert len(rows) == 1, "Exactly one investigation run should exist"
        assert rows[0][0] == expected_status
        assert rows[0][1] is not None, "Terminal timestamp (completed_at) must be set"


def _cleanup(superuser_engine: Engine) -> None:
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_runs"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM transactions"))
        conn.execute(text("DELETE FROM beneficiaries"))
        conn.execute(text("DELETE FROM accounts"))
        conn.execute(text("DELETE FROM customers"))


@pytest.fixture(autouse=True)
def clean_db(superuser_engine: Engine) -> Generator[None, None, None]:
    _cleanup(superuser_engine)
    yield
    _cleanup(superuser_engine)


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.investigation_orchestrator.run_graph_agent")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_all_evidence_found(
    mock_compute: Any,
    mock_run_graph: Any,
    mock_retrieve: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    tid = uuid.uuid4()
    case_id = _seed_case_and_alert(superuser_engine, transaction_id=tid)

    mock_compute.return_value = AmountDeviationComputed(
        alerted_transaction_id=tid,
        source_account_id=uuid.uuid4(),
        alerted_amount=Decimal("100"),
        historical_average=Decimal("10"),
        deviation_multiple=Decimal("10"),
        historical_transaction_count=1,
        source_transaction_ids=(uuid.uuid4(),),
    )
    mock_run_graph.return_value = None
    mock_retrieve.return_value = PolicyEvidenceFound(
        citations=[
            PolicyCitation(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                title="Test",
                document_type="Test",
                version="1.0",
                is_synthetic=True,
                chunk_index=0,
                chunk_text="text",
                rrf_score=1.0,
            )
        ]
    )

    status = orchestrate_investigation(app_role_engine, case_id)

    assert status == "COMPLETE"
    mock_compute.assert_called_once()
    mock_run_graph.assert_called_once()
    mock_retrieve.assert_called_once()

    # Exact policy query assertion
    args, kwargs = mock_retrieve.call_args
    query = (
        kwargs.get("query")
        if "query" in kwargs
        else (args[1] if len(args) > 1 else None)
    )
    assert query == "TEST_ALERT"

    _assert_terminal_state(superuser_engine, case_id, "COMPLETE")


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.investigation_orchestrator.run_graph_agent")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_policy_evidence_insufficient(
    mock_compute: Any,
    mock_run_graph: Any,
    mock_retrieve: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    tid = uuid.uuid4()
    case_id = _seed_case_and_alert(superuser_engine, transaction_id=tid)

    mock_compute.return_value = AmountDeviationComputed(
        alerted_transaction_id=tid,
        source_account_id=uuid.uuid4(),
        alerted_amount=Decimal("100"),
        historical_average=Decimal("10"),
        deviation_multiple=Decimal("10"),
        historical_transaction_count=1,
        source_transaction_ids=(uuid.uuid4(),),
    )
    mock_run_graph.return_value = None
    mock_retrieve.return_value = PolicyEvidenceInsufficient()

    status = orchestrate_investigation(app_role_engine, case_id)

    assert status == "INCOMPLETE_INSUFFICIENT_EVIDENCE"
    _assert_terminal_state(
        superuser_engine, case_id, "INCOMPLETE_INSUFFICIENT_EVIDENCE"
    )


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.investigation_orchestrator.run_graph_agent")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_amount_deviation_unknown(
    mock_compute: Any,
    mock_run_graph: Any,
    mock_retrieve: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    tid = uuid.uuid4()
    case_id = _seed_case_and_alert(superuser_engine, transaction_id=tid)

    mock_compute.return_value = AmountDeviationUnknown(
        alerted_transaction_id=tid,
        source_account_id=uuid.uuid4(),
        reason="Test",
    )
    mock_retrieve.return_value = PolicyEvidenceFound(citations=[])

    status = orchestrate_investigation(app_role_engine, case_id)

    assert status == "INCOMPLETE_INSUFFICIENT_EVIDENCE"
    mock_compute.assert_called_once()
    mock_run_graph.assert_called_once()
    mock_retrieve.assert_called_once()
    _assert_terminal_state(
        superuser_engine, case_id, "INCOMPLETE_INSUFFICIENT_EVIDENCE"
    )


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.investigation_orchestrator.run_graph_agent")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_no_transaction_id(
    mock_compute: Any,
    mock_run_graph: Any,
    mock_retrieve: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    case_id = _seed_case_and_alert(superuser_engine, transaction_id=None)
    mock_retrieve.return_value = PolicyEvidenceFound(citations=[])

    status = orchestrate_investigation(app_role_engine, case_id)

    assert status == "INCOMPLETE_INSUFFICIENT_EVIDENCE"
    mock_compute.assert_not_called()
    mock_run_graph.assert_not_called()
    mock_retrieve.assert_called_once()
    _assert_terminal_state(
        superuser_engine, case_id, "INCOMPLETE_INSUFFICIENT_EVIDENCE"
    )


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.investigation_orchestrator.run_graph_agent")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_transaction_agent_hard_failure(
    mock_compute: Any,
    mock_run_graph: Any,
    mock_retrieve: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    tid = uuid.uuid4()
    case_id = _seed_case_and_alert(superuser_engine, transaction_id=tid)

    mock_compute.side_effect = InvalidTransactionError("Boom")
    mock_retrieve.return_value = PolicyEvidenceFound(citations=[])

    with pytest.raises(InvalidTransactionError, match="Boom"):
        orchestrate_investigation(app_role_engine, case_id)

    mock_run_graph.assert_not_called()
    mock_retrieve.assert_called_once()

    _assert_terminal_state(superuser_engine, case_id, "FAILED")


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.investigation_orchestrator.run_graph_agent")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_graph_agent_hard_failure(
    mock_compute: Any,
    mock_run_graph: Any,
    mock_retrieve: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    tid = uuid.uuid4()
    case_id = _seed_case_and_alert(superuser_engine, transaction_id=tid)

    mock_compute.return_value = AmountDeviationComputed(
        alerted_transaction_id=tid,
        source_account_id=uuid.uuid4(),
        alerted_amount=Decimal("100"),
        historical_average=Decimal("10"),
        deviation_multiple=Decimal("10"),
        historical_transaction_count=1,
        source_transaction_ids=(uuid.uuid4(),),
    )
    mock_run_graph.side_effect = ValueError("Graph Boom")
    mock_retrieve.return_value = PolicyEvidenceFound(citations=[])

    status = orchestrate_investigation(app_role_engine, case_id)

    mock_retrieve.assert_called_once()
    assert status == "COMPLETE"
    _assert_terminal_state(superuser_engine, case_id, "COMPLETE")


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.investigation_orchestrator.run_graph_agent")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_policy_agent_hard_failure(
    mock_compute: Any,
    mock_run_graph: Any,
    mock_retrieve: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    tid = uuid.uuid4()
    case_id = _seed_case_and_alert(superuser_engine, transaction_id=tid)

    mock_compute.return_value = AmountDeviationComputed(
        alerted_transaction_id=tid,
        source_account_id=uuid.uuid4(),
        alerted_amount=Decimal("100"),
        historical_average=Decimal("10"),
        deviation_multiple=Decimal("10"),
        historical_transaction_count=1,
        source_transaction_ids=(uuid.uuid4(),),
    )
    mock_run_graph.return_value = None
    mock_retrieve.side_effect = RuntimeError("Policy Boom")

    with pytest.raises(RuntimeError, match="Policy Boom"):
        orchestrate_investigation(app_role_engine, case_id)

    _assert_terminal_state(superuser_engine, case_id, "FAILED")
