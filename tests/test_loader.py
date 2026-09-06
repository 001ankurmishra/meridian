import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text


def test_loader_idempotency_and_data_accuracy() -> None:
    """
    Verify that running the loader creates correct data,
    and running it twice is idempotent.
    """
    loader_url = os.environ.get("LOADER_DATABASE_URL")
    if not loader_url:
        pytest.skip("LOADER_DATABASE_URL not set")

    engine = create_engine(loader_url)

    # 0. Ensure no downstream records exist from previous tests
    migrator_url = os.environ.get("DATABASE_URL")
    if migrator_url:
        migrator_engine = create_engine(migrator_url)
        with migrator_engine.begin() as conn:
            conn.execute(text("DELETE FROM audit_events"))
            conn.execute(text("DELETE FROM investigation_runs"))
            conn.execute(text("DELETE FROM cases"))
            conn.execute(text("DELETE FROM alerts"))

    # 1. Run loader manually (simulate first run)
    from meridian.loader.main import main

    main()

    with engine.connect() as conn:
        # Verify total counts
        c_count = conn.execute(text("SELECT count(*) FROM customers")).scalar()
        a_count = conn.execute(text("SELECT count(*) FROM accounts")).scalar()
        t_count = conn.execute(text("SELECT count(*) FROM transactions")).scalar()

        # Worked Example adds 4 customers, background adds 100 -> 104
        assert c_count == 104
        assert a_count == 104
        assert t_count == 509  # 500 bg + 6 hist + 1 suspicious + 2 split = 509

        # Verify orphans (none should exist)
        orphan_accts = conn.execute(
            text(
                "SELECT count(*) FROM accounts "
                "WHERE customer_id NOT IN (SELECT customer_id FROM customers)"
            )
        ).scalar()
        assert orphan_accts == 0

        orphan_tx_src = conn.execute(
            text(
                "SELECT count(*) FROM transactions "
                "WHERE source_account_id NOT IN (SELECT account_id FROM accounts)"
            )
        ).scalar()
        assert orphan_tx_src == 0

        # Verify Rahul Sharma exact background transactions average
        result = conn.execute(
            text("""
            SELECT AVG(t.amount)
            FROM transactions t
            JOIN accounts a ON t.source_account_id = a.account_id
            JOIN customers c ON a.customer_id = c.customer_id
            WHERE c.full_name = 'Rahul Sharma'
              AND t.destination_account_id IS NULL -- the background txs
        """)
        ).scalar()
        assert float(result if result is not None else 0.0) == 60000.0

        # Verify Rahul to Tech Solutions tx is exactly 980,000
        suspicious_tx_amount = conn.execute(
            text("""
            SELECT t.amount
            FROM transactions t
            JOIN accounts a_src ON t.source_account_id = a_src.account_id
            JOIN customers c_src ON a_src.customer_id = c_src.customer_id
            JOIN accounts a_dst ON t.destination_account_id = a_dst.account_id
            JOIN customers c_dst ON a_dst.customer_id = c_dst.customer_id
            WHERE c_src.full_name = 'Rahul Sharma'
              AND c_dst.full_name = 'Tech Solutions Inc'
        """)
        ).scalar()
        assert float(
            suspicious_tx_amount if suspicious_tx_amount is not None else 0.0
        ) == 980000.0

        # Save specific values to check idempotency byte-for-byte
        first_run_txs = conn.execute(
            text(
                "SELECT transaction_id, amount, source FROM transactions "
                "WHERE source = 'worked_example_v1' ORDER BY transaction_id"
            )
        ).fetchall()
        first_run_customers = conn.execute(
            text(
                "SELECT customer_id, full_name, source FROM customers "
                "WHERE source = 'worked_example_v1' ORDER BY customer_id"
            )
        ).fetchall()

        # Verify Tech Solutions txs explicitly match 500k and 450k
        tech_tx_amounts = (
            conn.execute(
                text("""
            SELECT t.amount
            FROM transactions t
            JOIN accounts a ON t.source_account_id = a.account_id
            JOIN customers c ON a.customer_id = c.customer_id
            WHERE c.full_name = 'Tech Solutions Inc'
        """)
            )
            .scalars()
            .all()
        )
        assert set([float(amt) for amt in tech_tx_amounts]) == {500000.0, 450000.0}

        # 2. Run loader again (simulate idempotency)
        main()

        # The counts should be EXACTLY the same
        c_count_after = conn.execute(text("SELECT count(*) FROM customers")).scalar()
        assert c_count_after == 104

        # Validate byte-for-byte matches
        second_run_txs = conn.execute(
            text(
                "SELECT transaction_id, amount, source FROM transactions "
                "WHERE source = 'worked_example_v1' ORDER BY transaction_id"
            )
        ).fetchall()
        second_run_customers = conn.execute(
            text(
                "SELECT customer_id, full_name, source FROM customers "
                "WHERE source = 'worked_example_v1' ORDER BY customer_id"
            )
        ).fetchall()

        assert first_run_txs == second_run_txs, (
            "Idempotency failed: Transactions data mismatched"
        )
        assert first_run_customers == second_run_customers, (
            "Idempotency failed: Customers data mismatched"
        )


