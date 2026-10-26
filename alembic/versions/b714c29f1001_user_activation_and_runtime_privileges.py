"""User deactivation and read-only runtime identity permissions."""

import os

import sqlalchemy as sa

from alembic import op

revision = "b714c29f1001"
down_revision = "e82f1b4a9c3d"
branch_labels = None
depends_on = None


def _role() -> str:
    role = os.environ.get("APP_DB_USER", "meridian_app")
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
    ).scalar()
    if not exists:
        raise RuntimeError("Application database role does not exist.")
    return str(bind.dialect.identifier_preparer.quote_identifier(role))


def upgrade() -> None:
    role = _role()
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON users FROM {role}")


def downgrade() -> None:
    role = _role()
    op.execute(f"GRANT INSERT, UPDATE ON users TO {role}")
    op.drop_column("users", "is_active")
