import os
from typing import Generator

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

from alembic import command




def test_fk_constraint_negative(superuser_engine: Engine) -> None:
    """Test that inserting a transaction with a non-existent account fails."""
    with superuser_engine.begin() as conn:
        with pytest.raises(Exception) as excinfo:
            conn.execute(
                text(
                    "INSERT INTO transactions "
                    "(transaction_id, source_account_id) "
                    "VALUES (gen_random_uuid(), gen_random_uuid())"
                )
            )
        assert "foreign key constraint" in str(excinfo.value).lower()


def test_check_constraint_negative(superuser_engine: Engine) -> None:
    """Test that inserting an invalid status in accounts table fails."""
    with superuser_engine.begin() as conn:
        # First create a customer
        cust_id = conn.execute(
            text(
                "INSERT INTO customers (customer_id, full_name, is_synthetic) "
                "VALUES (gen_random_uuid(), 'Test', true) "
                "RETURNING customer_id"
            )
        ).scalar()

        with pytest.raises(Exception) as excinfo:
            conn.execute(
                text(
                    "INSERT INTO accounts (account_id, customer_id, status) "
                    "VALUES (gen_random_uuid(), :cust_id, 'INVALID_STATUS')"
                ),
                {"cust_id": cust_id},
            )
        assert "check constraint" in str(excinfo.value).lower()


