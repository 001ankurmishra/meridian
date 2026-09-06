"""grant_loader_privileges

Revision ID: 9e0a162b295b
Revises: 6a92f1f7c7e8
Create Date: 2026-09-05 19:19:10.589935

"""

import os
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9e0a162b295b"
down_revision: Union[str, None] = "6a92f1f7c7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    loader_role = os.environ.get("LOADER_DB_USER", "meridian_loader")
    bind = op.get_bind()

    # Check if role exists before granting
    result = bind.execute(
        sa.text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :role_name"),
        {"role_name": loader_role},
    ).scalar()
    if not result:
        raise RuntimeError(
            f"Expected loader role '{loader_role}' does not exist; "
            "run the bootstrap init script before applying migrations"
        )

    grant_loader_script = (
        "DO $$\n"
        "BEGIN\n"
        # Granting TRUNCATE even though we don't rely on it due to FK constraints on
        # alerts, as explicitly specified by the architecture decision to maintain
        # strict least-privilege semantics.
        "    EXECUTE format('GRANT SELECT, INSERT, TRUNCATE ON TABLE %I TO %I', "
        f"'customers', '{loader_role}');\n"
        "    EXECUTE format('GRANT SELECT, INSERT, TRUNCATE ON TABLE %I TO %I', "
        f"'accounts', '{loader_role}');\n"
        "    EXECUTE format('GRANT SELECT, INSERT, TRUNCATE ON TABLE %I TO %I', "
        f"'transactions', '{loader_role}');\n"
        "    EXECUTE format('GRANT SELECT, INSERT, TRUNCATE ON TABLE %I TO %I', "
        f"'beneficiaries', '{loader_role}');\n"
        "    EXECUTE format('GRANT SELECT, INSERT, TRUNCATE ON TABLE %I TO %I', "
        f"'entities', '{loader_role}');\n"
        "    EXECUTE format('GRANT SELECT, INSERT, TRUNCATE ON TABLE %I TO %I', "
        f"'graph_relationships', '{loader_role}');\n"
        "END $$;\n"
    )
    op.execute(grant_loader_script)


def downgrade() -> None:
    loader_role = os.environ.get("LOADER_DB_USER", "meridian_loader")
    revoke_script = (
        "DO $$\n"
        "BEGIN\n"
        "    EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I FROM %I', "
        f"'customers', '{loader_role}');\n"
        "    EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I FROM %I', "
        f"'accounts', '{loader_role}');\n"
        "    EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I FROM %I', "
        f"'transactions', '{loader_role}');\n"
        "    EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I FROM %I', "
        f"'beneficiaries', '{loader_role}');\n"
        "    EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I FROM %I', "
        f"'entities', '{loader_role}');\n"
        "    EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I FROM %I', "
        f"'graph_relationships', '{loader_role}');\n"
        "END $$;\n"
    )
    op.execute(revoke_script)
