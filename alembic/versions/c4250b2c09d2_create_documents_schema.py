"""create_documents_schema

Revision ID: c4250b2c09d2
Revises: 9e0a162b295b
Create Date: 2026-09-11 00:12:53.986940

"""
import os
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    # Fallback if pgvector is not installed yet
    class Vector(sa.types.UserDefinedType):
        def __init__(self, dim):
            self.dim = dim
        def get_col_spec(self):
            if self.dim is None:
                return "VECTOR"
            return f"VECTOR({self.dim})"


# revision identifiers, used by Alembic.
revision: str = 'c4250b2c09d2'
down_revision: Union[str, Sequence[str], None] = '9e0a162b295b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    app_role = os.environ.get("APP_DB_USER", "meridian_app")
    loader_role = os.environ.get("LOADER_DB_USER", "meridian_loader")

    # Create documents table
    op.create_table(
        "documents",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("source_url_or_ref", sa.Text(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("document_id"),
        sa.CheckConstraint(
            "document_type IN ('internal_policy', 'regulatory_guidance')",
            name="chk_documents_type",
        ),
    )

    # Create document_chunks table
    op.create_table(
        "document_chunks",
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.document_id"]),
        sa.PrimaryKeyConstraint("chunk_id"),
    )

    # Grants
    grant_script = (
        "DO $$\n"
        "BEGIN\n"
        "    -- SELECT ONLY for app_role\n"
        "    EXECUTE format('GRANT SELECT ON TABLE %I TO %I', "
        f"'documents', '{app_role}');\n"
        "    EXECUTE format('GRANT SELECT ON TABLE %I TO %I', "
        f"'document_chunks', '{app_role}');\n"
        "\n"
        "    -- SELECT, INSERT for loader_role\n"
        "    EXECUTE format('GRANT SELECT, INSERT ON TABLE %I TO %I', "
        f"'documents', '{loader_role}');\n"
        "    EXECUTE format('GRANT SELECT, INSERT ON TABLE %I TO %I', "
        f"'document_chunks', '{loader_role}');\n"
        "END $$;\n"
    )
    op.execute(grant_script)


def downgrade() -> None:
    app_role = os.environ.get("APP_DB_USER", "meridian_app")
    loader_role = os.environ.get("LOADER_DB_USER", "meridian_loader")

    revoke_script = (
        "DO $$\n"
        "BEGIN\n"
        "    EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I FROM %I', "
        f"'documents', '{app_role}');\n"
        "    EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I FROM %I', "
        f"'document_chunks', '{app_role}');\n"
        "    EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I FROM %I', "
        f"'documents', '{loader_role}');\n"
        "    EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I FROM %I', "
        f"'document_chunks', '{loader_role}');\n"
        "END $$;\n"
    )
    op.execute(revoke_script)
    op.drop_table("document_chunks")
    op.drop_table("documents")
