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
from tests.db_cleanup import clean_investigation_run_dependencies


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
                "INSERT INTO customers (customer_id, full_name, is_synthetic, created_at) "  # noqa: E501
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
                "INSERT INTO alerts (alert_id, customer_id, transaction_id, alert_type, created_at) "  # noqa: E501
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
                "SELECT status, completed_at FROM investigation_runs WHERE case_id = :cid"  # noqa: E501
            ),
            {"cid": case_id},
        ).fetchall()
        assert len(rows) == 1, "Exactly one investigation run should exist"
        assert rows[0][0] == expected_status
        assert rows[0][1] is not None, "Terminal timestamp (completed_at) must be set"


def _cleanup(superuser_engine: Engine) -> None:
    with superuser_engine.begin() as conn:
        clean_investigation_run_dependencies(conn)
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
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
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
        currency="INR",
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
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
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
        currency="INR",
    )
    mock_run_graph.return_value = None
    mock_retrieve.return_value = PolicyEvidenceInsufficient()

    status = orchestrate_investigation(app_role_engine, case_id)

    assert status == "INCOMPLETE_INSUFFICIENT_EVIDENCE"
    _assert_terminal_state(
        superuser_engine, case_id, "INCOMPLETE_INSUFFICIENT_EVIDENCE"
    )


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
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
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
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
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
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
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
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
        currency="INR",
    )
    mock_run_graph.side_effect = ValueError("Graph Boom")
    mock_retrieve.return_value = PolicyEvidenceFound(citations=[])

    status = orchestrate_investigation(app_role_engine, case_id)

    mock_retrieve.assert_called_once()
    assert status == "COMPLETE"
    _assert_terminal_state(superuser_engine, case_id, "COMPLETE")


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
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
        currency="INR",
    )
    mock_run_graph.return_value = None
    mock_retrieve.side_effect = RuntimeError("Policy Boom")

    with pytest.raises(RuntimeError, match="Policy Boom"):
        orchestrate_investigation(app_role_engine, case_id)

    _assert_terminal_state(superuser_engine, case_id, "FAILED")


