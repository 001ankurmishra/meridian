"""Read-only PostgreSQL verifier for Project Meridian source approval.

Verifies database documents and document_chunks against the canonical approval registry.
- Strict read-only REPEATABLE READ transaction.
- Zero dependency on tokenizers or embedding models at runtime.
- Deterministic error precedence and bounded non-sensitive reason codes.
- Fails closed.
"""

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, text

from meridian.registry.generator import load_canonical_registry
from meridian.registry.hashing import (
    compute_chunk_digest,
    compute_chunk_hash,
    compute_doc_hash,
)


class VerificationReason(str, Enum):
    """Deterministic failure codes for policy verification."""

    REGISTRY_INVALID = "REGISTRY_INVALID"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    UNREGISTERED_DOCUMENT = "UNREGISTERED_DOCUMENT"
    MISSING_DOCUMENT = "MISSING_DOCUMENT"
    NOT_APPROVED = "NOT_APPROVED"
    PROVENANCE_MISMATCH = "PROVENANCE_MISMATCH"
    CHUNK_SET_MISMATCH = "CHUNK_SET_MISMATCH"
    CHUNK_HASH_MISMATCH = "CHUNK_HASH_MISMATCH"
    DOC_HASH_MISMATCH = "DOC_HASH_MISMATCH"


@dataclass(frozen=True)
class VerificationResult:
    """Bounded verification outcome."""

    is_valid: bool
    reason_code: VerificationReason | None = None
    message: str | None = None


def _is_hex64(val: Any) -> bool:
    """Checks if val is a 64-character lowercase hexadecimal string."""
    if not isinstance(val, str) or len(val) != 64:
        return False
    hex_chars = set("0123456789abcdef")
    return all(c in hex_chars for c in val)


def _validate_registry_structure(
    registry_data: Any,
) -> tuple[
    bool,
    VerificationReason | None,
    str | None,
    dict[tuple[str, str, str, str | None], dict[str, Any]] | None,
]:
    """Validates the in-memory registry structure and detects duplicate identities.

    Returns:
        (is_valid, reason_code, message, identity_map)
    """
    if not isinstance(registry_data, dict):
        return (
            False,
            VerificationReason.REGISTRY_INVALID,
            "Registry must be a JSON object",
            None,
        )

    # Check top-level required fields
    if not isinstance(registry_data.get("registry_version"), str):
        return (
            False,
            VerificationReason.REGISTRY_INVALID,
            "Missing or invalid registry_version",
            None,
        )
    if not isinstance(registry_data.get("hash_algorithm"), str):
        return (
            False,
            VerificationReason.REGISTRY_INVALID,
            "Missing or invalid hash_algorithm",
            None,
        )

    documents = registry_data.get("documents")
    if not isinstance(documents, list) or len(documents) == 0:
        return (
            False,
            VerificationReason.REGISTRY_INVALID,
            "Missing or empty documents list",
            None,
        )

    identity_map: dict[tuple[str, str, str, str | None], dict[str, Any]] = {}

    for doc in documents:
        if not isinstance(doc, dict):
            return (
                False,
                VerificationReason.REGISTRY_INVALID,
                "Document entry must be an object",
                None,
            )

        title = doc.get("title")
        doc_type = doc.get("document_type")
        version = doc.get("version")
        source_url_or_ref = doc.get("source_url_or_ref")
        approved = doc.get("approved_for_public_deployment")
        is_synthetic = doc.get("is_synthetic")
        chunk_count = doc.get("chunk_count")
        chunk_hashes = doc.get("chunk_hashes")
        doc_hash_val = doc.get("doc_hash")
        source_text_sha256 = doc.get("source_text_sha256")

        if not isinstance(title, str) or not title.strip():
            return (
                False,
                VerificationReason.REGISTRY_INVALID,
                "Missing or invalid document title",
                None,
            )
        if not isinstance(doc_type, str) or not doc_type.strip():
            return (
                False,
                VerificationReason.REGISTRY_INVALID,
                "Missing or invalid document_type",
                None,
            )
        if not isinstance(version, str) or not version.strip():
            return (
                False,
                VerificationReason.REGISTRY_INVALID,
                "Missing or invalid version",
                None,
            )
        if source_url_or_ref is not None and not isinstance(source_url_or_ref, str):
            return (
                False,
                VerificationReason.REGISTRY_INVALID,
                "Invalid source_url_or_ref",
                None,
            )
        if not isinstance(approved, bool):
            return (
                False,
                VerificationReason.REGISTRY_INVALID,
                "Missing or invalid approved_for_public_deployment",
                None,
            )
        if not isinstance(is_synthetic, bool):
            return (
                False,
                VerificationReason.REGISTRY_INVALID,
                "Missing or invalid is_synthetic",
                None,
            )
        if (
            isinstance(chunk_count, bool)
            or not isinstance(chunk_count, int)
            or chunk_count < 1
        ):
            return (
                False,
                VerificationReason.REGISTRY_INVALID,
                "Invalid chunk_count",
                None,
            )
        if not isinstance(chunk_hashes, list) or len(chunk_hashes) != chunk_count:
            return (
                False,
                VerificationReason.REGISTRY_INVALID,
                "chunk_hashes count mismatch",
                None,
            )
        if not all(_is_hex64(h) for h in chunk_hashes):
            return (
                False,
                VerificationReason.REGISTRY_INVALID,
                "Malformed chunk hash digest",
                None,
            )
        if not _is_hex64(doc_hash_val):
            return (
                False,
                VerificationReason.REGISTRY_INVALID,
                "Malformed doc_hash digest",
                None,
            )
        if source_text_sha256 is not None and not _is_hex64(source_text_sha256):
            return (
                False,
                VerificationReason.REGISTRY_INVALID,
                "Malformed source_text_sha256 digest",
                None,
            )

        # Logical identity: (title, document_type, version, source_url_or_ref)
        identity = (title, doc_type, version, source_url_or_ref)
        if identity in identity_map:
            return (
                False,
                VerificationReason.DUPLICATE_IDENTITY,
                "Duplicate document identity in registry",
                None,
            )
        identity_map[identity] = doc

    return True, None, None, identity_map


