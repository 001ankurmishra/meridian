"""create agent_runs table

Revision ID: 644b6b3e6eb8
Revises: c4250b2c09d2
Create Date: 2026-09-11 16:19:22.593686

"""
import os
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '644b6b3e6eb8'
down_revision: Union[str, Sequence[str], None] = 'c4250b2c09d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    app_role = os.environ.get("APP_DB_USER", "meridian_app")
    bind = op.get_bind()

    # Check role exists
    result = bind.execute(
        sa.text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :role_name"),
        {"role_name": app_role},
    ).scalar()
    if not result:
        raise RuntimeError(
            f"Expected application role '{app_role}' does not exist; "
            "run the bootstrap init script before applying migrations"
        )

    op.create_table(
        "agent_runs",
        sa.Column("agent_run_id", sa.UUID(), nullable=False),
        sa.Column("investigation_run_id", sa.UUID(), nullable=False),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("tool_calls", JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("model_identifier", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["investigation_run_id"], ["investigation_runs.investigation_run_id"]
        ),
        sa.PrimaryKeyConstraint("agent_run_id"),
        sa.CheckConstraint(
            "status IN ('SUCCESS', 'FAILED', 'PARTIAL')",
            name="chk_agent_runs_status",
        ),
    )

    grant_script = (
        "DO $$\n"
        "BEGIN\n"
        "    EXECUTE format('GRANT SELECT, INSERT ON TABLE %I TO %I', "
        f"'agent_runs', '{app_role}');\n"
        "    EXECUTE format('REVOKE UPDATE, DELETE ON TABLE %I FROM %I', "
        f"'agent_runs', '{app_role}');\n"
        "END $$;\n"
    )
    op.execute(grant_script)


def downgrade() -> None:
    op.drop_table("agent_runs")
