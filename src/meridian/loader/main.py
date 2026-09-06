import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Engine, create_engine, text

from meridian.loader.worked_example import generate_worked_example


def get_loader_engine() -> Engine:
    db_url = os.environ.get("LOADER_DATABASE_URL")
    if not db_url:
        print(
            "Error: LOADER_DATABASE_URL environment variable is not set.",
            file=sys.stderr,
        )
        sys.exit(1)
    return create_engine(db_url)


def get_migrator_engine() -> Engine:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return create_engine(db_url)


def clear_data(migrator_engine: Engine) -> None:
    """Idempotent clearing of tables in FK-safe child-first order using the role."""
    print("Pre-checking for downstream references...")
    with migrator_engine.connect() as conn:
        # Check alerts table for references to loader-owned data
        alerts_count_raw = conn.execute(text("SELECT count(*) FROM alerts")).scalar()
        alerts_count = int(alerts_count_raw) if alerts_count_raw is not None else 0
        if alerts_count > 0:
            raise RuntimeError(
                f"ABORT LOUDLY: Cannot clear data. Downstream 'alerts' table "
                f"contains {alerts_count} rows. Clearing would violate "
                "referential integrity or destroy real case data."
            )

    print("Clearing tables...")
    with migrator_engine.begin() as conn:
        conn.execute(text("DELETE FROM graph_relationships"))
        conn.execute(text("DELETE FROM entities"))
        conn.execute(text("DELETE FROM beneficiaries"))
        conn.execute(text("DELETE FROM transactions"))
        conn.execute(text("DELETE FROM accounts"))
        conn.execute(text("DELETE FROM customers"))
    print("Tables cleared.")


def generate_background_data() -> dict[str, list[dict[str, Any]]]:
    """Generate bulk synthetic background data (mimicking AMLSim network)."""
    now = datetime.now(timezone.utc)
    customers = []
    accounts = []
    transactions: list[dict[str, Any]] = []
    beneficiaries: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    graph_relationships = []

    # Generate 100 background customers
    for i in range(100):
        c_id = uuid.uuid4()
        a_id = uuid.uuid4()
        e_c_id = uuid.uuid4()
        e_a_id = uuid.uuid4()

        customers.append(
            {
                "customer_id": c_id,
                "full_name": f"Synthetic User {i}",
                "date_of_birth": (
                    now - timedelta(days=365 * random.randint(18, 70))
                ).strftime("%Y-%m-%d"),
                "kyc_risk_rating": random.choice(["LOW", "MEDIUM", "HIGH"]),
                "onboarded_at": now - timedelta(days=random.randint(10, 1000)),
                "source": "meridian_native_generator_v1",
                "created_at": now,
                "is_synthetic": True,
            }
        )

        accounts.append(
            {
                "account_id": a_id,
                "customer_id": c_id,
                "account_type": random.choice(["SAVINGS", "CHECKING", "BUSINESS"]),
                "opened_at": now - timedelta(days=random.randint(5, 1000)),
                "status": "active",
                "created_at": now,
            }
        )

        entities.append(
            {
                "entity_id": e_c_id,
                "entity_type": "customer",
                "reference_id": c_id,
                "created_at": now,
            }
        )
        entities.append(
            {
                "entity_id": e_a_id,
                "entity_type": "account",
                "reference_id": a_id,
                "created_at": now,
            }
        )

        graph_relationships.append(
            {
                "relationship_id": uuid.uuid4(),
                "source_entity_id": e_c_id,
                "target_entity_id": e_a_id,
                "relationship_type": "OWNS",
                "weight": 1.0,
                "first_observed_at": now - timedelta(days=100),
                "last_observed_at": now,
                "created_at": now,
            }
        )

    # Generate transactions between accounts
    for i in range(500):
        src_acct = random.choice(accounts)["account_id"]
        dst_acct = random.choice(accounts)["account_id"]
        while src_acct == dst_acct:
            dst_acct = random.choice(accounts)["account_id"]

        tx_time = now - timedelta(hours=random.randint(1, 2400))
        transactions.append(
            {
                "transaction_id": uuid.uuid4(),
                "source_account_id": src_acct,
                "destination_account_id": dst_acct,
                "amount": round(random.uniform(10.0, 50000.0), 2),
                "currency": "INR",
                "transaction_type": "TRANSFER",
                "occurred_at": tx_time,
                "counterparty_external_ref": None,
                "source": "meridian_native_generator_v1",
                "created_at": now,
            }
        )

        # Find corresponding entities to create TRANSACTED_WITH relationship
        # For simplicity in background, we might skip building full graph edges
        # for every tx or just add them lazily if needed. The worked example
        # contains the explicit edges.

    return {
        "customers": customers,
        "accounts": accounts,
        "transactions": transactions,
        "beneficiaries": beneficiaries,
        "entities": entities,
        "graph_relationships": graph_relationships,
    }


