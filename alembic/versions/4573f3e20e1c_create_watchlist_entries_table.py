"""create_watchlist_entries_table

Revision ID: 4573f3e20e1c
Revises: f284a67877be
Create Date: 2026-10-10 02:21:15.813195

"""

import os
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4573f3e20e1c"
down_revision: Union[str, Sequence[str], None] = "f284a67877be"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to include watchlist_entries table and grants."""
    app_role = os.environ.get("APP_DB_USER", "meridian_app")
    loader_role = os.environ.get("LOADER_DB_USER", "meridian_loader")
    bind = op.get_bind()

    # Validate roles exist
    for role_name in (app_role, loader_role):
        result = bind.execute(
            sa.text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :role_name"),
            {"role_name": role_name},
        ).scalar()
        if not result:
            raise RuntimeError(
                f"Expected role '{role_name}' does not exist; "
                "run the bootstrap init script before applying migrations"
            )

    op.create_table(
        "watchlist_entries",
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("watchlist_name", sa.Text(), nullable=False),
        sa.Column("watchlist_version", sa.Text(), nullable=False),
        sa.Column("subject_key", sa.Text(), nullable=False),
        sa.Column("name_type", sa.Text(), nullable=False),
        sa.Column("listed_name", sa.Text(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("entry_id"),
        sa.CheckConstraint(
            "name_type IN ('primary', 'alias')",
            name="ck_watchlist_entries_name_type",
        ),
        sa.CheckConstraint(
            "length(trim(listed_name)) > 0",
            name="ck_watchlist_entries_listed_name_non_blank",
        ),
        sa.CheckConstraint(
            "is_synthetic = true",
            name="ck_watchlist_entries_is_synthetic",
        ),
        sa.UniqueConstraint(
            "watchlist_name",
            "watchlist_version",
            "subject_key",
            "name_type",
            "listed_name",
            name="uq_watchlist_entries_natural_key",
        ),
    )

    op.create_index(
        "ix_watchlist_entries_name_version",
        "watchlist_entries",
        ["watchlist_name", "watchlist_version"],
    )

    grant_script = (
        "DO $$\n"
        "BEGIN\n"
        "    -- SELECT ONLY for app_role\n"
        f"    EXECUTE format('GRANT SELECT ON TABLE %I TO %I', "
        f"'watchlist_entries', '{app_role}');\n"
        f"    EXECUTE format("
        f"'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE %I FROM %I', "
        f"'watchlist_entries', '{app_role}');\n"
        "\n"
        "    -- SELECT, INSERT for loader_role (immutable, append-only)\n"
        f"    EXECUTE format('GRANT SELECT, INSERT ON TABLE %I TO %I', "
        f"'watchlist_entries', '{loader_role}');\n"
        f"    EXECUTE format("
        f"'REVOKE UPDATE, DELETE, TRUNCATE ON TABLE %I FROM %I', "
        f"'watchlist_entries', '{loader_role}');\n"
        "END $$;\n"
    )
    op.execute(grant_script)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_watchlist_entries_name_version",
        table_name="watchlist_entries",
    )
    op.execute("DROP TABLE IF EXISTS watchlist_entries CASCADE;")
