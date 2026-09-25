"""Tests for F9 audit trail reconstruction (audit.audit_trail)."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from meridian.audit.audit_events import record_audit_event
from meridian.audit.audit_trail import get_case_audit_trail
from meridian.audit.errors import CaseNotFoundError
from meridian.evidence.evidence import record_evidence
from meridian.findings.findings import record_finding
from meridian.orchestration.agent_run_tracking import record_agent_run
from meridian.orchestration.investigation_run import create_investigation_run
from meridian.orchestration.transaction_agent_dispatch import run_transaction_agent
from tests.db_cleanup import clean_investigation_run_dependencies


def _seed_customer(superuser_engine: Engine) -> uuid.UUID:
    cid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers "
                "(customer_id, full_name, is_synthetic, created_at) "
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
    occurred_at = datetime.now(timezone.utc)
    if days_ago > 0:
        occurred_at -= timedelta(days=days_ago)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions "
                "(transaction_id, source_account_id, amount, currency, "
                "occurred_at, created_at) "
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
    superuser_engine: Engine,
    customer_id: uuid.UUID,
    transaction_id: uuid.UUID | None = None,
) -> uuid.UUID:
    alert_id = uuid.uuid4()
    case_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts "
                "(alert_id, customer_id, transaction_id, created_at) "
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
    return case_id


def _cleanup(superuser_engine: Engine, customer_id: uuid.UUID | None = None) -> None:
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events"))
        conn.execute(text("DELETE FROM findings"))
        conn.execute(text("DELETE FROM evidence"))
        clean_investigation_run_dependencies(conn)
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))
        if customer_id is not None:
            conn.execute(
                text(
                    "DELETE FROM transactions WHERE source_account_id IN "
                    "(SELECT account_id FROM accounts WHERE customer_id = :cid)"
                ),
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


# --- 1. Missing case -------------------------------------------------------


def test_missing_case_raises_case_not_found(app_role_engine: Engine) -> None:
    with pytest.raises(CaseNotFoundError):
        get_case_audit_trail(app_role_engine, uuid.uuid4())


# --- 2. Empty case (no investigation runs yet) ------------------------------


def test_empty_case_returns_empty_lists(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    cid = _seed_customer(superuser_engine)
    case_id = _seed_alert_case(superuser_engine, cid)
    try:
        trail = get_case_audit_trail(app_role_engine, case_id)
        assert trail.case_id == case_id
        assert trail.case_status == "OPEN"
        assert trail.investigation_runs == ()
        assert trail.audit_events == ()
    finally:
        _cleanup(superuser_engine, cid)


# --- 3. Full reconstruction: agent run + evidence + finding + human decision


def test_full_reconstruction(app_role_engine: Engine, superuser_engine: Engine) -> None:
    cid = _seed_customer(superuser_engine)
    try:
        aid = _seed_account(superuser_engine, cid)
        _seed_transaction(superuser_engine, aid, Decimal("50.0"), 10)
        tid = _seed_transaction(superuser_engine, aid, Decimal("1000.0"), 0)
        case_id = _seed_alert_case(superuser_engine, cid, tid)
        inv_run = create_investigation_run(app_role_engine, case_id)

        run_transaction_agent(app_role_engine, inv_run.investigation_run_id, tid)

        with superuser_engine.connect() as conn:
            agent_run_id = conn.execute(
                text(
                    "SELECT agent_run_id FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run.investigation_run_id},
            ).scalar_one()

        ev = record_evidence(
            app_role_engine,
            inv_run.investigation_run_id,
            "transaction",
            "transactions",
            tid,
            agent_run_id,
        )
        record_finding(
            app_role_engine,
            inv_run.investigation_run_id,
            observed_fact="Transaction amount is 20x historical average.",
            derived_signal="20.0x deviation",
            interpretation="Significant deviation from historical behavior.",
            evidence_ids=[ev.evidence_id],
            confidence="MEDIUM",
        )

        # A human decision (F8) tied to this case.
        with app_role_engine.begin() as conn:
            record_audit_event(
                conn,
                case_id=case_id,
                actor_type="human",
                actor_id=str(uuid.uuid4()),
                action="CASE_ESCALATED",
                input_summary={"requested_action": "ESCALATE"},
                output_summary={"from_status": "OPEN", "to_status": "ESCALATED"},
                occurred_at=datetime.now(timezone.utc),
                investigation_run_id=inv_run.investigation_run_id,
            )

        trail = get_case_audit_trail(app_role_engine, case_id)

        assert trail.case_id == case_id
        assert len(trail.investigation_runs) == 1
        run_entry = trail.investigation_runs[0]
        assert run_entry.investigation_run_id == inv_run.investigation_run_id

        assert len(run_entry.agent_runs) == 1
        assert run_entry.agent_runs[0].agent_name == "TransactionAgent"
        assert run_entry.agent_runs[0].status == "SUCCESS"
        # tool_calls must be the real, non-fabricated summary passed by the
        # dispatch layer -- not the old hardcoded {}.
        assert run_entry.agent_runs[0].tool_calls != {}
        assert "queries" in run_entry.agent_runs[0].tool_calls

        assert len(run_entry.evidence) == 1
        assert run_entry.evidence[0].evidence_id == ev.evidence_id
        assert run_entry.evidence[0].evidence_type == "transaction"

        assert len(run_entry.findings) == 1
        assert run_entry.findings[0].confidence == "MEDIUM"
        assert ev.evidence_id in run_entry.findings[0].evidence_ids

        assert len(trail.audit_events) == 1
        assert trail.audit_events[0].action == "CASE_ESCALATED"
        assert trail.audit_events[0].output_summary is not None
        assert trail.audit_events[0].output_summary["to_status"] == "ESCALATED"

    finally:
        _cleanup(superuser_engine, cid)


# --- 4. Chronological ordering ----------------------------------------------


def test_chronological_ordering_of_agent_runs(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    cid = _seed_customer(superuser_engine)
    try:
        case_id = _seed_alert_case(superuser_engine, cid)
        inv_run = create_investigation_run(app_role_engine, case_id)

        def _noop_agent() -> str:
            return "ok"

        # Record three agent runs out of alphabetical order to prove the
        # result is ordered by started_at, not by insertion order or name.
        record_agent_run(
            app_role_engine, inv_run.investigation_run_id, "ThirdAgent", _noop_agent
        )
        record_agent_run(
            app_role_engine, inv_run.investigation_run_id, "FirstAgent", _noop_agent
        )
        record_agent_run(
            app_role_engine, inv_run.investigation_run_id, "SecondAgent", _noop_agent
        )

        trail = get_case_audit_trail(app_role_engine, case_id)
        names = [ar.agent_name for ar in trail.investigation_runs[0].agent_runs]
        # started_at is assigned at call time, so real call order is the
        # expected chronological order regardless of the misleading names.
        assert names == ["ThirdAgent", "FirstAgent", "SecondAgent"]

    finally:
        _cleanup(superuser_engine, cid)


# --- 5. Multiple investigation runs on one case -----------------------------


def test_multiple_investigation_runs_all_present(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    cid = _seed_customer(superuser_engine)
    try:
        case_id = _seed_alert_case(superuser_engine, cid)

        run_1 = create_investigation_run(app_role_engine, case_id)
        run_2 = create_investigation_run(app_role_engine, case_id)

        trail = get_case_audit_trail(app_role_engine, case_id)

        assert len(trail.investigation_runs) == 2
        returned_ids = {r.investigation_run_id for r in trail.investigation_runs}
        assert returned_ids == {
            run_1.investigation_run_id,
            run_2.investigation_run_id,
        }
        # Ordered chronologically: run_1 was created first.
        assert (
            trail.investigation_runs[0].investigation_run_id
            == run_1.investigation_run_id
        )
        assert (
            trail.investigation_runs[1].investigation_run_id
            == run_2.investigation_run_id
        )

    finally:
        _cleanup(superuser_engine, cid)


# --- 6. tool_calls persistence on success and failure -----------------------


def test_tool_calls_persisted_on_success(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    cid = _seed_customer(superuser_engine)
    try:
        case_id = _seed_alert_case(superuser_engine, cid)
        inv_run = create_investigation_run(app_role_engine, case_id)

        def _noop_agent() -> str:
            return "ok"

        summary = {"tool": "sql_query", "queries": ["some_table: lookup by id"]}
        record_agent_run(
            app_role_engine,
            inv_run.investigation_run_id,
            "TestAgent",
            _noop_agent,
            tool_calls=summary,
        )

        with superuser_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT tool_calls FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run.investigation_run_id},
            ).fetchone()
            assert row is not None
            assert row[0] == summary

    finally:
        _cleanup(superuser_engine, cid)


def test_tool_calls_persisted_on_failure(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    cid = _seed_customer(superuser_engine)
    try:
        case_id = _seed_alert_case(superuser_engine, cid)
        inv_run = create_investigation_run(app_role_engine, case_id)

        def _failing_agent() -> None:
            raise ValueError("deliberate test failure")

        summary = {"tool": "sql_query", "queries": ["some_table: lookup by id"]}
        with pytest.raises(ValueError, match="deliberate test failure"):
            record_agent_run(
                app_role_engine,
                inv_run.investigation_run_id,
                "TestAgent",
                _failing_agent,
                tool_calls=summary,
            )

        with superuser_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT status, tool_calls FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run.investigation_run_id},
            ).fetchone()
            assert row is not None
            assert row[0] == "FAILED"
            assert row[1] == summary

    finally:
        _cleanup(superuser_engine, cid)


def test_tool_calls_default_none_recorded_as_empty_object(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """No tool_calls argument supplied -> stored as {} (unchanged prior
    behavior), never fabricated by record_agent_run itself."""
    cid = _seed_customer(superuser_engine)
    try:
        case_id = _seed_alert_case(superuser_engine, cid)
        inv_run = create_investigation_run(app_role_engine, case_id)

        def _noop_agent() -> str:
            return "ok"

        record_agent_run(
            app_role_engine, inv_run.investigation_run_id, "TestAgent", _noop_agent
        )

        with superuser_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT tool_calls FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run.investigation_run_id},
            ).fetchone()
            assert row is not None
            assert row[0] == {}

    finally:
        _cleanup(superuser_engine, cid)


# --- 7. Integration with real dispatch behavior (TransactionAgent) ---------


def test_integration_transaction_agent_dispatch_tool_calls(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """The real TransactionAgent dispatch path (not a stub) must now
    populate a truthful, non-empty tool_calls summary, and that summary
    must be visible via get_case_audit_trail()."""
    cid = _seed_customer(superuser_engine)
    try:
        aid = _seed_account(superuser_engine, cid)
        _seed_transaction(superuser_engine, aid, Decimal("50.0"), 10)
        tid = _seed_transaction(superuser_engine, aid, Decimal("1000.0"), 0)
        case_id = _seed_alert_case(superuser_engine, cid, tid)
        inv_run = create_investigation_run(app_role_engine, case_id)

        run_transaction_agent(app_role_engine, inv_run.investigation_run_id, tid)

        trail = get_case_audit_trail(app_role_engine, case_id)
        assert len(trail.investigation_runs) == 1
        agent_runs = trail.investigation_runs[0].agent_runs
        assert len(agent_runs) == 1
        assert agent_runs[0].agent_name == "TransactionAgent"
        assert agent_runs[0].tool_calls["tool"] == "sql_query"
        assert any("transactions" in q for q in agent_runs[0].tool_calls["queries"])

    finally:
        _cleanup(superuser_engine, cid)
