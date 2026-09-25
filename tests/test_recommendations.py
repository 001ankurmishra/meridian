"""Tests for recommendations module."""

import uuid
from datetime import datetime, timezone

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text

from alembic import command
from meridian.evidence.evidence import record_evidence
from meridian.findings.findings import record_finding
from meridian.orchestration.investigation_run import create_investigation_run
from meridian.orchestration.transaction_agent_dispatch import run_transaction_agent
from meridian.recommendations.recommendations import record_recommendation
from tests.db_cleanup import clean_investigation_run_dependencies


def setup_customer_and_transaction(
    superuser_engine: Engine, amount: float = 100.0, days_ago: int = 0
) -> tuple[uuid.UUID, uuid.UUID]:
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

    aid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (account_id, customer_id, status, created_at) "
                "VALUES (:aid, :cid, 'active', :now)"
            ),
            {"aid": aid, "cid": cid, "now": datetime.now(timezone.utc)},
        )

    tid = uuid.uuid4()
    occurred_at = datetime.now(timezone.utc)
    if days_ago > 0:
        import datetime as dt

        occurred_at -= dt.timedelta(days=days_ago)

    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions "
                "(transaction_id, source_account_id, amount, "
                "currency, occurred_at, created_at) "
                "VALUES (:tid, :aid, :amount, 'INR', :occ, :now)"
            ),
            {
                "tid": tid,
                "aid": aid,
                "amount": amount,
                "occ": occurred_at,
                "now": datetime.now(timezone.utc),
            },
        )
    return cid, tid


def setup_alert(
    superuser_engine: Engine, customer_id: uuid.UUID, transaction_id: uuid.UUID
) -> uuid.UUID:
    alert_id = uuid.uuid4()
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
    return alert_id


def setup_case(superuser_engine: Engine, alert_id: uuid.UUID) -> uuid.UUID:
    """Helper to setup a case for an alert."""
    case_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO cases "
                "(case_id, alert_id, status, created_at) "
                "VALUES (:cid, :aid, 'OPEN', :now)"
            ),
            {"cid": case_id, "aid": alert_id, "now": now},
        )
    return case_id


def _cleanup_seeded_data(superuser_engine: Engine, customer_id: uuid.UUID) -> None:
    with superuser_engine.begin() as conn:
        clean_investigation_run_dependencies(conn)
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(
            text(
                "DELETE FROM transactions WHERE source_account_id IN "
                "(SELECT account_id FROM accounts WHERE customer_id = :cid)"
            ),
            {"cid": customer_id},
        )
        conn.execute(
            text("DELETE FROM accounts WHERE customer_id = :cid"), {"cid": customer_id}
        )
        conn.execute(
            text("DELETE FROM customers WHERE customer_id = :cid"), {"cid": customer_id}
        )


def test_migration_downgrade_upgrade(superuser_engine: Engine) -> None:
    """Test that migration downgrade drops the table and upgrade recreates it."""
    alembic_cfg = Config("alembic.ini")

    # The prior revision before recommendations is 202c96c61bbf
    command.downgrade(alembic_cfg, "202c96c61bbf")

    with superuser_engine.connect() as conn:
        with pytest.raises(Exception):
            conn.execute(text("SELECT * FROM recommendations"))

    # upgrade to head
    command.upgrade(alembic_cfg, "head")

    with superuser_engine.connect() as conn:
        res = conn.execute(text("SELECT count(*) FROM recommendations")).scalar()
        assert res == 0


def test_fk_integrity(app_role_engine: Engine) -> None:
    """Attempt to insert a recommendation using a nonexistent investigation_run_id."""
    with app_role_engine.connect() as conn:
        with pytest.raises(Exception) as excinfo:
            conn.execute(
                text(
                    "INSERT INTO recommendations ("
                    "recommendation_id, investigation_run_id, text, "
                    "based_on_finding_ids, created_at) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), 'rec', "
                    "'{}', NOW())"
                )
            )
            conn.commit()
        assert "foreign key constraint" in str(excinfo.value).lower()
        conn.rollback()