def _verify_with_connection(
    conn: Connection,
    registry_data: dict[str, Any],
) -> VerificationResult:
    """Executes the 9-step verification sequence against a database connection."""
    # Step 1: Validate registry structure and duplicate identities
    is_valid, reason, msg, identity_map = _validate_registry_structure(registry_data)
    if not is_valid:
        return VerificationResult(is_valid=False, reason_code=reason, message=msg)
    assert identity_map is not None

    # Enforce read-only REPEATABLE READ transaction
    conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))

    # Step 2: Query database documents and detect duplicate document identities
    db_docs_query = text(
        "SELECT document_id, title, document_type, version, "
        "source_url_or_ref, is_synthetic "
        "FROM documents "
        "ORDER BY title ASC, document_type ASC, version ASC, "
        "source_url_or_ref ASC NULLS FIRST, document_id ASC"
    )
    db_docs = conn.execute(db_docs_query).fetchall()

    db_identities: list[tuple[str, str, str, str | None]] = [
        (row.title, row.document_type, row.version, row.source_url_or_ref)
        for row in db_docs
    ]
    counts = Counter(db_identities)
    for ident, count in counts.items():
        if count > 1:
            return VerificationResult(
                is_valid=False,
                reason_code=VerificationReason.DUPLICATE_IDENTITY,
                message="Duplicate document identity in database",
            )

    db_identity_map = {ident: row for ident, row in zip(db_identities, db_docs)}

    # Step 3: Require every database document to match exactly one registry entry
    for ident in db_identities:
        if ident not in identity_map:
            return VerificationResult(
                is_valid=False,
                reason_code=VerificationReason.UNREGISTERED_DOCUMENT,
                message="Database contains unregistered document",
            )

    # Step 4: Require every registry entry to match exactly one database document
    for ident in identity_map:
        if ident not in db_identity_map:
            return VerificationResult(
                is_valid=False,
                reason_code=VerificationReason.MISSING_DOCUMENT,
                message="Registered document missing from database",
            )

    # Step 5: Reject registry entries that are not approved for public deployment
    for ident, reg_entry in identity_map.items():
        if not reg_entry.get("approved_for_public_deployment", False):
            return VerificationResult(
                is_valid=False,
                reason_code=VerificationReason.NOT_APPROVED,
                message="Document not approved for public deployment",
            )

    # Step 6: Verify the is_synthetic flag and provenance metadata
    for ident, reg_entry in identity_map.items():
        db_row = db_identity_map[ident]
        if bool(db_row.is_synthetic) != bool(reg_entry["is_synthetic"]):
            return VerificationResult(
                is_valid=False,
                reason_code=VerificationReason.PROVENANCE_MISMATCH,
                message="Document provenance synthetic flag mismatch",
            )
        # Release-1 documents must be synthetic
        if not db_row.is_synthetic:
            return VerificationResult(
                is_valid=False,
                reason_code=VerificationReason.PROVENANCE_MISMATCH,
                message="Non-synthetic document detected in release-1 corpus",
            )

    # Steps 7, 8, 9: Verify chunk set, chunk hashes, and doc hash for each document
    for ident, reg_entry in identity_map.items():
        db_row = db_identity_map[ident]
        chunks_query = text(
            "SELECT chunk_id, chunk_index, chunk_text "
            "FROM document_chunks "
            "WHERE document_id = :doc_id "
            "ORDER BY chunk_index ASC, chunk_id ASC"
        )
        chunks = conn.execute(chunks_query, {"doc_id": db_row.document_id}).fetchall()

        # Step 7: Verify chunk indexes are exactly 0..n-1
        # with no duplicates, gaps, extras
        expected_chunk_count = reg_entry["chunk_count"]
        if len(chunks) != expected_chunk_count:
            return VerificationResult(
                is_valid=False,
                reason_code=VerificationReason.CHUNK_SET_MISMATCH,
                message="Document chunk count mismatch",
            )

        indices = [c.chunk_index for c in chunks]
        if indices != list(range(expected_chunk_count)):
            return VerificationResult(
                is_valid=False,
                reason_code=VerificationReason.CHUNK_SET_MISMATCH,
                message="Document chunk indices mismatch",
            )

        # Step 8: Recompute and verify every chunk hash
        raw_digests: list[bytes] = []
        for idx, c in enumerate(chunks):
            computed_hash = compute_chunk_hash(c.chunk_index, c.chunk_text)
            expected_hash = reg_entry["chunk_hashes"][idx]
            if computed_hash != expected_hash:
                return VerificationResult(
                    is_valid=False,
                    reason_code=VerificationReason.CHUNK_HASH_MISMATCH,
                    message="Document chunk content hash mismatch",
                )
            raw_digests.append(compute_chunk_digest(c.chunk_index, c.chunk_text))

        # Step 9: Recompute and verify document hash
        computed_doc_hash = compute_doc_hash(
            title=reg_entry["title"],
            document_type=reg_entry["document_type"],
            version=reg_entry["version"],
            source_url_or_ref=reg_entry["source_url_or_ref"],
            is_synthetic=reg_entry["is_synthetic"],
            raw_chunk_digests=raw_digests,
        )
        if computed_doc_hash != reg_entry["doc_hash"]:
            return VerificationResult(
                is_valid=False,
                reason_code=VerificationReason.DOC_HASH_MISMATCH,
                message="Document composite hash mismatch",
            )

    return VerificationResult(
        is_valid=True,
        reason_code=None,
        message="Policy database verified successfully against registry",
    )


