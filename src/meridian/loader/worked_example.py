import uuid
from datetime import datetime, timedelta, timezone
from typing import Any


def generate_worked_example() -> dict[str, list[dict[str, Any]]]:
    """Generate the explicit Rahul Sharma worked example scenario."""
    now = datetime.now(timezone.utc)

    # 1. Customers
    rahul_id = uuid.uuid5(uuid.NAMESPACE_OID, "rahul_sharma")
    tech_sol_id = uuid.uuid5(uuid.NAMESPACE_OID, "tech_solutions_inc")
    global_traders_id = uuid.uuid5(uuid.NAMESPACE_OID, "global_traders_llc")

    customers = [
        {
            "customer_id": rahul_id,
            "full_name": "Rahul Sharma",
            "date_of_birth": "1980-05-15",
            "kyc_risk_rating": "LOW",
            "onboarded_at": now - timedelta(days=365 * 5),
            "source": "worked_example_v1",
            "created_at": now,
            "is_synthetic": True,
        },
        {
            "customer_id": tech_sol_id,
            "full_name": "Tech Solutions Inc",
            "date_of_birth": None,
            "kyc_risk_rating": "MEDIUM",
            "onboarded_at": now - timedelta(days=365 * 2),
            "source": "worked_example_v1",
            "created_at": now,
            "is_synthetic": True,
        },
        {
            "customer_id": global_traders_id,
            "full_name": "Global Traders LLC",
            "date_of_birth": None,
            "kyc_risk_rating": "HIGH",
            "onboarded_at": now - timedelta(days=365 * 1),
            "source": "worked_example_v1",
            "created_at": now,
            "is_synthetic": True,
        },
    ]

    another_id = uuid.uuid5(uuid.NAMESPACE_OID, "another_company_llc")
    customers.append(
        {
            "customer_id": another_id,
            "full_name": "Another Company LLC",
            "date_of_birth": None,
            "kyc_risk_rating": "HIGH",
            "onboarded_at": now - timedelta(days=365 * 1),
            "source": "worked_example_v1",
            "created_at": now,
            "is_synthetic": True,
        }
    )

    # 2. Accounts
    rahul_acct_id = uuid.uuid5(uuid.NAMESPACE_OID, "rahul_acct_1")
    tech_sol_acct_id = uuid.uuid5(uuid.NAMESPACE_OID, "tech_sol_acct_1")
    global_traders_acct_id = uuid.uuid5(uuid.NAMESPACE_OID, "global_traders_acct_1")
    another_acct_id = uuid.uuid5(uuid.NAMESPACE_OID, "another_acct_1")

    accounts = [
        {
            "account_id": rahul_acct_id,
            "customer_id": rahul_id,
            "account_type": "SAVINGS",
            "opened_at": now - timedelta(days=365 * 5),
            "status": "active",
            "created_at": now,
        },
        {
            "account_id": tech_sol_acct_id,
            "customer_id": tech_sol_id,
            "account_type": "BUSINESS",
            "opened_at": now - timedelta(days=365 * 2),
            "status": "active",
            "created_at": now,
        },
        {
            "account_id": global_traders_acct_id,
            "customer_id": global_traders_id,
            "account_type": "BUSINESS",
            "opened_at": now - timedelta(days=365 * 1),
            "status": "active",
            "created_at": now,
        },
    ]
    accounts.append(
        {
            "account_id": another_acct_id,
            "customer_id": another_id,
            "account_type": "BUSINESS",
            "opened_at": now - timedelta(days=365 * 1),
            "status": "active",
            "created_at": now,
        }
    )

    # 3. Transactions
    transactions = []

    # Historical transactions for Rahul to make average precisely 60,000 INR
    # Let's say we have 6 months of history, exactly one transaction of 60,000 per month
    for i in range(1, 7):
        tx_time = now - timedelta(days=30 * i)
        transactions.append(
            {
                "transaction_id": uuid.uuid5(uuid.NAMESPACE_OID, f"rahul_hist_tx_{i}"),
                "source_account_id": rahul_acct_id,
                "destination_account_id": None,  # external transfer out or spending
                "amount": 60000.00,
                "currency": "INR",
                "transaction_type": "TRANSFER",
                "occurred_at": tx_time,
                "counterparty_external_ref": f"external_merchant_{i}",
                "source": "worked_example_v1",
                "created_at": now,
            }
        )

    # The Suspicious Transfer: 9,80,000 to Tech Solutions
    suspicious_tx_time = now - timedelta(hours=2)
    transactions.append(
        {
            "transaction_id": uuid.uuid5(uuid.NAMESPACE_OID, "rahul_to_tech_sol_tx"),
            "source_account_id": rahul_acct_id,
            "destination_account_id": tech_sol_acct_id,
            "amount": 980000.00,
            "currency": "INR",
            "transaction_type": "TRANSFER",
            "occurred_at": suspicious_tx_time,
            "counterparty_external_ref": None,
            "source": "worked_example_v1",
            "created_at": now,
        }
    )

    # The Split Transfers: Tech Solutions to Global Traders
    split_tx_time_1 = now - timedelta(hours=1, minutes=30)
    transactions.append(
        {
            "transaction_id": uuid.uuid5(uuid.NAMESPACE_OID, "tech_sol_to_global_tx_1"),
            "source_account_id": tech_sol_acct_id,
            "destination_account_id": global_traders_acct_id,
            "amount": 500000.00,
            "currency": "INR",
            "transaction_type": "TRANSFER",
            "occurred_at": split_tx_time_1,
            "counterparty_external_ref": None,
            "source": "worked_example_v1",
            "created_at": now,
        }
    )

    split_tx_time_2 = now - timedelta(hours=1, minutes=15)
    transactions.append(
        {
            "transaction_id": uuid.uuid5(
                uuid.NAMESPACE_OID, "tech_sol_to_another_tx_2"
            ),
            "source_account_id": tech_sol_acct_id,
            "destination_account_id": another_acct_id,
            "amount": 450000.00,
            "currency": "INR",
            "transaction_type": "TRANSFER",
            "occurred_at": split_tx_time_2,
            "counterparty_external_ref": None,
            "source": "worked_example_v1",
            "created_at": now,
        }
    )

    # 4. Beneficiaries
    beneficiaries = [
        {
            "beneficiary_id": uuid.uuid5(uuid.NAMESPACE_OID, "rahul_tech_sol_bene"),
            "customer_id": rahul_id,
            "account_id": tech_sol_acct_id,
            "added_at": now - timedelta(days=2),  # Added shortly before the transaction
            "created_at": now,
        },
        {
            "beneficiary_id": uuid.uuid5(uuid.NAMESPACE_OID, "tech_sol_global_bene"),
            "customer_id": tech_sol_id,
            "account_id": global_traders_acct_id,
            "added_at": now - timedelta(days=30),
            "created_at": now,
        },
    ]
    beneficiaries.append(
        {
            "beneficiary_id": uuid.uuid5(uuid.NAMESPACE_OID, "tech_sol_another_bene"),
            "customer_id": tech_sol_id,
            "account_id": another_acct_id,
            "added_at": now - timedelta(days=25),
            "created_at": now,
        }
    )

    # 5. Entities
    entities = []

    def add_entity(e_id: uuid.UUID, e_type: str, r_id: uuid.UUID) -> None:
        entities.append(
            {
                "entity_id": e_id,
                "entity_type": e_type,
                "reference_id": r_id,
                "created_at": now,
            }
        )

    rahul_entity_id = uuid.uuid5(uuid.NAMESPACE_OID, f"entity_cust_{rahul_id}")
    tech_sol_entity_id = uuid.uuid5(uuid.NAMESPACE_OID, f"entity_cust_{tech_sol_id}")
    global_traders_entity_id = uuid.uuid5(
        uuid.NAMESPACE_OID, f"entity_cust_{global_traders_id}"
    )
    another_entity_id = uuid.uuid5(uuid.NAMESPACE_OID, f"entity_cust_{another_id}")

    rahul_acct_entity_id = uuid.uuid5(
        uuid.NAMESPACE_OID, f"entity_acct_{rahul_acct_id}"
    )
    tech_sol_acct_entity_id = uuid.uuid5(
        uuid.NAMESPACE_OID, f"entity_acct_{tech_sol_acct_id}"
    )
    global_traders_acct_entity_id = uuid.uuid5(
        uuid.NAMESPACE_OID, f"entity_acct_{global_traders_acct_id}"
    )
    another_acct_entity_id = uuid.uuid5(
        uuid.NAMESPACE_OID, f"entity_acct_{another_acct_id}"
    )

    add_entity(rahul_entity_id, "customer", rahul_id)
    add_entity(tech_sol_entity_id, "customer", tech_sol_id)
    add_entity(global_traders_entity_id, "customer", global_traders_id)
    add_entity(another_entity_id, "customer", another_id)

    add_entity(rahul_acct_entity_id, "account", rahul_acct_id)
    add_entity(tech_sol_acct_entity_id, "account", tech_sol_acct_id)
    add_entity(global_traders_acct_entity_id, "account", global_traders_acct_id)
    add_entity(another_acct_entity_id, "account", another_acct_id)

    # 6. Graph Relationships
    graph_relationships = []

    def add_relationship(
        s_id: uuid.UUID,
        t_id: uuid.UUID,
        r_type: str,
        w: float,
        first_obs: datetime,
        last_obs: datetime,
    ) -> None:
        graph_relationships.append(
            {
                "relationship_id": uuid.uuid5(
                    uuid.NAMESPACE_OID, f"rel_{s_id}_{t_id}_{r_type}"
                ),
                "source_entity_id": s_id,
                "target_entity_id": t_id,
                "relationship_type": r_type,
                "weight": w,
                "first_observed_at": first_obs,
                "last_observed_at": last_obs,
                "created_at": now,
            }
        )

    # Customer owns account
    add_relationship(
        rahul_entity_id,
        rahul_acct_entity_id,
        "OWNS",
        1.0,
        now - timedelta(days=365 * 5),
        now,
    )
    add_relationship(
        tech_sol_entity_id,
        tech_sol_acct_entity_id,
        "OWNS",
        1.0,
        now - timedelta(days=365 * 2),
        now,
    )
    add_relationship(
        global_traders_entity_id,
        global_traders_acct_entity_id,
        "OWNS",
        1.0,
        now - timedelta(days=365 * 1),
        now,
    )
    add_relationship(
        another_entity_id,
        another_acct_entity_id,
        "OWNS",
        1.0,
        now - timedelta(days=365 * 1),
        now,
    )

    # Transacted with
    add_relationship(
        rahul_acct_entity_id,
        tech_sol_acct_entity_id,
        "TRANSACTED_WITH",
        1.0,
        suspicious_tx_time,
        suspicious_tx_time,
    )
    add_relationship(
        tech_sol_acct_entity_id,
        global_traders_acct_entity_id,
        "TRANSACTED_WITH",
        1.0,
        split_tx_time_1,
        split_tx_time_1,
    )
    add_relationship(
        tech_sol_acct_entity_id,
        another_acct_entity_id,
        "TRANSACTED_WITH",
        1.0,
        split_tx_time_2,
        split_tx_time_2,
    )

    return {
        "customers": customers,
        "accounts": accounts,
        "transactions": transactions,
        "beneficiaries": beneficiaries,
        "entities": entities,
        "graph_relationships": graph_relationships,
    }
