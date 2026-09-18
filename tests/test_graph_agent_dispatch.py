"""Tests for graph_agent_dispatch."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import Engine, text

from meridian.agents.graph.errors import EntityNotFoundError, InvalidGraphInputError
from meridian.agents.graph.subgraph import SubgraphResult
from meridian.orchestration.graph_agent_dispatch import (
    GraphAgentDispatchResult,
    run_graph_agent,
)
from meridian.orchestration.investigation_run import create_investigation_run

# --- Data Seed Helpers ---

_NOW = datetime.now(timezone.utc)


def _seed_customer(engine: Engine) -> uuid.UUID:
    cid = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers (customer_id, full_name, is_synthetic, "
                "created_at) VALUES (:cid, :name, true, :now)"
            ),
            {"cid": cid, "name": f"Test Customer {cid}", "now": _NOW},
        )
    return cid


def _seed_account(engine: Engine, customer_id: uuid.UUID) -> uuid.UUID:
    aid = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (account_id, customer_id, status, created_at) "
                "VALUES (:aid, :cid, 'active', :now)"
            ),
            {"aid": aid, "cid": customer_id, "now": _NOW},
        )
    return aid


def _seed_entity(
    engine: Engine,
    *,
    entity_type: str = "account",
    reference_id: uuid.UUID | None = None,
) -> uuid.UUID:
    eid = uuid.uuid4()
    rid = reference_id or uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO entities (entity_id, entity_type, reference_id, "
                "created_at) VALUES (:eid, :etype, :rid, :now)"
            ),
            {"eid": eid, "etype": entity_type, "rid": rid, "now": _NOW},
        )
    return eid


def _seed_relationship(
    engine: Engine,
    source_entity_id: uuid.UUID,
    target_entity_id: uuid.UUID,
) -> uuid.UUID:
    rid = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO graph_relationships "
                "(relationship_id, source_entity_id, target_entity_id, "
                "relationship_type, weight, first_observed_at, "
                "last_observed_at, created_at) "
                "VALUES (:rid, :src, :tgt, 'TRANSACTED_WITH', 1.0, :now, :now, :now)"
            ),
            {
                "rid": rid,
                "src": source_entity_id,
                "tgt": target_entity_id,
                "now": _NOW,
            },
        )
    return rid


def _seed_alert_case(engine: Engine, customer_id: uuid.UUID) -> uuid.UUID:
    """Returns case_id."""
    alert_id = uuid.uuid4()
    case_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, created_at) "
                "VALUES (:aid, :cid, :now)"
            ),
            {"aid": alert_id, "cid": customer_id, "now": _NOW},
        )
        conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status, opened_at, created_at) "
                "VALUES (:case_id, :aid, 'OPEN', :now, :now)"
            ),
            {"case_id": case_id, "aid": alert_id, "now": _NOW},
        )
    return case_id


def _cleanup_data(
    superuser_engine: Engine, customer_id: uuid.UUID | None = None
) -> None:
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_runs"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM graph_relationships"))
        conn.execute(text("DELETE FROM entities"))
        if customer_id:
            conn.execute(
                text("DELETE FROM accounts WHERE customer_id = :cid"),
                {"cid": customer_id},
            )
            conn.execute(
                text("DELETE FROM customers WHERE customer_id = :cid"),
                {"cid": customer_id},
            )


# --- Tests ---


def test_graph_agent_dispatch_success(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Test 1 & 2 & 4: successful dispatch, exact audit row, no finding."""
    cid = _seed_customer(superuser_engine)
    aid = _seed_account(superuser_engine, cid)
    eid = _seed_entity(superuser_engine, reference_id=aid)

    # Create another entity to form a simple graph
    eid2 = _seed_entity(superuser_engine)
    rid = _seed_relationship(superuser_engine, eid, eid2)

    case_id = _seed_alert_case(superuser_engine, cid)

    try:
        # Pre-count tables for Test 4
        with superuser_engine.connect() as conn:
            evidence_before = (
                conn.execute(text("SELECT count(*) FROM evidence")).scalar() or 0
            )
            findings_before = (
                conn.execute(text("SELECT count(*) FROM findings")).scalar() or 0
            )

        inv_run = create_investigation_run(app_role_engine, case_id)

        # Dispatch
        dispatch_result = run_graph_agent(
            app_role_engine, inv_run.investigation_run_id, aid, max_hops=1
        )

        # Assertions for Test 1
        assert isinstance(dispatch_result, GraphAgentDispatchResult)
        assert dispatch_result.investigation_run_id == inv_run.investigation_run_id

        subgraph = dispatch_result.result
        assert isinstance(subgraph, SubgraphResult)
        assert subgraph.start_entity_id == eid
        assert subgraph.max_hops == 1
        assert set(subgraph.node_entity_ids) == {eid, eid2}
        assert set(subgraph.relationship_ids) == {rid}
        assert subgraph.truncated is False

        # Assertions for Test 2 (Database verification of agent_runs)
        with superuser_engine.connect() as conn:
            ar_rows = conn.execute(
                text(
                    "SELECT agent_name, status, error, tool_calls FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run.investigation_run_id},
            ).fetchall()

            assert len(ar_rows) == 1
            row = ar_rows[0]
            assert row[0] == "GraphAgent"
            assert row[1] == "SUCCESS"
            assert row[2] is None

            tool_calls = row[3]
            assert tool_calls is not None
            assert tool_calls.get("tool") == "sql_query"
            assert "entities:" in tool_calls.get("queries", [])[0]

        # Assertions for Test 4 (No evidence/finding side effects)
        with superuser_engine.connect() as conn:
            evidence_after = (
                conn.execute(text("SELECT count(*) FROM evidence")).scalar() or 0
            )
            findings_after = (
                conn.execute(text("SELECT count(*) FROM findings")).scalar() or 0
            )

            assert evidence_after == evidence_before
            assert findings_after == findings_before

    finally:
        _cleanup_data(superuser_engine, cid)


def test_graph_agent_dispatch_entity_not_found(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Test 3: failure behavior for unresolvable account."""
    cid = _seed_customer(superuser_engine)
    case_id = _seed_alert_case(superuser_engine, cid)

    # Random unseeded account
    fake_aid = uuid.uuid4()

    try:
        inv_run = create_investigation_run(app_role_engine, case_id)

        # Exception should propagate unchanged
        with pytest.raises(
            EntityNotFoundError, match="No entity with entity_type='account'"
        ):
            run_graph_agent(
                app_role_engine, inv_run.investigation_run_id, fake_aid, max_hops=2
            )

        # Assertions for Test 3 (agent_runs record is FAILED)
        with superuser_engine.connect() as conn:
            ar_rows = conn.execute(
                text(
                    "SELECT agent_name, status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run.investigation_run_id},
            ).fetchall()

            assert len(ar_rows) == 1
            row = ar_rows[0]
            assert row[0] == "GraphAgent"
            assert row[1] == "FAILED"
            assert row[2] is not None
            assert "No entity with entity_type='account'" in row[2]

    finally:
        _cleanup_data(superuser_engine, cid)


def test_graph_agent_dispatch_invalid_hops(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Test 5: boundary behavior for invalid graph inputs."""
    cid = _seed_customer(superuser_engine)
    aid = _seed_account(superuser_engine, cid)
    # MUST seed entity so it doesn't fail on resolution before max_hops check
    _seed_entity(superuser_engine, reference_id=aid)

    case_id = _seed_alert_case(superuser_engine, cid)

    try:
        inv_run = create_investigation_run(app_role_engine, case_id)

        # Exception should propagate unchanged
        with pytest.raises(InvalidGraphInputError, match="max_hops must be >= 1"):
            # Invalid max_hops
            run_graph_agent(
                app_role_engine, inv_run.investigation_run_id, aid, max_hops=0
            )

        # Verify agent_runs correctly captured the failed run
        with superuser_engine.connect() as conn:
            ar_rows = conn.execute(
                text(
                    "SELECT agent_name, status, error FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run.investigation_run_id},
            ).fetchall()

            assert len(ar_rows) == 1
            assert ar_rows[0][0] == "GraphAgent"
            assert ar_rows[0][1] == "FAILED"
            assert "max_hops must be >= 1" in ar_rows[0][2]

    finally:
        _cleanup_data(superuser_engine, cid)
