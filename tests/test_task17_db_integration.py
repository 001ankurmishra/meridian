import typing
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from meridian.orchestration.investigation_orchestrator import orchestrate_investigation
from tests.db_cleanup import clean_investigation_run_dependencies
from tests.test_transaction_agent_dispatch import (
    _seed_account,
    _seed_customer,
    _seed_transaction,
)


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
def clean_db(superuser_engine: Engine) -> typing.Generator[None, None, None]:
    _cleanup(superuser_engine)
    yield
    _cleanup(superuser_engine)


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


def test_wired_path_velocity_and_age(
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meridian.orchestration.graph_agent_dispatch as graph_agent
    import meridian.orchestration.policy_agent_dispatch as policy_agent

    monkeypatch.setattr(graph_agent, "_execute_graph_agent", lambda *a, **kw: None)

    from meridian.agents.policy.policy_agent import PolicyEvidenceFound

    monkeypatch.setattr(
        policy_agent,
        "retrieve_policy_evidence",
        lambda *a, **kw: PolicyEvidenceFound([]),
    )

    cid = _seed_customer(superuser_engine)
    aid = _seed_account(superuser_engine, cid)

    now = datetime.now(timezone.utc)
    # Seed transactions
    # 1. Alerted transaction
    tid_alerted = _seed_transaction(superuser_engine, aid, Decimal("500"), 0)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE transactions SET occurred_at = :now WHERE transaction_id = :tid"
            ),
            {"now": now, "tid": tid_alerted},
        )

    # 2. Historical (within 24 hours, velocity = 2)
    tid_hist_23h = _seed_transaction(superuser_engine, aid, Decimal("100"), 0)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE transactions SET occurred_at = :t WHERE transaction_id = :tid"
            ),
            {"t": now - timedelta(hours=23), "tid": tid_hist_23h},
        )

    # 3. Historical (outside 24 hours)
    tid_hist_25h = _seed_transaction(superuser_engine, aid, Decimal("100"), 0)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE transactions SET occurred_at = :t WHERE transaction_id = :tid"
            ),
            {"t": now - timedelta(hours=25), "tid": tid_hist_25h},
        )

    # Seed beneficiary
    dest_id = _seed_account(superuser_engine, cid)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE transactions SET destination_account_id = :dest_id WHERE transaction_id = :tid"  # noqa: E501
            ),
            {"dest_id": dest_id, "tid": tid_alerted},
        )
        ben_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO beneficiaries (beneficiary_id, customer_id, account_id, added_at, created_at) VALUES (:bid, :cid, :dest_id, :added_at, now())"  # noqa: E501
            ),
            {
                "bid": ben_id,
                "cid": cid,
                "dest_id": dest_id,
                "added_at": now - timedelta(days=2, hours=1),
            },
        )

    case_id = _seed_alert(superuser_engine, cid, tid_alerted)

    status = orchestrate_investigation(app_role_engine, case_id)
    assert status == "COMPLETE"

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text(
                "SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"  # noqa: E501
            ),
            {"cid": case_id},
        ).scalar()

        findings = conn.execute(
            text(
                "SELECT observed_fact, derived_signal FROM findings WHERE investigation_run_id = :rid"  # noqa: E501
            ),
            {"rid": inv_run_id},
        ).fetchall()
        risks = conn.execute(
            text(
                "SELECT signal_type, value FROM risk_signals WHERE investigation_run_id = :rid"  # noqa: E501
            ),
            {"rid": inv_run_id},
        ).fetchall()

    assert len(risks) == 3
    risk_dict = {r[0]: r[1] for r in risks}
    assert "amount_deviation" in risk_dict
    assert "transaction_velocity" in risk_dict
    assert risk_dict["transaction_velocity"] == Decimal("2")  # alerted + 23h
    assert "beneficiary_age" in risk_dict
    assert risk_dict["beneficiary_age"] == Decimal(49 * 3600)  # 2 days 1 hr

    finding_texts = [f[0] for f in findings]
    assert any("2 outgoing transaction(s)" in f for f in finding_texts)
    assert any("2 day(s), 1 hour(s)" in f for f in finding_texts)

