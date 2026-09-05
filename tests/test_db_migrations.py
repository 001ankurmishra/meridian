import os

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command


@pytest.fixture(scope="session", autouse=True)
def run_migrations():
    """Run Alembic migrations before the test session and tear down after."""
    alembic_cfg = Config("alembic.ini")

    # Upgrade to head
    command.upgrade(alembic_cfg, "head")

    yield

    # Downgrade to base to verify reversibility
    command.downgrade(alembic_cfg, "base")
    # Upgrade again so subsequent tests/teardowns are in a valid state
    command.upgrade(alembic_cfg, "head")


@pytest.fixture
def superuser_engine():
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://meridian_user:meridian_pass@localhost:5432/meridian_db",
    )
    engine = create_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def app_role_engine():
    app_db_url = os.environ.get(
        "APP_DATABASE_URL",
        "postgresql+psycopg://meridian_app:meridian_app_pass@localhost:5432/meridian_db",
    )
    engine = create_engine(app_db_url)
    yield engine
    engine.dispose()


def test_fk_constraint_negative(superuser_engine):
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


def test_check_constraint_negative(superuser_engine):
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


def test_app_role_cannot_update_audit_events(app_role_engine, superuser_engine):
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