def test_app_role_privileges(app_role_engine: Engine, superuser_engine: Engine) -> None:
    """meridian_app can SELECT/INSERT but not UPDATE/DELETE on recommendations."""
    cid, tid = setup_customer_and_transaction(superuser_engine)
    try:
        alert_id = setup_alert(superuser_engine, cid, tid)
        case_id = setup_case(superuser_engine, alert_id)
        inv_run = create_investigation_run(app_role_engine, case_id)

        r_id = uuid.uuid4()

        with app_role_engine.connect() as conn:
            # INSERT should succeed
            conn.execute(
                text(
                    "INSERT INTO recommendations ("
                    "recommendation_id, investigation_run_id, text, "
                    "based_on_finding_ids, created_at) "
                    "VALUES (:r_id, :inv_id, 'test rec', "
                    "'{}', NOW())"
                ),
                {
                    "r_id": r_id,
                    "inv_id": inv_run.investigation_run_id,
                },
            )
            conn.commit()

            # SELECT should succeed
            count = conn.execute(
                text(
                    "SELECT count(*) FROM recommendations "
                    "WHERE recommendation_id = :r_id"
                ),
                {"r_id": r_id},
            ).scalar()
            assert count == 1

            # UPDATE should fail
            with pytest.raises(Exception) as excinfo:
                conn.execute(
                    text(
                        "UPDATE recommendations SET text = 'new rec' "
                        "WHERE recommendation_id = :r_id"
                    ),
                    {"r_id": r_id},
                )
                conn.commit()
            assert "permission denied" in str(excinfo.value).lower()
            conn.rollback()

            # DELETE should fail
            with pytest.raises(Exception) as excinfo:
                conn.execute(
                    text("DELETE FROM recommendations WHERE recommendation_id = :r_id"),
                    {"r_id": r_id},
                )
                conn.commit()
            assert "permission denied" in str(excinfo.value).lower()
            conn.rollback()

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_unresolvable_finding_rejection(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """record_recommendation rejects on nonexistent finding UUID."""
    cid, tid = setup_customer_and_transaction(superuser_engine)
    try:
        alert_id = setup_alert(superuser_engine, cid, tid)
        case_id = setup_case(superuser_engine, alert_id)
        inv_run = create_investigation_run(app_role_engine, case_id)

        random_finding_id = uuid.uuid4()

        with pytest.raises(ValueError, match="do not exist in the findings table"):
            record_recommendation(
                engine=app_role_engine,
                investigation_run_id=inv_run.investigation_run_id,
                recommendation_text="Escalate",
                based_on_finding_ids=[random_finding_id],
            )

        # Verify no recommendation row was inserted
        with superuser_engine.connect() as conn:
            res = conn.execute(
                text(
                    "SELECT count(*) FROM recommendations "
                    "WHERE investigation_run_id = :inv_id"
                ),
                {"inv_id": inv_run.investigation_run_id},
            ).scalar()
            assert res == 0

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_empty_finding_reference_behavior(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """record_recommendation permits empty finding references."""
    cid, tid = setup_customer_and_transaction(superuser_engine)
    try:
        alert_id = setup_alert(superuser_engine, cid, tid)
        case_id = setup_case(superuser_engine, alert_id)
        inv_run = create_investigation_run(app_role_engine, case_id)

        rec = record_recommendation(
            engine=app_role_engine,
            investigation_run_id=inv_run.investigation_run_id,
            recommendation_text="Escalate",
            based_on_finding_ids=[],
        )

        assert rec.investigation_run_id == inv_run.investigation_run_id
        assert rec.based_on_finding_ids == []

    finally:
        _cleanup_seeded_data(superuser_engine, cid)


def test_real_proof_case(app_role_engine: Engine, superuser_engine: Engine) -> None:
    """Proof case linking transaction dispatch to recommendation."""
    cid, tid = setup_customer_and_transaction(
        superuser_engine, amount=450.0, days_ago=0
    )
    try:
        # Seed history
        with superuser_engine.connect() as conn:
            aid = conn.execute(
                text("SELECT account_id FROM accounts WHERE customer_id = :cid"),
                {"cid": cid},
            ).scalar()

        # Generate some previous transactions
        occurred_at_1 = datetime.now(timezone.utc)
        import datetime as dt

        occurred_at_1 -= dt.timedelta(days=10)

        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO transactions "
                    "(transaction_id, source_account_id, amount, "
                    "currency, occurred_at, created_at) "
                    "VALUES (:tid, :src, :amount, 'INR', :occ, :now)"
                ),
                {
                    "tid": uuid.uuid4(),
                    "src": aid,
                    "amount": 100.0,
                    "occ": occurred_at_1,
                    "now": datetime.now(timezone.utc),
                },
            )

        alert_id = setup_alert(superuser_engine, cid, tid)
        case_id = setup_case(superuser_engine, alert_id)

        # 1. create_investigation_run
        inv_run = create_investigation_run(app_role_engine, case_id)

        # 2. run_transaction_agent
        run_transaction_agent(
            app_role_engine,
            inv_run.investigation_run_id,
            tid,
        )

        # 3. get agent_run_id
        with superuser_engine.connect() as conn:
            ar_id = conn.execute(
                text(
                    "SELECT agent_run_id FROM agent_runs "
                    "WHERE investigation_run_id = :inv_id "
                    "AND agent_name = 'TransactionAgent'"
                ),
                {"inv_id": inv_run.investigation_run_id},
            ).scalar()
        assert ar_id is not None

        # 4. record_evidence
        evidence_record = record_evidence(
            app_role_engine,
            investigation_run_id=inv_run.investigation_run_id,
            evidence_type="transaction_amount_deviation",
            reference_table="transactions",
            reference_id=tid,
            produced_by_agent_run_id=ar_id,
        )

        # 5. record_finding
        finding_record = record_finding(
            engine=app_role_engine,
            investigation_run_id=inv_run.investigation_run_id,
            observed_fact="Transaction deviation",
            derived_signal=None,
            interpretation=None,
            evidence_ids=[evidence_record.evidence_id],
            confidence="MEDIUM",
        )

        # 6. record_recommendation
        rec_record = record_recommendation(
            engine=app_role_engine,
            investigation_run_id=inv_run.investigation_run_id,
            recommendation_text="Proceed with review",
            based_on_finding_ids=[finding_record.finding_id],
        )

        # 7. verify
        assert rec_record.investigation_run_id == inv_run.investigation_run_id
        assert rec_record.text == "Proceed with review"
        assert rec_record.based_on_finding_ids == [finding_record.finding_id]

    finally:
        _cleanup_seeded_data(superuser_engine, cid)
