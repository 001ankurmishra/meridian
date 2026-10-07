"""Add api_tokens table

Revision ID: f284a67877be
Revises: f37528dfc60b
Create Date: 2026-10-07 02:16:00.426083

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f284a67877be'
down_revision: Union[str, Sequence[str], None] = 'f37528dfc60b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    import os
    app_role = os.environ.get("APP_DB_USER", "meridian_app")
    bind = op.get_bind()

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
        "api_tokens",
        sa.Column("token_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("token_id"),
        sa.UniqueConstraint("token_hash", name="uq_api_tokens_token_hash"),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32", name="ck_api_tokens_hash_length"
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_api_tokens_expires_at_after_created_at"
        ),
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])

    grant_script = (
        "DO $$\n"
        "BEGIN\n"
        "    EXECUTE format('GRANT SELECT ON TABLE %I TO %I', "
        f"'api_tokens', '{app_role}');\n"
        "    EXECUTE format('REVOKE INSERT, UPDATE, DELETE ON TABLE %I FROM %I', "
        f"'api_tokens', '{app_role}');\n"
        "END $$;\n"
    )
    op.execute(grant_script)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE IF EXISTS api_tokens CASCADE;")
