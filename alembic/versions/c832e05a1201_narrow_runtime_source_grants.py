"""Remove runtime graph writes and alert updates; preserve intake INSERT."""

import os

import sqlalchemy as sa

from alembic import op

revision = "c832e05a1201"
down_revision = "b714c29f1001"
branch_labels = None
depends_on = None


def _role() -> str:
    bind = op.get_bind()
    role = os.environ.get("APP_DB_USER", "meridian_app")
    if not bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname=:r"), {"r": role}
    ).scalar():
        raise RuntimeError("Application database role does not exist.")
    return str(bind.dialect.identifier_preparer.quote_identifier(role))


def upgrade() -> None:
    role = _role()
    op.execute(f"REVOKE INSERT, UPDATE ON entities, graph_relationships FROM {role}")
    op.execute(f"REVOKE UPDATE ON alerts FROM {role}")


def downgrade() -> None:
    role = _role()
    op.execute(f"GRANT INSERT, UPDATE ON entities, graph_relationships TO {role}")
    op.execute(f"GRANT UPDATE ON alerts TO {role}")