def test_app_role_cannot_update_audit_events(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """
    Test that the application DB role cannot UPDATE or DELETE rows in audit_events.
    """

    # Setup data as superuser to ensure it exists
    with superuser_engine.begin() as conn:
        audit_id = conn.execute(
            text(
                "INSERT INTO audit_events (audit_event_id, actor_type, action) "
                "VALUES (gen_random_uuid(), 'system', 'test_action') "
                "RETURNING audit_event_id"
            )
        ).scalar()

    # Now try to update/delete as app_role
    with app_role_engine.connect() as conn:
        # The app role has INSERT and SELECT on audit_events

        # Test SELECT succeeds
        res = conn.execute(text("SELECT * FROM audit_events")).fetchall()
        assert len(res) >= 1

        # Test INSERT succeeds
        conn.execute(
            text(
                "INSERT INTO audit_events (audit_event_id, actor_type, action) "
                "VALUES (gen_random_uuid(), 'system', 'test_action2')"
            )
        )
        conn.commit()

        # Test UPDATE fails
        with pytest.raises(Exception) as excinfo:
            conn.execute(
                text(
                    "UPDATE audit_events SET action = 'hacked' "
                    "WHERE audit_event_id = :id"
                ),
                {"id": audit_id},
            )
            conn.commit()
        assert "permission denied" in str(excinfo.value).lower()

        # In SQLAlchemy with psycopg, a failed transaction needs rollback
        conn.rollback()

        # Test DELETE fails
        with pytest.raises(Exception) as excinfo:
            conn.execute(
                text("DELETE FROM audit_events WHERE audit_event_id = :id"),
                {"id": audit_id},
            )
            conn.commit()
        assert "permission denied" in str(excinfo.value).lower()


def test_app_role_privileges_read_only(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """
    Test that meridian_app CAN SELECT from:
    customers, accounts, transactions, beneficiaries
    but CANNOT INSERT, UPDATE, or DELETE on them.
    """
    # Create parent rows as superuser
    with superuser_engine.begin() as conn:
        cust_id = conn.execute(
            text(
                "INSERT INTO customers (customer_id, full_name, is_synthetic) "
                "VALUES (gen_random_uuid(), 'Test Cust', true) "
                "RETURNING customer_id"
            )
        ).scalar()
        acc_id = conn.execute(
            text(
                "INSERT INTO accounts (account_id, customer_id, status) "
                "VALUES (gen_random_uuid(), :cust_id, 'active') "
                "RETURNING account_id"
            ),
            {"cust_id": cust_id},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO transactions (transaction_id, source_account_id) "
                "VALUES (gen_random_uuid(), :acc_id) "
                "RETURNING transaction_id"
            ),
            {"acc_id": acc_id},
        )
        conn.execute(
            text(
                "INSERT INTO beneficiaries (beneficiary_id, customer_id, account_id) "
                "VALUES (gen_random_uuid(), :cust_id, :acc_id) "
                "RETURNING beneficiary_id"
            ),
            {"cust_id": cust_id, "acc_id": acc_id},
        )

    tables = ["customers", "accounts", "transactions", "beneficiaries"]
    with app_role_engine.connect() as conn:
        for table in tables:
            # SELECT succeeds
            res = conn.execute(text(f"SELECT * FROM {table}")).fetchall()
            assert len(res) >= 1

            # INSERT fails
            with pytest.raises(Exception) as excinfo:
                if table == "customers":
                    conn.execute(
                        text(
                            "INSERT INTO customers (customer_id, is_synthetic) "
                            "VALUES (gen_random_uuid(), true)"
                        )
                    )
                elif table == "accounts":
                    conn.execute(
                        text(
                            "INSERT INTO accounts (account_id, customer_id, status) "
                            "VALUES (gen_random_uuid(), :cust_id, 'active')"
                        ),
                        {"cust_id": cust_id},
                    )
                elif table == "transactions":
                    conn.execute(
                        text(
                            "INSERT INTO transactions "
                            "(transaction_id, source_account_id) "
                            "VALUES (gen_random_uuid(), :acc_id)"
                        ),
                        {"acc_id": acc_id},
                    )
                elif table == "beneficiaries":
                    conn.execute(
                        text(
                            "INSERT INTO beneficiaries (beneficiary_id, customer_id) "
                            "VALUES (gen_random_uuid(), :cust_id)"
                        ),
                        {"cust_id": cust_id},
                    )
            assert "permission denied" in str(excinfo.value).lower()
            conn.rollback()

            # UPDATE fails
            with pytest.raises(Exception) as excinfo:
                conn.execute(text(f"UPDATE {table} SET created_at = NOW()"))
            assert "permission denied" in str(excinfo.value).lower()
            conn.rollback()

            # DELETE fails
            with pytest.raises(Exception) as excinfo:
                conn.execute(text(f"DELETE FROM {table}"))
            assert "permission denied" in str(excinfo.value).lower()
            conn.rollback()


def test_app_role_privileges_read_write(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """
    Test that meridian_app CAN perform intended writes on:
    entities, graph_relationships, alerts, cases, investigation_runs, users
    """
    with superuser_engine.begin() as conn:
        cust_id = conn.execute(
            text(
                "INSERT INTO customers (customer_id, full_name, is_synthetic) "
                "VALUES (gen_random_uuid(), 'Test Cust', true) "
                "RETURNING customer_id"
            )
        ).scalar()
        acc_id = conn.execute(
            text(
                "INSERT INTO accounts (account_id, customer_id, status) "
                "VALUES (gen_random_uuid(), :cust_id, 'active') "
                "RETURNING account_id"
            ),
            {"cust_id": cust_id},
        ).scalar()
        txn_id = conn.execute(
            text(
                "INSERT INTO transactions (transaction_id, source_account_id) "
                "VALUES (gen_random_uuid(), :acc_id) "
                "RETURNING transaction_id"
            ),
            {"acc_id": acc_id},
        ).scalar()

    with app_role_engine.connect() as conn:
        # entities
        ent_id = conn.execute(
            text(
                "INSERT INTO entities (entity_id, entity_type, reference_id) "
                "VALUES (gen_random_uuid(), 'customer', :cust_id) "
                "RETURNING entity_id"
            ),
            {"cust_id": cust_id},
        ).scalar()

        ent_id2 = conn.execute(
            text(
                "INSERT INTO entities (entity_id, entity_type, reference_id) "
                "VALUES (gen_random_uuid(), 'account', :acc_id) "
                "RETURNING entity_id"
            ),
            {"acc_id": acc_id},
        ).scalar()

        # graph_relationships
        conn.execute(
            text(
                "INSERT INTO graph_relationships (relationship_id, source_entity_id, "
                "target_entity_id, relationship_type) "
                "VALUES (gen_random_uuid(), :e1, :e2, 'owns')"
            ),
            {"e1": ent_id, "e2": ent_id2},
        )

        # alerts
        alert_id = conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, transaction_id) "
                "VALUES (gen_random_uuid(), :cust_id, :txn_id) "
                "RETURNING alert_id"
            ),
            {"cust_id": cust_id, "txn_id": txn_id},
        ).scalar()

        # users
        user_id = conn.execute(
            text(
                "INSERT INTO users (user_id, email, role) "
                "VALUES (gen_random_uuid(), 'test@test.com', 'analyst') "
                "RETURNING user_id"
            )
        ).scalar()

        # cases
        case_id = conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, assigned_analyst_id, status) "
                "VALUES (gen_random_uuid(), :alert_id, :user_id, 'OPEN') "
                "RETURNING case_id"
            ),
            {"alert_id": alert_id, "user_id": user_id},
        ).scalar()

        # investigation_runs
        conn.execute(
            text(
                "INSERT INTO investigation_runs (investigation_run_id, case_id, "
                "status) VALUES (gen_random_uuid(), :case_id, 'IN_PROGRESS')"
            ),
            {"case_id": case_id},
        )
        conn.commit()

        # Test SELECT on all 6 tables
        rw_tables = [
            "entities", "graph_relationships", "alerts",
            "cases", "investigation_runs", "users"
        ]
        for table in rw_tables:
            res = conn.execute(text(f"SELECT * FROM {table}")).fetchall()
            assert len(res) >= 1

        # Test UPDATE on all 6 tables
        conn.execute(text("UPDATE entities SET created_at = NOW()"))
        conn.execute(text("UPDATE graph_relationships SET created_at = NOW()"))
        conn.execute(text("UPDATE alerts SET created_at = NOW()"))
        conn.execute(
            text("UPDATE cases SET status = 'IN_REVIEW' WHERE case_id = :case_id"),
            {"case_id": case_id},
        )
        conn.execute(text("UPDATE investigation_runs SET created_at = NOW()"))
        conn.execute(text("UPDATE users SET created_at = NOW()"))
        conn.commit()

        # Test DELETE fails on all 6 tables
        for table in rw_tables:
            with pytest.raises(Exception) as excinfo:
                conn.execute(text(f"DELETE FROM {table}"))
                conn.commit()
            assert "permission denied" in str(excinfo.value).lower()
            conn.rollback()
