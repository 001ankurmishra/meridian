# ruff: noqa: E501
"""Integration tests for the read-only PostgreSQL policy approval database verifier.

Tests:
- Positive control: ingest real synthetic policy corpus and verify successfully.
- Chunk modifications: 1-character, case, whitespace changes are rejected (CHUNK_HASH_MISMATCH).
- Chunk set anomalies: extra chunk, missing chunk, duplicate index, incorrect index (CHUNK_SET_MISMATCH).
- Duplicate database document identity (DUPLICATE_IDENTITY).
- Unregistered document in database (UNREGISTERED_DOCUMENT).
- Altered title, version, source reference (UNREGISTERED_DOCUMENT).
- Altered synthetic flag (PROVENANCE_MISMATCH).
- Missing document in database (MISSING_DOCUMENT).
- Document not approved for deployment (NOT_APPROVED).
- Registry structure/duplicate invalidity (REGISTRY_INVALID, DUPLICATE_IDENTITY).
- Error precedence verification.
- Database state immutability (verifier leaves all rows unchanged).
- Bounded, sanitized reason messages (no document titles, policy text, tokens, credentials).
"""

import uuid
from copy import deepcopy
from typing import Generator

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, text

from meridian.loader.policy_corpus import POLICY_CORPUS_V1
from meridian.loader.policy_ingest import ingest_policy_corpus
from meridian.registry.generator import load_canonical_registry
from meridian.registry.verifier import (
    VerificationReason,
    verify_policy_database,
)


@pytest.fixture
def clean_policy_tables(superuser_engine: Engine) -> Generator[None, None, None]:
    """Cleans policy tables before and after each test."""
    with superuser_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE document_chunks, documents CASCADE"))
    yield
    with superuser_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE document_chunks, documents CASCADE"))


@pytest.fixture
def populated_corpus(
    clean_policy_tables: None, loader_role_engine: Engine
) -> Generator[None, None, None]:
    """Populates the database with the real 4-document synthetic corpus."""
    docs_inserted, chunks_inserted = ingest_policy_corpus(
        loader_role_engine, POLICY_CORPUS_V1
    )
    assert docs_inserted == 4
    assert chunks_inserted == 10
    yield


class TestVerifierPositiveControlAndImmutability:
    """Positive control and read-only non-mutation guarantees."""

    def test_positive_control_verification(
        self, populated_corpus: None, app_role_engine: Engine
    ) -> None:
        result = verify_policy_database(app_role_engine)
        assert result.is_valid is True
        assert result.reason_code is None
        assert (
            result.message == "Policy database verified successfully against registry"
        )

    def test_database_rows_unchanged_by_verifier(
        self, populated_corpus: None, app_role_engine: Engine, superuser_engine: Engine
    ) -> None:
        with superuser_engine.connect() as conn:
            docs_before = conn.execute(
                text(
                    "SELECT document_id, title, version, is_synthetic FROM documents ORDER BY document_id"
                )
            ).fetchall()
            chunks_before = conn.execute(
                text(
                    "SELECT chunk_id, document_id, chunk_index, chunk_text FROM document_chunks ORDER BY chunk_id"
                )
            ).fetchall()

        # Run verification
        result = verify_policy_database(app_role_engine)
        assert result.is_valid is True

        with superuser_engine.connect() as conn:
            docs_after = conn.execute(
                text(
                    "SELECT document_id, title, version, is_synthetic FROM documents ORDER BY document_id"
                )
            ).fetchall()
            chunks_after = conn.execute(
                text(
                    "SELECT chunk_id, document_id, chunk_index, chunk_text FROM document_chunks ORDER BY chunk_id"
                )
            ).fetchall()

        assert docs_before == docs_after
        assert chunks_before == chunks_after