def test_loader_precheck_abort() -> None:
    """
    Verify that clear_data loudly aborts if downstream alerts
    reference loader data.
    """
    migrator_url = os.environ.get("DATABASE_URL")
    if not migrator_url:
        pytest.skip("DATABASE_URL not set")

    migrator_engine = create_engine(migrator_url)

    # 1. Ensure we have data loaded
    from meridian.loader.main import main

    main()

    # 2. Insert a dummy alert referencing a real customer
    dummy_alert_id = uuid.uuid4()
    with migrator_engine.begin() as conn:
        customer_id = conn.execute(
            text("SELECT customer_id FROM customers LIMIT 1")
        ).scalar()
        conn.execute(
            text(
                """
                INSERT INTO alerts (
                    alert_id, customer_id, alert_type, raised_at, created_at
                ) VALUES (:aid, :cid, 'TEST', :now, :now)
                """
            ),
            {
                "aid": dummy_alert_id,
                "cid": customer_id,
                "now": datetime.now(timezone.utc),
            },
        )

    try:
        # 3. Attempt to run main() again, which should trigger clear_data abort
        with pytest.raises(RuntimeError) as excinfo:
            main()

        assert "ABORT LOUDLY" in str(excinfo.value)
        assert "Downstream 'alerts' table contains" in str(excinfo.value)

    finally:
        # 4. Clean up dummy alert
        with migrator_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM alerts WHERE alert_id = :aid"),
                {"aid": dummy_alert_id},
            )


def test_loader_least_privilege() -> None:
    """
    Verify meridian_loader cannot access orchestration tables
    and cannot UPDATE/DELETE.
    """
    loader_url = os.environ.get("LOADER_DATABASE_URL")
    if not loader_url:
        pytest.skip("LOADER_DATABASE_URL not set")

    engine = create_engine(loader_url)

    loader_tables = [
        "customers", "accounts", "transactions", "beneficiaries",
        "entities", "graph_relationships"
    ]

    with engine.connect() as conn:
        # Loader should be able to select from all its tables
        for table in loader_tables:
            conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))

    # Loader should fail to UPDATE its tables
    for table in loader_tables:
        with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                conn.execute(text(f"UPDATE {table} SET created_at = NOW()"))
            assert f"permission denied for table {table}" in str(excinfo.value)

    # Loader should fail to DELETE its tables
    for table in loader_tables:
        with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                conn.execute(text(f"DELETE FROM {table}"))
            assert f"permission denied for table {table}" in str(excinfo.value)

    orchestration_tables = [
        "alerts", "cases", "investigation_runs", "users", "audit_events"
    ]

    # Loader should fail to SELECT or INSERT into orchestration tables
    for table in orchestration_tables:
        with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
            assert f"permission denied for table {table}" in str(excinfo.value)

        with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                # We just run a dummy insert
                # which fails on permissions before anything else
                conn.execute(text(f"INSERT INTO {table} DEFAULT VALUES"))
            assert f"permission denied for table {table}" in str(excinfo.value)