def test_atomicity_rollback(
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meridian.orchestration.graph_agent_dispatch as graph_agent
    import meridian.orchestration.policy_agent_dispatch as policy_agent

    monkeypatch.setattr(graph_agent, "_execute_graph_agent", lambda *a, **kw: None)

    from meridian.agents.policy.policy_agent import PolicyEvidenceFound
    monkeypatch.setattr(
        policy_agent,
        "retrieve_policy_evidence",
        lambda *a, **kw: PolicyEvidenceFound([]),
    )

    cid = _seed_customer(superuser_engine)
    aid = _seed_account(superuser_engine, cid)
    tid_alerted = _seed_transaction(superuser_engine, aid, Decimal("500"), 0)
    now = datetime.now(timezone.utc)
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET occurred_at = :now WHERE transaction_id = :tid"),  # noqa: E501
            {"now": now, "tid": tid_alerted},
        )
    case_id = _seed_alert(superuser_engine, cid, tid_alerted)

    # Monkeypatch the DB engine to fail precisely on the final UPDATE
    from sqlalchemy.engine import Connection
    original_execute = Connection.execute

    def _failing_execute(self, statement, *args, **kwargs):
        stmt_str = str(statement)
        if "UPDATE investigation_runs SET status" in stmt_str:
            raise RuntimeError("Injected database failure")
        return original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(Connection, "execute", _failing_execute)

    with pytest.raises(RuntimeError, match="Injected database failure"):
        orchestrate_investigation(app_role_engine, case_id)

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text("SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"),  # noqa: E501
            {"cid": case_id},
        ).scalar()
        risks = conn.execute(
            text("SELECT risk_signal_id FROM risk_signals WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()
        findings = conn.execute(
            text("SELECT finding_id FROM findings WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()
        evidence = conn.execute(
            text("SELECT evidence_id FROM evidence WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()
        recommendations = conn.execute(
            text("SELECT recommendation_id FROM recommendations WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()

    assert len(risks) == 0
    assert len(findings) == 0
    assert len(evidence) == 0
    assert len(recommendations) == 0

def test_wired_path_velocity_edge_cases(
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meridian.orchestration.graph_agent_dispatch as graph_agent
    import meridian.orchestration.policy_agent_dispatch as policy_agent

    monkeypatch.setattr(graph_agent, "_execute_graph_agent", lambda *a, **kw: None)

    from meridian.agents.policy.policy_agent import PolicyEvidenceFound
    monkeypatch.setattr(
        policy_agent,
        "retrieve_policy_evidence",
        lambda *a, **kw: PolicyEvidenceFound([]),
    )

    cid = _seed_customer(superuser_engine)
    aid1 = _seed_account(superuser_engine, cid)
    aid2 = _seed_account(superuser_engine, cid)

    now = datetime.now(timezone.utc)

    # 1. Alerted transaction on aid1
    tid_alerted = _seed_transaction(superuser_engine, aid1, Decimal("500"), 0)
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET occurred_at = :now WHERE transaction_id = :tid"),  # noqa: E501
            {"now": now, "tid": tid_alerted},
        )

    # 2. Same timestamp on aid1
    tid_same = _seed_transaction(superuser_engine, aid1, Decimal("100"), 0)
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET occurred_at = :now WHERE transaction_id = :tid"),  # noqa: E501
            {"now": now, "tid": tid_same},
        )

    # 3. Exactly 24h boundary on aid2 (should be included)
    tid_exact_24 = _seed_transaction(superuser_engine, aid2, Decimal("100"), 0)
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET occurred_at = :t WHERE transaction_id = :tid"),  # noqa: E501
            {"t": now - timedelta(hours=24), "tid": tid_exact_24},
        )

    case_id = _seed_alert(superuser_engine, cid, tid_alerted)
    orchestrate_investigation(app_role_engine, case_id)

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text("SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"),  # noqa: E501
            {"cid": case_id},
        ).scalar()

        risks = conn.execute(
            text("SELECT signal_type, value FROM risk_signals WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()

    risk_dict = {r[0]: r[1] for r in risks}
    # alerted + same timestamp + exactly 24h boundary from multiple customer accounts
    assert risk_dict["transaction_velocity"] == Decimal("3")


def test_wired_path_beneficiary_age_edge_cases(
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meridian.orchestration.graph_agent_dispatch as graph_agent
    import meridian.orchestration.policy_agent_dispatch as policy_agent

    monkeypatch.setattr(graph_agent, "_execute_graph_agent", lambda *a, **kw: None)

    from meridian.agents.policy.policy_agent import PolicyEvidenceFound
    monkeypatch.setattr(
        policy_agent,
        "retrieve_policy_evidence",
        lambda *a, **kw: PolicyEvidenceFound([]),
    )

    cid = _seed_customer(superuser_engine)
    aid = _seed_account(superuser_engine, cid)
    dest_id = _seed_account(superuser_engine, cid)

    now = datetime.now(timezone.utc)

    # Alerted transaction
    tid_alerted = _seed_transaction(superuser_engine, aid, Decimal("500"), 0)
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET destination_account_id = :dest_id, occurred_at = :now WHERE transaction_id = :tid"),  # noqa: E501
            {"dest_id": dest_id, "now": now, "tid": tid_alerted},
        )

    # 1. Multiple beneficiaries, we want the earliest non-null
    with superuser_engine.begin() as conn:
        # Null added_at
        conn.execute(
            text("INSERT INTO beneficiaries (beneficiary_id, customer_id, account_id, added_at, created_at) VALUES (:bid, :cid, :dest_id, NULL, now())"),  # noqa: E501
            {"bid": uuid.uuid4(), "cid": cid, "dest_id": dest_id},
        )
        # Added after transaction
        conn.execute(
            text("INSERT INTO beneficiaries (beneficiary_id, customer_id, account_id, added_at, created_at) VALUES (:bid, :cid, :dest_id, :added_at, now())"),  # noqa: E501
            {"bid": uuid.uuid4(), "cid": cid, "dest_id": dest_id, "added_at": now + timedelta(days=1)},  # noqa: E501
        )
        # Added exactly now (zero age)
        conn.execute(
            text("INSERT INTO beneficiaries (beneficiary_id, customer_id, account_id, added_at, created_at) VALUES (:bid, :cid, :dest_id, :added_at, now())"),  # noqa: E501
            {"bid": uuid.uuid4(), "cid": cid, "dest_id": dest_id, "added_at": now},
        )

    case_id = _seed_alert(superuser_engine, cid, tid_alerted)
    orchestrate_investigation(app_role_engine, case_id)

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text("SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"),  # noqa: E501
            {"cid": case_id},
        ).scalar()
        risks = conn.execute(
            text("SELECT signal_type, value FROM risk_signals WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()

    risk_dict = {r[0]: r[1] for r in risks}
    # Zero age is valid and selected over NULL and added_after
    assert "beneficiary_age" in risk_dict
    assert risk_dict["beneficiary_age"] == Decimal("0")


def test_wired_path_beneficiary_age_unknown(
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meridian.orchestration.graph_agent_dispatch as graph_agent
    import meridian.orchestration.policy_agent_dispatch as policy_agent

    monkeypatch.setattr(graph_agent, "_execute_graph_agent", lambda *a, **kw: None)

    from meridian.agents.policy.policy_agent import PolicyEvidenceFound
    monkeypatch.setattr(
        policy_agent,
        "retrieve_policy_evidence",
        lambda *a, **kw: PolicyEvidenceFound([]),
    )

    cid = _seed_customer(superuser_engine)
    aid = _seed_account(superuser_engine, cid)
    dest_id = _seed_account(superuser_engine, cid)

    now = datetime.now(timezone.utc)

    tid_alerted = _seed_transaction(superuser_engine, aid, Decimal("500"), 0)
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET destination_account_id = :dest_id, occurred_at = :now WHERE transaction_id = :tid"),  # noqa: E501
            {"dest_id": dest_id, "now": now, "tid": tid_alerted},
        )

    # Only NULL added_at
    with superuser_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO beneficiaries (beneficiary_id, customer_id, account_id, added_at, created_at) VALUES (:bid, :cid, :dest_id, NULL, now())"),  # noqa: E501
            {"bid": uuid.uuid4(), "cid": cid, "dest_id": dest_id},
        )

    case_id = _seed_alert(superuser_engine, cid, tid_alerted)
    orchestrate_investigation(app_role_engine, case_id)

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text("SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"),  # noqa: E501
            {"cid": case_id},
        ).scalar()
        risks = conn.execute(
            text("SELECT signal_type FROM risk_signals WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()
        evidence_keys = conn.execute(
            text("SELECT evidence_type FROM evidence WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()
        findings = conn.execute(
            text("SELECT observed_fact FROM findings WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()

    risk_types = [r[0] for r in risks]
    assert "beneficiary_age" not in risk_types

    e_keys = [e[0] for e in evidence_keys]
    assert not any(k.startswith("beneficiary_age_") for k in e_keys)

    f_texts = [f[0] for f in findings]
    assert not any("Beneficiary age" in f for f in f_texts)

def test_wired_path_beneficiary_earliest_non_null(
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meridian.orchestration.graph_agent_dispatch as graph_agent
    import meridian.orchestration.policy_agent_dispatch as policy_agent

    monkeypatch.setattr(graph_agent, "_execute_graph_agent", lambda *a, **kw: None)

    from meridian.agents.policy.policy_agent import PolicyEvidenceFound
    monkeypatch.setattr(
        policy_agent,
        "retrieve_policy_evidence",
        lambda *a, **kw: PolicyEvidenceFound([]),
    )

    cid = _seed_customer(superuser_engine)
    aid = _seed_account(superuser_engine, cid)
    dest_id = _seed_account(superuser_engine, cid)

    now = datetime.now(timezone.utc)

    tid_alerted = _seed_transaction(superuser_engine, aid, Decimal("500"), 0)
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET destination_account_id = :dest_id, occurred_at = :now WHERE transaction_id = :tid"),  # noqa: E501
            {"dest_id": dest_id, "now": now, "tid": tid_alerted},
        )

    with superuser_engine.begin() as conn:
        # NULL added_at
        conn.execute(
            text("INSERT INTO beneficiaries (beneficiary_id, customer_id, account_id, added_at, created_at) VALUES (:bid, :cid, :dest_id, NULL, now())"),  # noqa: E501
            {"bid": uuid.uuid4(), "cid": cid, "dest_id": dest_id},
        )
        # 5 days BEFORE
        conn.execute(
            text("INSERT INTO beneficiaries (beneficiary_id, customer_id, account_id, added_at, created_at) VALUES (:bid, :cid, :dest_id, :added_at, now())"),  # noqa: E501
            {"bid": uuid.uuid4(), "cid": cid, "dest_id": dest_id, "added_at": now - timedelta(days=5)},  # noqa: E501
        )
        # 2 days BEFORE
        conn.execute(
            text("INSERT INTO beneficiaries (beneficiary_id, customer_id, account_id, added_at, created_at) VALUES (:bid, :cid, :dest_id, :added_at, now())"),  # noqa: E501
            {"bid": uuid.uuid4(), "cid": cid, "dest_id": dest_id, "added_at": now - timedelta(days=2)},  # noqa: E501
        )
        # 1 day AFTER
        conn.execute(
            text("INSERT INTO beneficiaries (beneficiary_id, customer_id, account_id, added_at, created_at) VALUES (:bid, :cid, :dest_id, :added_at, now())"),  # noqa: E501
            {"bid": uuid.uuid4(), "cid": cid, "dest_id": dest_id, "added_at": now + timedelta(days=1)},  # noqa: E501
        )

    case_id = _seed_alert(superuser_engine, cid, tid_alerted)
    orchestrate_investigation(app_role_engine, case_id)

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text("SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"),  # noqa: E501
            {"cid": case_id},
        ).scalar()
        risks = conn.execute(
            text("SELECT signal_type, value FROM risk_signals WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()

    risk_dict = {r[0]: r[1] for r in risks}
    assert "beneficiary_age" in risk_dict
    assert risk_dict["beneficiary_age"] == Decimal(5 * 24 * 3600)


def test_wired_path_beneficiary_age_added_after_unknown(
    app_role_engine: Engine,
    superuser_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meridian.orchestration.graph_agent_dispatch as graph_agent
    import meridian.orchestration.policy_agent_dispatch as policy_agent

    monkeypatch.setattr(graph_agent, "_execute_graph_agent", lambda *a, **kw: None)

    from meridian.agents.policy.policy_agent import PolicyEvidenceFound
    monkeypatch.setattr(
        policy_agent,
        "retrieve_policy_evidence",
        lambda *a, **kw: PolicyEvidenceFound([]),
    )

    cid = _seed_customer(superuser_engine)
    aid = _seed_account(superuser_engine, cid)
    dest_id = _seed_account(superuser_engine, cid)

    now = datetime.now(timezone.utc)

    tid_alerted = _seed_transaction(superuser_engine, aid, Decimal("500"), 0)
    with superuser_engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET destination_account_id = :dest_id, occurred_at = :now WHERE transaction_id = :tid"),  # noqa: E501
            {"dest_id": dest_id, "now": now, "tid": tid_alerted},
        )

    # Only 1 day AFTER
    with superuser_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO beneficiaries (beneficiary_id, customer_id, account_id, added_at, created_at) VALUES (:bid, :cid, :dest_id, :added_at, now())"),  # noqa: E501
            {"bid": uuid.uuid4(), "cid": cid, "dest_id": dest_id, "added_at": now + timedelta(days=1)},  # noqa: E501
        )

    case_id = _seed_alert(superuser_engine, cid, tid_alerted)
    orchestrate_investigation(app_role_engine, case_id)

    with superuser_engine.connect() as conn:
        inv_run_id = conn.execute(
            text("SELECT investigation_run_id FROM investigation_runs WHERE case_id = :cid"),  # noqa: E501
            {"cid": case_id},
        ).scalar()
        risks = conn.execute(
            text("SELECT signal_type FROM risk_signals WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()
        evidence_keys = conn.execute(
            text("SELECT evidence_type FROM evidence WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()
        findings = conn.execute(
            text("SELECT observed_fact FROM findings WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()
        recommendations = conn.execute(
            text("SELECT text FROM recommendations WHERE investigation_run_id = :rid"),  # noqa: E501
            {"rid": inv_run_id},
        ).fetchall()

    risk_types = [r[0] for r in risks]
    assert "beneficiary_age" not in risk_types

    e_keys = [e[0] for e in evidence_keys]
    assert not any(k.startswith("beneficiary_age_") for k in e_keys)

    f_texts = [f[0] for f in findings]
    assert not any("Beneficiary age" in f for f in f_texts)

    r_texts = [r[0] for r in recommendations]
    assert not any("Beneficiary age" in r for r in r_texts)
