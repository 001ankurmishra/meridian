"""Task 18 graph structure DB integration tests."""

import uuid
from decimal import Decimal
from typing import Any, Generator

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
def investigation_setup(
    superuser_engine: Engine,
) -> Generator[tuple[uuid.UUID, uuid.UUID, uuid.UUID], None, None]:
    """Set up a test case in the database."""
    customer_id = _seed_customer(superuser_engine)
    account_id = _seed_account(superuser_engine, customer_id)
    tx_id = _seed_transaction(superuser_engine, account_id, Decimal("50.0"), 0)
    case_id = _seed_alert(superuser_engine, customer_id, tx_id)

    yield case_id, customer_id, tx_id

    with superuser_engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE risk_signals CASCADE"))
        conn.execute(text("TRUNCATE TABLE recommendations CASCADE"))
        conn.execute(text("TRUNCATE TABLE findings CASCADE"))
        conn.execute(text("TRUNCATE TABLE evidence CASCADE"))
        conn.execute(text("TRUNCATE TABLE agent_runs CASCADE"))
        conn.execute(text("TRUNCATE TABLE investigation_runs CASCADE"))
        conn.execute(text("TRUNCATE TABLE cases CASCADE"))
        conn.execute(text("TRUNCATE TABLE alerts CASCADE"))
        conn.execute(text("TRUNCATE TABLE transactions CASCADE"))
        conn.execute(text("TRUNCATE TABLE accounts CASCADE"))
        conn.execute(text("TRUNCATE TABLE customers CASCADE"))