def verify_policy_database(
    target: Engine | Connection,
    registry: dict[str, Any] | Path | str | None = None,
) -> VerificationResult:
    """Verifies database documents and chunks against the source-approval registry.

    Fails closed. Uses a single REPEATABLE READ read-only transaction.
    Does not modify database state or registry.
    """
    # Load registry if needed
    if registry is None:
        try:
            registry_data = load_canonical_registry()
        except Exception:
            return VerificationResult(
                is_valid=False,
                reason_code=VerificationReason.REGISTRY_INVALID,
                message="Failed to load canonical registry file",
            )
    elif isinstance(registry, (str, Path)):
        try:
            registry_data = load_canonical_registry(registry)
        except Exception:
            return VerificationResult(
                is_valid=False,
                reason_code=VerificationReason.REGISTRY_INVALID,
                message="Failed to read specified registry file",
            )
    elif isinstance(registry, dict):
        registry_data = registry
    else:
        return VerificationResult(
            is_valid=False,
            reason_code=VerificationReason.REGISTRY_INVALID,
            message="Registry must be dict, Path, or None",
        )

    # Perform verification inside repeatable read, read only transaction
    if isinstance(target, Engine):
        with target.connect() as conn:
            with conn.begin():
                return _verify_with_connection(conn, registry_data)
    elif isinstance(target, Connection):
        # Already inside a connection, wrap in begin if not inside a transaction
        if not target.in_transaction():
            with target.begin():
                return _verify_with_connection(target, registry_data)
        else:
            return _verify_with_connection(target, registry_data)
    else:
        raise TypeError(
            f"Target must be Engine or Connection, got {type(target).__name__}"
        )