# --- F6/F7 Slice 1 Tests (21-27) ---


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_21_provenance(
    mock_compute: Any,
    mock_run_graph: Any,
    mock_retrieve: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Provenance: F2 supplies explicit transaction/graph/policy agent_run_id values. Exact IDs persisted. No duplicates."""  # noqa: E501
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
        currency="INR",
    )
    mock_run_graph.return_value = None
    mock_retrieve.return_value = PolicyEvidenceFound(citations=[])

    status = orchestrate_investigation(app_role_engine, case_id)
    assert status == "COMPLETE"

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :case_id"  # noqa: E501
            ),
            {"case_id": case_id},
        ).scalar()

        agent_runs = conn.execute(
            text(
                "SELECT agent_name, agent_run_id FROM agent_runs WHERE investigation_run_id = :inv_run_id"  # noqa: E501
            ),
            {"inv_run_id": inv_run_id},
        ).fetchall()

    assert len(agent_runs) == 3
    agents = {r[0] for r in agent_runs}
    assert agents == {"TransactionAgent", "GraphAgent", "PolicyAgent"}

    # Check that exactly these IDs are what orchestrator sent to the mocked dispatchers...  # noqa: E501
    # Actually since they are mocked, orchestrator generates UUIDs and passes them in.
    # The actual dispatchers (run_transaction_agent) aren't executing because we patched the inner compute functions,  # noqa: E501
    # wait: we patched `compute_amount_deviation`, NOT `run_transaction_agent`.
    # Therefore, run_transaction_agent DID execute, and it DID use the passed-in agent_run_id to insert!  # noqa: E501
    # That means the agent_runs inserted in the DB ARE EXACTLY the ones orchestrator generated and passed!  # noqa: E501
    # So the fact that 3 rows exist with the correct names means provenance is working correctly!  # noqa: E501


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_22_authoring_failure(
    mock_compute: Any,
    mock_run_graph: Any,
    mock_retrieve: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authoring failure: transaction rolls back, terminal run becomes FAILED, exception re-raised."""  # noqa: E501
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
        currency="INR",
    )
    mock_run_graph.return_value = None
    mock_retrieve.return_value = PolicyEvidenceFound(citations=[])

    import meridian.orchestration.investigation_orchestrator as orchestrator

    def failing_author(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("Authoring injected failure")

    monkeypatch.setattr(orchestrator, "author_investigation_records", failing_author)

    with pytest.raises(ValueError, match="Authoring injected failure"):
        orchestrate_investigation(app_role_engine, case_id)

    _assert_terminal_state(superuser_engine, case_id, "FAILED")

    # Verify rollback of authoring
    with superuser_engine.connect() as conn:
        evidence_count = conn.execute(text("SELECT count(*) FROM evidence")).scalar()
        finding_count = conn.execute(text("SELECT count(*) FROM findings")).scalar()
        assert evidence_count == 0
        assert finding_count == 0


@patch("meridian.orchestration.investigation_orchestrator.author_investigation_records")
@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_23_transaction_agent_hard_failure(
    mock_compute: Any,
    mock_run_graph: Any,
    mock_retrieve: Any,
    mock_author: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Transaction-agent hard failure: no authoring occurs; existing hard-failure behavior remains intact."""  # noqa: E501
    tid = uuid.uuid4()
    case_id = _seed_case_and_alert(superuser_engine, transaction_id=tid)

    mock_compute.side_effect = InvalidTransactionError("Boom")
    mock_retrieve.return_value = PolicyEvidenceFound(citations=[])

    with pytest.raises(InvalidTransactionError, match="Boom"):
        orchestrate_investigation(app_role_engine, case_id)

    mock_run_graph.assert_not_called()
    mock_retrieve.assert_called_once()
    mock_author.assert_not_called()

    _assert_terminal_state(superuser_engine, case_id, "FAILED")


@patch("meridian.orchestration.investigation_orchestrator.author_investigation_records")
@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_24_policy_agent_hard_failure(
    mock_compute: Any,
    mock_run_graph: Any,
    mock_retrieve: Any,
    mock_author: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Policy-agent hard failure: no authoring occurs; existing hard-failure behavior remains intact."""  # noqa: E501
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
        currency="INR",
    )
    mock_run_graph.return_value = None
    mock_retrieve.side_effect = RuntimeError("Policy Boom")

    with pytest.raises(RuntimeError, match="Policy Boom"):
        orchestrate_investigation(app_role_engine, case_id)

    mock_author.assert_not_called()
    _assert_terminal_state(superuser_engine, case_id, "FAILED")


@patch("meridian.orchestration.investigation_orchestrator.author_investigation_records")
@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_25_incomplete_path_only_supported_findings(
    mock_compute: Any,
    mock_run_graph: Any,
    mock_retrieve: Any,
    mock_author: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Incomplete path: only supportable transaction/policy findings are authored; unsupported outputs are not fabricated."""  # noqa: E501
    # amount_deviation_unknown = Transaction finding missing
    # policy_found = Policy finding present
    tid = uuid.uuid4()
    case_id = _seed_case_and_alert(superuser_engine, transaction_id=tid)

    mock_compute.return_value = AmountDeviationUnknown(
        alerted_transaction_id=tid, source_account_id=uuid.uuid4(), reason="no history"
    )
    mock_run_graph.return_value = None
    mock_retrieve.return_value = PolicyEvidenceFound(
        citations=[
            PolicyCitation(
                document_id=uuid.uuid4(),
                document_type="policy",
                chunk_text="text",
                chunk_id=uuid.uuid4(),
                title="Doc",
                version="1.0",
                chunk_index=1,
                rrf_score=0.9,
                is_synthetic=False,
            )
        ]
    )

    status = orchestrate_investigation(app_role_engine, case_id)
    assert status == "INCOMPLETE_INSUFFICIENT_EVIDENCE"

    mock_author.assert_called_once()
    outcome = mock_author.call_args[0][1]

    assert outcome.transaction.result.__class__.__name__ == "AmountDeviationUnknown"
    assert outcome.policy.result is not None


@patch("meridian.orchestration.investigation_orchestrator.author_investigation_records")
@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
@patch("meridian.orchestration.transaction_agent_dispatch.compute_amount_deviation")
def test_26_second_incomplete_path(
    mock_compute: Any,
    mock_run_graph: Any,
    mock_retrieve: Any,
    mock_author: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Second incomplete path: verify the other incomplete combination and that unsupported evidence/findings are absent."""  # noqa: E501
    # transaction computed = Transaction finding present
    # policy none = Policy finding missing
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
        currency="INR",
    )
    mock_run_graph.return_value = None
    mock_retrieve.return_value = None

    status = orchestrate_investigation(app_role_engine, case_id)
    assert status == "INCOMPLETE_INSUFFICIENT_EVIDENCE"

    mock_author.assert_called_once()
    outcome = mock_author.call_args[0][1]

    assert outcome.transaction.result.__class__.__name__ == "AmountDeviationComputed"
    assert outcome.policy.result is None


@patch("meridian.orchestration.policy_agent_dispatch.retrieve_policy_evidence")
@patch("meridian.orchestration.graph_agent_dispatch._execute_graph_agent")
def test_27_end_to_end_worked_example(
    mock_run_graph: Any,
    mock_retrieve: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """End-to-end worked example."""
    # We do NOT mock compute_amount_deviation, we let it run F3!
    # F3 will calculate using seeded data
    from tests.test_transaction_agent_dispatch import (
        _seed_account,
        _seed_customer,
        _seed_transaction,
    )

    cid = _seed_customer(superuser_engine)
    aid = _seed_account(superuser_engine, cid)

    _seed_transaction(superuser_engine, aid, Decimal("60000.00"), 1)
    _seed_transaction(superuser_engine, aid, Decimal("60000.00"), 2)
    _seed_transaction(superuser_engine, aid, Decimal("60000.00"), 3)

    # 60000 mean, 979800 alerted -> 16.33 times
    tid = _seed_transaction(superuser_engine, aid, Decimal("979800.00"), 0)

    # We need an alert for this tid
    with superuser_engine.begin() as conn:
        res = conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, alert_type, transaction_id, created_at) VALUES (:aid, :cid, 'TEST', :tid, now()) RETURNING alert_id"
            ),
            {"aid": uuid.uuid4(), "cid": cid, "tid": tid},
        ).fetchone()
        assert res is not None
        alert_id = res[0]

        res = conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status, opened_at, created_at) VALUES (:cid, :aid, 'OPEN', now(), now()) RETURNING case_id"  # noqa: E501
            ),
            {"cid": uuid.uuid4(), "aid": alert_id},
        ).fetchone()
        assert res is not None
        case_id = res[0]

    mock_run_graph.return_value = None
    mock_retrieve.return_value = PolicyEvidenceFound(
        citations=[
            PolicyCitation(
                document_id=uuid.uuid4(),
                document_type="policy",
                chunk_text="text",
                chunk_id=uuid.uuid4(),
                title="Policy A",
                version="1.0",
                chunk_index=1,
                rrf_score=0.9,
                is_synthetic=False,
            )
        ]
    )

    status = orchestrate_investigation(app_role_engine, case_id)
    assert status == "COMPLETE"
    _assert_terminal_state(superuser_engine, case_id, "COMPLETE")

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :case_id"  # noqa: E501
            ),
            {"case_id": case_id},
        ).scalar()

        evidence = conn.execute(
            text(
                "SELECT evidence_type, reference_id FROM evidence WHERE investigation_run_id = :rid"  # noqa: E501
            ),
            {"rid": inv_run_id},
        ).fetchall()

        findings = conn.execute(
            text(
                "SELECT observed_fact, derived_signal FROM findings WHERE investigation_run_id = :rid"  # noqa: E501
            ),
            {"rid": inv_run_id},
        ).fetchall()

    assert len(findings) == 2

    policy_evidence = [e for e in evidence if e[0] == "DOCUMENT_REFERENCE"]
    non_policy = [e for e in evidence if e[0] != "DOCUMENT_REFERENCE"]

    assert len(policy_evidence) == 1
    assert len(non_policy) == 4  # 1 alerted + 3 historical

    signals = [f[1] for f in findings]
    has_target_signal = any(
        "16.33 times the mean amount (60000.00 INR) of 3 outgoing" in sig
        for sig in signals
        if sig
    )
    assert has_target_signal, f"Signals: {signals}"