def insert_data(engine: Engine, data_dict: dict[str, list[dict[str, Any]]]) -> None:
    print("Inserting data...")
    with engine.begin() as conn:
        if data_dict["customers"]:
            conn.execute(
                text(
                    "INSERT INTO customers (customer_id, full_name, date_of_birth, "
                    "kyc_risk_rating, onboarded_at, source, created_at, is_synthetic) "
                    "VALUES (:customer_id, :full_name, :date_of_birth, "
                    ":kyc_risk_rating, "
                    ":onboarded_at, :source, :created_at, :is_synthetic)"
                ),
                data_dict["customers"],
            )

        if data_dict["accounts"]:
            conn.execute(
                text(
                    "INSERT INTO accounts (account_id, customer_id, account_type, "
                    "opened_at, status, created_at) "
                    "VALUES (:account_id, :customer_id, :account_type, :opened_at, "
                    ":status, :created_at)"
                ),
                data_dict["accounts"],
            )

        if data_dict["transactions"]:
            conn.execute(
                text(
                    "INSERT INTO transactions (transaction_id, source_account_id, "
                    "destination_account_id, amount, currency, transaction_type, "
                    "occurred_at, counterparty_external_ref, source, created_at) "
                    "VALUES (:transaction_id, :source_account_id, "
                    ":destination_account_id, :amount, :currency, :transaction_type, "
                    ":occurred_at, :counterparty_external_ref, :source, :created_at)"
                ),
                data_dict["transactions"],
            )

        if data_dict["beneficiaries"]:
            conn.execute(
                text(
                    "INSERT INTO beneficiaries (beneficiary_id, customer_id, "
                    "account_id, added_at, created_at) "
                    "VALUES (:beneficiary_id, :customer_id, :account_id, "
                    ":added_at, :created_at)"
                ),
                data_dict["beneficiaries"],
            )

        if data_dict["entities"]:
            conn.execute(
                text("""
                INSERT INTO entities (entity_id, entity_type, reference_id, created_at)
                VALUES (:entity_id, :entity_type, :reference_id, :created_at)
                """),
                data_dict["entities"],
            )

        if data_dict["graph_relationships"]:
            conn.execute(
                text(
                    "INSERT INTO graph_relationships (relationship_id, "
                    "source_entity_id, target_entity_id, relationship_type, weight, "
                    "first_observed_at, "
                    "last_observed_at, created_at) "
                    "VALUES (:relationship_id, :source_entity_id, "
                    ":target_entity_id, :relationship_type, :weight, "
                    ":first_observed_at, :last_observed_at, :created_at)"
                ),
                data_dict["graph_relationships"],
            )
    print("Data inserted.")


def main() -> None:
    migrator_engine = get_migrator_engine()
    clear_data(migrator_engine)

    loader_engine = get_loader_engine()

    # Generate and Insert Worked Example
    we_data = generate_worked_example()
    insert_data(loader_engine, we_data)

    # Generate and Insert Background Data
    bg_data = generate_background_data()
    insert_data(loader_engine, bg_data)

    print("Load complete.")


if __name__ == "__main__":
    main()