class TestChunkHashVerification:
    """Verifies that any content modification to chunk text is rejected."""

    def test_rejects_single_character_change(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            # Change one character in the first chunk
            row = conn.execute(
                text("SELECT chunk_id, chunk_text FROM document_chunks LIMIT 1")
            ).fetchone()
            assert row is not None
            modified_text = row.chunk_text[:-1] + (
                "X" if row.chunk_text[-1] != "X" else "Y"
            )
            conn.execute(
                text(
                    "UPDATE document_chunks SET chunk_text = :t WHERE chunk_id = :cid"
                ),
                {"t": modified_text, "cid": row.chunk_id},
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.CHUNK_HASH_MISMATCH

    def test_rejects_case_change(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            row = conn.execute(
                text("SELECT chunk_id, chunk_text FROM document_chunks LIMIT 1")
            ).fetchone()
            assert row is not None
            # Invert case of the first letter
            first_char = row.chunk_text[0]
            flipped = first_char.lower() if first_char.isupper() else first_char.upper()
            modified = flipped + row.chunk_text[1:]
            conn.execute(
                text(
                    "UPDATE document_chunks SET chunk_text = :t WHERE chunk_id = :cid"
                ),
                {"t": modified, "cid": row.chunk_id},
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.CHUNK_HASH_MISMATCH

    def test_rejects_trailing_whitespace(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            row = conn.execute(
                text("SELECT chunk_id, chunk_text FROM document_chunks LIMIT 1")
            ).fetchone()
            assert row is not None
            conn.execute(
                text(
                    "UPDATE document_chunks SET chunk_text = :t WHERE chunk_id = :cid"
                ),
                {"t": row.chunk_text + " ", "cid": row.chunk_id},
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.CHUNK_HASH_MISMATCH


class TestChunkSetVerification:
    """Verifies chunk counts, indices, missing, extra, and duplicate chunks."""

    def test_rejects_extra_chunk(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            # Pick a doc and insert an extra chunk with index 2
            doc = conn.execute(
                text(
                    "SELECT document_id FROM documents WHERE title LIKE '%Large / unusual%'"
                )
            ).fetchone()
            assert doc is not None
            conn.execute(
                text(
                    "INSERT INTO document_chunks (chunk_id, document_id, chunk_text, chunk_index) "
                    "VALUES (:cid, :doc_id, 'Extra chunk text', 2)"
                ),
                {"cid": str(uuid.uuid4()), "doc_id": doc.document_id},
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.CHUNK_SET_MISMATCH

    def test_rejects_missing_chunk(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            doc = conn.execute(
                text(
                    "SELECT document_id FROM documents WHERE title LIKE '%Large / unusual%'"
                )
            ).fetchone()
            assert doc is not None
            conn.execute(
                text(
                    "DELETE FROM document_chunks WHERE document_id = :doc_id AND chunk_index = 1"
                ),
                {"doc_id": doc.document_id},
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.CHUNK_SET_MISMATCH

    def test_rejects_duplicate_chunk_index(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            doc = conn.execute(
                text(
                    "SELECT document_id FROM documents WHERE title LIKE '%Large / unusual%'"
                )
            ).fetchone()
            assert doc is not None
            conn.execute(
                text(
                    "INSERT INTO document_chunks (chunk_id, document_id, chunk_text, chunk_index) "
                    "VALUES (:cid, :doc_id, 'Duplicate index chunk', 0)"
                ),
                {"cid": str(uuid.uuid4()), "doc_id": doc.document_id},
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.CHUNK_SET_MISMATCH

    def test_rejects_non_zero_start_index(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            doc = conn.execute(
                text(
                    "SELECT document_id FROM documents WHERE title LIKE '%Large / unusual%'"
                )
            ).fetchone()
            assert doc is not None
            conn.execute(
                text(
                    "UPDATE document_chunks SET chunk_index = chunk_index + 1 WHERE document_id = :doc_id"
                ),
                {"doc_id": doc.document_id},
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.CHUNK_SET_MISMATCH


class TestIdentityAndProvenanceVerification:
    """Verifies duplicate identities, unregistered documents, missing entries, and flags."""

    def test_rejects_duplicate_document_identity_in_database(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            doc = conn.execute(text("SELECT * FROM documents LIMIT 1")).fetchone()
            assert doc is not None
            conn.execute(
                text(
                    "INSERT INTO documents (document_id, title, document_type, version, source_url_or_ref, is_synthetic) "
                    "VALUES (:did, :title, :document_type, :version, :source_url_or_ref, :is_synthetic)"
                ),
                {
                    "did": str(uuid.uuid4()),
                    "title": doc.title,
                    "document_type": doc.document_type,
                    "version": doc.version,
                    "source_url_or_ref": doc.source_url_or_ref,
                    "is_synthetic": doc.is_synthetic,
                },
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.DUPLICATE_IDENTITY

    def test_rejects_unregistered_document(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO documents (document_id, title, document_type, version, source_url_or_ref, is_synthetic) "
                    "VALUES (:did, 'Unapproved Policy X', 'internal_policy', 'v1', 'meridian-test', true)"
                ),
                {"did": str(uuid.uuid4())},
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.UNREGISTERED_DOCUMENT

    def test_altered_title_yields_unregistered_document(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE documents SET title = title || ' [MODIFIED]' WHERE title LIKE '%Large / unusual%'"
                )
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        # Precedence: UNREGISTERED_DOCUMENT precedes MISSING_DOCUMENT
        assert res.reason_code == VerificationReason.UNREGISTERED_DOCUMENT

    def test_altered_version_yields_unregistered_document(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE documents SET version = 'v2' WHERE title LIKE '%Large / unusual%'"
                )
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.UNREGISTERED_DOCUMENT

    def test_altered_source_url_or_ref_yields_unregistered_document(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE documents SET source_url_or_ref = 'altered-ref' WHERE title LIKE '%Large / unusual%'"
                )
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.UNREGISTERED_DOCUMENT

    def test_altered_synthetic_flag_yields_provenance_mismatch(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE documents SET is_synthetic = false WHERE title LIKE '%Large / unusual%'"
                )
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.PROVENANCE_MISMATCH

    def test_missing_document_in_database(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            doc = conn.execute(
                text(
                    "SELECT document_id FROM documents WHERE title LIKE '%Large / unusual%'"
                )
            ).fetchone()
            assert doc is not None
            conn.execute(
                text("DELETE FROM document_chunks WHERE document_id = :did"),
                {"did": doc.document_id},
            )
            conn.execute(
                text("DELETE FROM documents WHERE document_id = :did"),
                {"did": doc.document_id},
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.MISSING_DOCUMENT


class TestRegistryValidationAndPrecedence:
    """Verifies registry validation, approval flags, error precedence, and sanitization."""

    def test_rejects_unapproved_document(
        self, populated_corpus: None, app_role_engine: Engine
    ) -> None:
        reg = deepcopy(load_canonical_registry())
        reg["documents"][0]["approved_for_public_deployment"] = False

        res = verify_policy_database(app_role_engine, registry=reg)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.NOT_APPROVED

    def test_rejects_invalid_registry_structure(
        self, populated_corpus: None, app_role_engine: Engine
    ) -> None:
        res = verify_policy_database(app_role_engine, registry={"broken": True})
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.REGISTRY_INVALID

    def test_rejects_duplicate_identity_in_registry(
        self, populated_corpus: None, app_role_engine: Engine
    ) -> None:
        reg = deepcopy(load_canonical_registry())
        reg["documents"].append(deepcopy(reg["documents"][0]))

        res = verify_policy_database(app_role_engine, registry=reg)
        assert res.is_valid is False
        assert res.reason_code == VerificationReason.DUPLICATE_IDENTITY

    def test_error_precedence_duplicate_identity_over_unregistered(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        with superuser_engine.begin() as conn:
            # 1. Add duplicate identity
            doc = conn.execute(text("SELECT * FROM documents LIMIT 1")).fetchone()
            assert doc is not None
            conn.execute(
                text(
                    "INSERT INTO documents (document_id, title, document_type, version, source_url_or_ref, is_synthetic) "
                    "VALUES (:did, :title, :document_type, :version, :source_url_or_ref, :is_synthetic)"
                ),
                {
                    "did": str(uuid.uuid4()),
                    "title": doc.title,
                    "document_type": doc.document_type,
                    "version": doc.version,
                    "source_url_or_ref": doc.source_url_or_ref,
                    "is_synthetic": doc.is_synthetic,
                },
            )
            # 2. Also add unregistered document
            conn.execute(
                text(
                    "INSERT INTO documents (document_id, title, document_type, version, source_url_or_ref, is_synthetic) "
                    "VALUES (:did, 'Unregistered X', 'internal_policy', 'v1', 'ref', true)"
                ),
                {"did": str(uuid.uuid4())},
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        # DUPLICATE_IDENTITY must take precedence over UNREGISTERED_DOCUMENT
        assert res.reason_code == VerificationReason.DUPLICATE_IDENTITY

    def test_error_precedence_not_approved_over_chunk_hash_mismatch(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        # Corrupt chunk text in DB
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE document_chunks SET chunk_text = 'tampered' WHERE chunk_index = 0"
                )
            )

        # Also mark registry as not approved
        reg = deepcopy(load_canonical_registry())
        reg["documents"][0]["approved_for_public_deployment"] = False

        res = verify_policy_database(app_role_engine, registry=reg)
        assert res.is_valid is False
        # NOT_APPROVED must take precedence over CHUNK_HASH_MISMATCH
        assert res.reason_code == VerificationReason.NOT_APPROVED

    def test_messages_do_not_leak_sensitive_corpus_content(
        self, populated_corpus: None, superuser_engine: Engine, app_role_engine: Engine
    ) -> None:
        # Check all failure messages for information leakage
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE documents SET title = 'CONFIDENTIAL_TITLE' WHERE title LIKE '%Large / unusual%'"
                )
            )

        res = verify_policy_database(app_role_engine)
        assert res.is_valid is False
        assert "CONFIDENTIAL_TITLE" not in (res.message or "")
        assert "Synthetic Internal Policy" not in (res.message or "")
