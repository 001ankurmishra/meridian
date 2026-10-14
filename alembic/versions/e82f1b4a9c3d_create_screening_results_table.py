"""create_screening_results_table

Revision ID: e82f1b4a9c3d
Revises: 4573f3e20e1c
Create Date: 2026-10-14 02:00:00.000000

"""

import os
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e82f1b4a9c3d"
down_revision: Union[str, Sequence[str], None] = "4573f3e20e1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to include screening_results table and role grants."""
    app_role = os.environ.get("APP_DB_USER", "meridian_app")
    bind = op.get_bind()

    # Check application role exists and bind to session parameter safely
    result = bind.execute(
        sa.text(
            "SELECT set_config('meridian.app_role', rolname, true) "
            "FROM pg_catalog.pg_roles WHERE rolname = :role_name"
        ),
        {"role_name": app_role},
    ).scalar()
    if not result:
        raise RuntimeError(
            f"Expected application role '{app_role}' does not exist; "
            "run the bootstrap init script before applying migrations"
        )

    op.create_table(
        "screening_results",
        sa.Column("screening_result_id", sa.UUID(), nullable=False),
        sa.Column("investigation_run_id", sa.UUID(), nullable=False),
        sa.Column("agent_run_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("watchlist_name", sa.Text(), nullable=False),
        sa.Column("watchlist_version", sa.Text(), nullable=False),
        sa.Column("matching_rule_id", sa.Text(), nullable=False),
        sa.Column("normalization_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("screening_result_id", name="screening_results_pkey"),
        sa.ForeignKeyConstraint(
            ["investigation_run_id"],
            ["investigation_runs.investigation_run_id"],
            name="fk_screening_results_investigation_run_id",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.agent_run_id"],
            name="fk_screening_results_agent_run_id",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.customer_id"],
            name="fk_screening_results_customer_id",
        ),
        sa.UniqueConstraint(
            "investigation_run_id",
            name="uq_screening_results_investigation_run_id",
        ),
        sa.UniqueConstraint(
            "agent_run_id",
            name="uq_screening_results_agent_run_id",
        ),
        sa.CheckConstraint(
            "outcome IN ("
            "'CANDIDATE_MATCHES_FOUND', "
            "'NO_CANDIDATE_MATCH', "
            "'NOT_PERFORMED'"
            ")",
            name="chk_screening_results_outcome",
        ),
        sa.CheckConstraint(
            "("
            "outcome = 'NOT_PERFORMED' AND reason_code IS NOT NULL AND "
            "reason_code IN ("
            "'CUSTOMER_NAME_MISSING', "
            "'CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION', "
            "'WATCHLIST_VERSION_NOT_LOADED'"
            ")"
            ") OR ("
            "outcome != 'NOT_PERFORMED' AND reason_code IS NULL"
            ")",
            name="chk_screening_results_reason_code",
        ),
        sa.CheckConstraint(
            "candidate_count >= 0 AND ("
            "(outcome = 'CANDIDATE_MATCHES_FOUND' AND candidate_count > 0) "
            "OR (outcome != 'CANDIDATE_MATCHES_FOUND' AND candidate_count = 0)"
            ")",
            name="chk_screening_results_candidate_count",
        ),
    )

    grant_script = (
        "DO $$\n"
        "DECLARE\n"
        "    app_role text := current_setting('meridian.app_role');\n"
        "BEGIN\n"
        "    EXECUTE format('GRANT SELECT, INSERT ON TABLE %I TO %I', "
        "'screening_results', app_role);\n"
        "    EXECUTE format('REVOKE UPDATE, DELETE ON TABLE %I FROM %I', "
        "'screening_results', app_role);\n"
        "END $$;\n"
    )
    op.execute(grant_script)


def downgrade() -> None:
    """Downgrade schema by dropping screening_results table."""
    op.drop_table("screening_results")
