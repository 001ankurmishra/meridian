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
from meridian.orchestration.errors import InvestigationError
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


def _cleanup(superuser_engine: Engine) -> None:
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_runs"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM customers"))


@pytest.fixture(autouse=True)
def clean_db(superuser_engine: Engine) -> Generator[None, None, None]:
    _cleanup(superuser_engine)
    yield
    _cleanup(superuser_engine)


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch.build_graph")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_all_evidence_found(
    mock_compute: Any,
    mock_build: Any,
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
    mock_build.return_value = {"nodes": [], "edges": []}
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
    mock_build.assert_called_once()
    mock_retrieve.assert_called_once()


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch.build_graph")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_policy_evidence_insufficient(
    mock_compute: Any,
    mock_build: Any,
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
    mock_build.return_value = {"nodes": [], "edges": []}
    mock_retrieve.return_value = PolicyEvidenceInsufficient()

    status = orchestrate_investigation(app_role_engine, case_id)

    assert status == "INCOMPLETE_INSUFFICIENT_EVIDENCE"


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch.build_graph")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_amount_deviation_unknown(
    mock_compute: Any,
    mock_build: Any,
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
    mock_build.assert_called_once()
    mock_retrieve.assert_called_once()


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch.build_graph")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_no_transaction_id(
    mock_compute: Any,
    mock_build: Any,
    mock_retrieve: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    case_id = _seed_case_and_alert(superuser_engine, transaction_id=None)
    mock_retrieve.return_value = PolicyEvidenceFound(citations=[])

    status = orchestrate_investigation(app_role_engine, case_id)

    assert status == "INCOMPLETE_INSUFFICIENT_EVIDENCE"
    mock_compute.assert_not_called()
    mock_build.assert_not_called()
    mock_retrieve.assert_called_once()


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch.build_graph")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_transaction_agent_hard_failure(
    mock_compute: Any,
    mock_build: Any,
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

    mock_build.assert_not_called()
    mock_retrieve.assert_called_once()

    with superuser_engine.begin() as conn:
        inv_status = conn.execute(
            text("SELECT status FROM investigation_runs WHERE case_id = :cid"),
            {"cid": case_id},
        ).scalar()
        assert inv_status == "FAILED"


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch.build_graph")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_graph_agent_hard_failure(
    mock_compute: Any,
    mock_build: Any,
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
    mock_build.side_effect = ValueError("Graph Boom")
    mock_retrieve.return_value = PolicyEvidenceFound(citations=[])

    status = orchestrate_investigation(app_role_engine, case_id)

    mock_retrieve.assert_called_once()
    assert status == "COMPLETE"


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch.build_graph")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_policy_agent_hard_failure(
    mock_compute: Any,
    mock_build: Any,
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
    mock_build.return_value = {"nodes": [], "edges": []}
    mock_retrieve.side_effect = RuntimeError("Policy Boom")

    with pytest.raises(RuntimeError, match="Policy Boom"):
        orchestrate_investigation(app_role_engine, case_id)

    with superuser_engine.begin() as conn:
        inv_status = conn.execute(
            text("SELECT status FROM investigation_runs WHERE case_id = :cid"),
            {"cid": case_id},
        ).scalar()
        assert inv_status == "FAILED"


def test_case_invalid_state(app_role_engine: Engine, superuser_engine: Engine) -> None:
    # Closed case
    case_id = _seed_case_and_alert(superuser_engine, status="CLOSED")
    with pytest.raises(InvestigationError, match="is not OPEN"):
        orchestrate_investigation(app_role_engine, case_id)
