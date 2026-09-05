"""initial_schema

Revision ID: 6a92f1f7c7e8
Revises:
Create Date: 2026-09-05 15:25:39.000000

"""

import os
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6a92f1f7c7e8"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    app_role = os.environ.get("APP_DB_USER", "meridian_app")
    bind = op.get_bind()

    # 0. Check role exists
    result = bind.execute(
        sa.text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :role_name"),
        {"role_name": app_role},
    ).scalar()
    if not result:
        raise RuntimeError(
            f"Expected application role '{app_role}' does not exist; "
            "run the bootstrap init script before applying migrations"
        )

    # 1. Extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Tables
    # 1. customers
    op.create_table(
        "customers",
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("kyc_risk_rating", sa.Text(), nullable=True),
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_synthetic", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.PrimaryKeyConstraint("customer_id"),
        sa.CheckConstraint("is_synthetic = true", name="chk_customers_is_synthetic"),
        sa.CheckConstraint(
            "kyc_risk_rating IN ('LOW', 'MEDIUM', 'HIGH')",
            name="chk_customers_kyc_risk_rating",
        ),
    )

    # 2. users
    op.create_table(
        "users",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("email"),
        sa.CheckConstraint(
            "role IN ('analyst', 'senior_analyst', 'compliance_manager', 'admin')",
            name="chk_users_role",
        ),
    )

    # 3. accounts
    op.create_table(
        "accounts",
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("account_type", sa.Text(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.customer_id"]),
        sa.PrimaryKeyConstraint("account_id"),
        sa.CheckConstraint(
            "status IN ('active', 'closed', 'frozen')", name="chk_accounts_status"
        ),
    )
    op.create_index("ix_accounts_customer_id", "accounts", ["customer_id"])

    # 4. transactions
    op.create_table(
        "transactions",
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("source_account_id", sa.UUID(), nullable=True),
        sa.Column("destination_account_id", sa.UUID(), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("transaction_type", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("counterparty_external_ref", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_account_id"], ["accounts.account_id"]),
        sa.ForeignKeyConstraint(["destination_account_id"], ["accounts.account_id"]),
        sa.PrimaryKeyConstraint("transaction_id"),
    )
    op.create_index(
        "ix_transactions_source_account_id_occurred_at",
        "transactions",
        ["source_account_id", "occurred_at"],
    )
    op.create_index(
        "ix_transactions_destination_account_id_occurred_at",
        "transactions",
        ["destination_account_id", "occurred_at"],
    )

    # 5. beneficiaries
    op.create_table(
        "beneficiaries",
        sa.Column("beneficiary_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.customer_id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
        sa.PrimaryKeyConstraint("beneficiary_id"),
    )

    # 6. entities
    op.create_table(
        "entities",
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("reference_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("entity_id"),
        sa.CheckConstraint(
            "entity_type IN ('customer', 'account', 'beneficiary', "
            "'device', 'merchant')",
            name="chk_entities_type",
        ),
    )

    # 7. graph_relationships
    op.create_table(
        "graph_relationships",
        sa.Column("relationship_id", sa.UUID(), nullable=False),
        sa.Column("source_entity_id", sa.UUID(), nullable=False),
        sa.Column("target_entity_id", sa.UUID(), nullable=False),
        sa.Column("relationship_type", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_entity_id"], ["entities.entity_id"]),
        sa.ForeignKeyConstraint(["target_entity_id"], ["entities.entity_id"]),
        sa.PrimaryKeyConstraint("relationship_id"),
    )
    op.create_index(
        "ix_graph_relationships_source_entity_id",
        "graph_relationships",
        ["source_entity_id"],
    )
    op.create_index(
        "ix_graph_relationships_target_entity_id",
        "graph_relationships",
        ["target_entity_id"],
    )
    op.create_index(
        "ix_graph_relationships_relationship_type",
        "graph_relationships",
        ["relationship_type"],
    )

    # 8. alerts
    op.create_table(
        "alerts",
        sa.Column("alert_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column("alert_type", sa.Text(), nullable=True),
        sa.Column("alert_reasons", sa.JSON(), nullable=True),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_system", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.customer_id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.transaction_id"]),
        sa.PrimaryKeyConstraint("alert_id"),
    )

    # 9. cases
    op.create_table(
        "cases",
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("alert_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("assigned_analyst_id", sa.UUID(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.alert_id"]),
        sa.ForeignKeyConstraint(["assigned_analyst_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("case_id"),
        sa.CheckConstraint(
            "status IN ('OPEN', 'IN_REVIEW', 'ESCALATED', "
            "'CLOSED_APPROVED', 'CLOSED_REJECTED', 'CLOSED_MORE_INFO')",
            name="chk_cases_status",
        ),
    )

    # 10. investigation_runs
    # NOTE: This table is a minimal FK-dependency skeleton for audit_events.
    # Full implementation is deferred to Phase 1.
    op.create_table(
        "investigation_runs",
        sa.Column("investigation_run_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.PrimaryKeyConstraint("investigation_run_id"),
        sa.CheckConstraint(
            "status IN ('IN_PROGRESS', 'COMPLETE', "
            "'INCOMPLETE_INSUFFICIENT_EVIDENCE', 'FAILED')",
            name="chk_investigation_runs_status",
        ),
    )

    # 11. audit_events
    op.create_table(
        "audit_events",
        sa.Column("audit_event_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("investigation_run_id", sa.UUID(), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("input_summary", sa.JSON(), nullable=True),
        sa.Column("output_summary", sa.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.ForeignKeyConstraint(
            ["investigation_run_id"], ["investigation_runs.investigation_run_id"]
        ),
        sa.PrimaryKeyConstraint("audit_event_id"),
        sa.CheckConstraint(
            "actor_type IN ('agent', 'human', 'system')",
            name="chk_audit_events_actor_type",
        ),
    )

    # 3. Grants
    grant_script = (
        "DO $$\n"
        "BEGIN\n"
        "    -- SELECT ONLY\n"
        "    EXECUTE format('GRANT SELECT ON TABLE %I TO %I', "
        f"'customers', '{app_role}');\n"
        "    EXECUTE format('GRANT SELECT ON TABLE %I TO %I', "
        f"'accounts', '{app_role}');\n"
        "    EXECUTE format('GRANT SELECT ON TABLE %I TO %I', "
        f"'transactions', '{app_role}');\n"
        "    EXECUTE format('GRANT SELECT ON TABLE %I TO %I', "
        f"'beneficiaries', '{app_role}');\n"
        "\n"
        "    -- SELECT, INSERT, UPDATE\n"
        "    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON TABLE %I TO %I', "
        f"'entities', '{app_role}');\n"
        "    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON TABLE %I TO %I', "
        f"'graph_relationships', '{app_role}');\n"
        "    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON TABLE %I TO %I', "
        f"'alerts', '{app_role}');\n"
        "    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON TABLE %I TO %I', "
        f"'cases', '{app_role}');\n"
        "    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON TABLE %I TO %I', "
        f"'investigation_runs', '{app_role}');\n"
        "    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON TABLE %I TO %I', "
        f"'users', '{app_role}');\n"
        "\n"
        "    -- SELECT, INSERT (audit_events - REVOKE UPDATE, DELETE logic)\n"
        "    EXECUTE format('GRANT SELECT, INSERT ON TABLE %I TO %I', "
        f"'audit_events', '{app_role}');\n"
        "    -- Ensure UPDATE and DELETE are explicitly revoked (defense in depth)\n"
        "    EXECUTE format('REVOKE UPDATE, DELETE ON TABLE %I FROM %I', "
        f"'audit_events', '{app_role}');\n"
        "END $$;\n"
    )
    op.execute(grant_script)


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("investigation_runs")
    op.drop_table("cases")
    op.drop_table("alerts")
    op.drop_index(
        "ix_graph_relationships_relationship_type", table_name="graph_relationships"
    )
    op.drop_index(
        "ix_graph_relationships_target_entity_id", table_name="graph_relationships"
    )
    op.drop_index(
        "ix_graph_relationships_source_entity_id", table_name="graph_relationships"
    )
    op.drop_table("graph_relationships")
    op.drop_table("entities")
    op.drop_table("beneficiaries")
    op.drop_index(
        "ix_transactions_destination_account_id_occurred_at",
        table_name="transactions",
    )
    op.drop_index(
        "ix_transactions_source_account_id_occurred_at", table_name="transactions"
    )
    op.drop_table("transactions")
    op.drop_index("ix_accounts_customer_id", table_name="accounts")
    op.drop_table("accounts")
    op.drop_table("users")
    op.drop_table("customers")

    op.execute("DROP EXTENSION IF EXISTS vector")