def test_atomicity_rollback_on_error(
    app_role_engine: Engine,
    investigation_setup: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test T8 - atomicity. Inject failure after graph authoring."""
    case_id, customer_id, tx_id = investigation_setup

    from meridian.agents.graph.structure_signals import (
        ChainDepthComputed,
        CycleFound,
    )
    from meridian.agents.graph.subgraph import SubgraphResult
    from meridian.orchestration import investigation_orchestrator

    # Force GraphAgent to return a cycle and chain
    def mock_run_graph_agent(*args: Any, **kwargs: Any) -> Any:
        from datetime import datetime, timezone

        from meridian.orchestration.graph_agent_dispatch import GraphAgentDispatchResult

        agent_run_id = kwargs.get("agent_run_id")
        if agent_run_id is None and len(args) > 2:
            agent_run_id = args[2]

        if agent_run_id:
            with app_role_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO agent_runs "
                        "(agent_run_id, investigation_run_id, agent_name, "
                        "status, started_at, tool_calls, completed_at) "
                        "VALUES (:aid, :inv, 'GraphAgent', 'SUCCESS', "
                        ":now, '[]', :now)"
                    ),
                    {
                        "aid": agent_run_id,
                        "inv": kwargs.get(
                            "investigation_run_id",
                            args[1] if len(args) > 1 else uuid.uuid4(),
                        ),
                        "now": datetime.now(timezone.utc),
                    },
                )

        return GraphAgentDispatchResult(
            investigation_run_id=uuid.uuid4(),
            result=SubgraphResult(
                start_entity_id=customer_id,
                max_hops=3,
                node_entity_ids=(customer_id,),
                relationship_ids=(uuid.uuid4(), uuid.uuid4()),
                truncated=False,
            ),
            cycle_result=CycleFound(
                account_id=uuid.uuid4(),
                cycle_entity_ids=(uuid.uuid4(), uuid.uuid4()),
                cycle_relationship_ids=(uuid.uuid4(), uuid.uuid4()),
            ),
            chain_result=ChainDepthComputed(
                account_id=uuid.uuid4(),
                depth=2,
                chain_entity_ids=(uuid.uuid4(), uuid.uuid4(), uuid.uuid4()),
                chain_relationship_ids=(uuid.uuid4(), uuid.uuid4()),
            ),
        )

    monkeypatch.setattr(
        investigation_orchestrator,
        "run_graph_agent",
        mock_run_graph_agent,
    )

    original_record = investigation_orchestrator.record_risk_signal_with_connection  # type: ignore
    failure_reached = False

    def failing_record(*args: Any, **kwargs: Any) -> None:
        nonlocal failure_reached
        original_record(*args, **kwargs)

        # In this mock, risk_score_result is the 5th positional arg or 'result' kwarg
        result = kwargs.get("result")
        if result is None and len(args) > 4:
            result = args[4]

        from meridian.risk_engine.risk_signals import RiskScoreResult

        print(f"CALLED MOCK WITH result={result}")
        if isinstance(result, RiskScoreResult):
            # Only fail on the last one (graph_outbound_chain_depth)
            if result.signal_type == "graph_outbound_chain_depth":
                failure_reached = True
                raise RuntimeError("Simulated failure")

    monkeypatch.setattr(
        investigation_orchestrator, "record_risk_signal_with_connection", failing_record
    )

    with pytest.raises(RuntimeError, match="Simulated failure"):
        orchestrate_investigation(app_role_engine, case_id)

    assert failure_reached, "Failure injection point was not reached"

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
        # Depending on how the error is caught,
        # the orchestrator might log it and fail the run
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


def test_graph_agent_failure_does_not_fail_investigation(
    app_role_engine: Engine,
    investigation_setup: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_id, _, _ = investigation_setup

    from meridian.orchestration import investigation_orchestrator

    def failing_graph_agent(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Simulated GraphAgent failure")

    monkeypatch.setattr(
        investigation_orchestrator, "run_graph_agent", failing_graph_agent
    )

    # Let the orchestration run (should not raise RuntimeError)
    orchestrate_investigation(app_role_engine, case_id)

    with app_role_engine.connect() as conn:
        inv_runs = conn.execute(
            text(
                "SELECT investigation_run_id, status FROM investigation_runs "
                "WHERE case_id = :c"
            ),
            {"c": case_id},
        ).fetchall()

        assert len(inv_runs) == 1
        inv_id = inv_runs[0][0]
        # Should NOT be FAILED
        assert inv_runs[0][1] != "FAILED"

        # No graph findings or risk signals
        graph_findings = conn.execute(
            text(
                "SELECT count(*) FROM findings WHERE investigation_run_id = :i "
                "AND observed_fact LIKE 'Graph%'"
            ),
            {"i": inv_id},
        ).scalar()
        assert graph_findings == 0


def test_graph_agent_runs_exactly_once(
    app_role_engine: Engine, investigation_setup: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    case_id, _, _ = investigation_setup

    orchestrate_investigation(app_role_engine, case_id)

    with app_role_engine.connect() as conn:
        # Get inv_id
        inv_id = conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :c"
            ),
            {"c": case_id},
        ).scalar()

        graph_runs = conn.execute(
            text(
                "SELECT count(*) FROM agent_runs WHERE investigation_run_id = :i "
                "AND agent_name = 'GraphAgent'"
            ),
            {"i": inv_id},
        ).scalar()

        assert graph_runs == 1

def test_graph_artifacts_are_persisted(
    app_role_engine: Engine,
    investigation_setup: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test positive persistence of graph artifacts."""
    case_id, customer_id, tx_id = investigation_setup

    from meridian.agents.graph.structure_signals import (
        ChainDepthComputed,
        CycleFound,
    )
    from meridian.agents.graph.subgraph import SubgraphResult
    from meridian.orchestration import investigation_orchestrator

    # Prepare some real UUIDs for relationships to check against
    rel_id_1 = uuid.uuid4()
    rel_id_2 = uuid.uuid4()

    def mock_run_graph_agent(*args: Any, **kwargs: Any) -> Any:
        from datetime import datetime, timezone

        from meridian.orchestration.graph_agent_dispatch import GraphAgentDispatchResult

        inv_id: uuid.UUID | None = kwargs.get("investigation_run_id")
        if not inv_id and len(args) > 1:
            inv_id = args[1]
        assert inv_id is not None
        agent_run_id = kwargs.get("agent_run_id") or uuid.uuid4()
        with app_role_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_runs "
                    "(agent_run_id, investigation_run_id, agent_name, "
                    "status, started_at, tool_calls, completed_at) "
                    "VALUES (:aid, :inv, 'GraphAgent', 'SUCCESS', "
                    ":now, '[]', :now)"
                ),
                {
                    "aid": agent_run_id,
                    "inv": inv_id,
                    "now": datetime.now(timezone.utc),
                },
            )

        return GraphAgentDispatchResult(
            investigation_run_id=inv_id,
            result=SubgraphResult(
                start_entity_id=customer_id,
                max_hops=3,
                node_entity_ids=(customer_id,),
                relationship_ids=(rel_id_1, rel_id_2),
                truncated=False,
            ),
            cycle_result=CycleFound(
                account_id=customer_id,
                cycle_entity_ids=(customer_id,),
                cycle_relationship_ids=(rel_id_1, rel_id_2),
            ),
            chain_result=ChainDepthComputed(
                account_id=customer_id,
                depth=2,
                chain_entity_ids=(customer_id,),
                chain_relationship_ids=(rel_id_1, rel_id_2),
            ),
        )

    monkeypatch.setattr(
        investigation_orchestrator,
        "run_graph_agent",
        mock_run_graph_agent,
    )

    from meridian.agents.transaction.amount_deviation import AmountDeviationComputed
    from meridian.orchestration.transaction_agent_dispatch import (
        TransactionAgentDispatchResult,
    )

    def mock_run_transaction_agent(
        *args: Any, **kwargs: Any
    ) -> TransactionAgentDispatchResult:
        inv_id: uuid.UUID | None = kwargs.get("investigation_run_id")
        if not inv_id and len(args) > 1:
            inv_id = args[1]
        assert inv_id is not None
        agent_run_id = kwargs.get("agent_run_id") or uuid.uuid4()
        with app_role_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_runs "
                    "(agent_run_id, investigation_run_id, agent_name, "
                    "status, started_at, tool_calls, completed_at) "
                    "VALUES (:aid, :inv, 'TransactionAgent', 'SUCCESS', "
                    "now(), '[]', now())"
                ),
                {
                    "aid": agent_run_id,
                    "inv": inv_id,
                },
            )
        return TransactionAgentDispatchResult(
            investigation_run_id=inv_id,
            result=AmountDeviationComputed(
                alerted_transaction_id=tx_id,
                source_account_id=customer_id,
                alerted_amount=Decimal("100"),
                historical_average=Decimal("10"),
                deviation_multiple=Decimal("10"),
                historical_transaction_count=5,
                source_transaction_ids=(),
                currency="INR",
            ),
            velocity_result=None,
            beneficiary_age_result=None,
        )
    monkeypatch.setattr(
        investigation_orchestrator, "run_transaction_agent", mock_run_transaction_agent
    )

    from meridian.agents.policy.policy_agent import PolicyEvidenceFound

    def mock_run_policy_agent(*args: Any, **kwargs: Any) -> PolicyEvidenceFound:
        inv_id: uuid.UUID | None = kwargs.get("investigation_run_id")
        if not inv_id and len(args) > 1:
            inv_id = args[1]
        assert inv_id is not None
        agent_run_id = kwargs.get("agent_run_id") or uuid.uuid4()
        with app_role_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_runs "
                    "(agent_run_id, investigation_run_id, agent_name, "
                    "status, started_at, tool_calls, completed_at) "
                    "VALUES (:aid, :inv, 'PolicyAgent', 'SUCCESS', "
                    "now(), '[]', now())"
                ),
                {
                    "aid": agent_run_id,
                    "inv": inv_id,
                },
            )
        return PolicyEvidenceFound(citations=[])
    monkeypatch.setattr(
        investigation_orchestrator, "run_policy_agent", mock_run_policy_agent
    )

    orchestrate_investigation(app_role_engine, case_id)

    with app_role_engine.connect() as conn:
        inv_runs = conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :c"
            ),
            {"c": case_id},
        ).fetchall()
        inv_id = inv_runs[0][0]

        # Verify evidence
        ev = conn.execute(
            text(
                "SELECT evidence_type, reference_id FROM evidence "
                "WHERE investigation_run_id = :i"
            ),
            {"i": inv_id},
        ).fetchall()

        cycle_ev = [e for e in ev if e[0] == "graph_cycle_relationship"]
        chain_ev = [e for e in ev if e[0] == "graph_chain_relationship"]

        assert len(cycle_ev) == 2
        assert len(chain_ev) == 2
        assert {e[1] for e in cycle_ev} == {rel_id_1, rel_id_2}

        # Verify findings
        findings = conn.execute(
            text("SELECT observed_fact FROM findings WHERE investigation_run_id = :i"),
            {"i": inv_id},
        ).fetchall()

        cycle_findings = [f for f in findings if "Graph cycle:" in f[0]]
        chain_findings = [f for f in findings if "Graph chain:" in f[0]]
        assert len(cycle_findings) == 1
        assert len(chain_findings) == 1

        # Verify risk signals
        risk_signals = conn.execute(
            text(
                "SELECT signal_type, value FROM risk_signals "
                "WHERE investigation_run_id = :i"
            ),
            {"i": inv_id},
        ).fetchall()

        cycle_signals = [rs for rs in risk_signals if rs[0] == "graph_cycle_length"]
        chain_signals = [
            rs for rs in risk_signals if rs[0] == "graph_outbound_chain_depth"
        ]
        assert len(cycle_signals) == 1
        assert len(chain_signals) == 1
        assert cycle_signals[0][1] == Decimal("2")
        assert chain_signals[0][1] == Decimal("2")

        # Verify recommendations
        recommendations = conn.execute(
            text(
                "SELECT text FROM recommendations "
                "WHERE investigation_run_id = :i"
            ),
            {"i": inv_id},
        ).fetchall()

        cycle_recs = [r for r in recommendations if "cycle" in r[0].lower()]
        chain_recs = [r for r in recommendations if "chain" in r[0].lower()]
        assert len(cycle_recs) == 1
        assert len(chain_recs) == 1
