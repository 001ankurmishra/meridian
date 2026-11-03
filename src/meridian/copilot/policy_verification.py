"""Policy chunk provenance verification for Project Meridian Copilot EvidencePackage.

Provides deterministic verification of policy chunks against the canonical M1 registry:
- Verifies document identity, version, synthetic flag, and public approval.
- Verifies chunk index bounds.
- Recomputes and verifies SHA-256 chunk hash using canonical byte framing.
- Reads policy chunk data from PostgreSQL connection or in-memory records.
- Computes canonical registry digest for package_hash binding.
- Zero ML / tokenizer / PyTorch dependencies at runtime.
- Fails closed on any mismatch, corruption, or missing data.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from meridian.registry.generator import (
    load_canonical_registry,
    serialize_registry_json,
)
from meridian.registry.hashing import compute_chunk_hash


class PolicyVerificationReason(str, Enum):
    """Deterministic failure codes for policy chunk verification."""

    UNREGISTERED_DOCUMENT = "UNREGISTERED_DOCUMENT"
    NOT_APPROVED = "NOT_APPROVED"
    PROVENANCE_MISMATCH = "PROVENANCE_MISMATCH"
    CHUNK_INDEX_OUT_OF_BOUNDS = "CHUNK_INDEX_OUT_OF_BOUNDS"
    CHUNK_HASH_MISMATCH = "CHUNK_HASH_MISMATCH"
    MISSING_CHUNK_RECORD = "MISSING_CHUNK_RECORD"
    REGISTRY_INVALID = "REGISTRY_INVALID"


@dataclass(frozen=True)
class PolicyChunkRecord:
    """Record representing a policy chunk from the database or test fixture."""

    chunk_id: UUID
    chunk_index: int
    chunk_text: str
    title: str
    document_type: str
    version: str
    source_url_or_ref: str | None
    is_synthetic: bool


@dataclass(frozen=True)
class VerifiedPolicyChunk:
    """A successfully verified policy chunk with provenance metadata."""

    chunk_id: UUID
    evidence_id: UUID
    chunk_index: int
    chunk_text: str
    chunk_hash: str
    title: str
    document_type: str
    version: str
    source_url_or_ref: str | None
    is_synthetic: bool
    doc_hash: str
    registry_version: str
    registry_hash: str


@dataclass(frozen=True)
class PolicyVerificationOutcome:
    """Outcome of verifying a policy chunk against the approval registry."""

    is_valid: bool
    reason: PolicyVerificationReason | None = None
    message: str | None = None
    chunk_hash: str | None = None
    doc_hash: str | None = None
    registry_version: str | None = None
    registry_hash: str | None = None


def compute_registry_content_hash(registry: dict[str, Any]) -> str:
    """Computes SHA-256 digest of the canonical JSON serialization of registry."""
    serialized = serialize_registry_json(registry)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def verify_policy_chunk(
    chunk: PolicyChunkRecord,
    registry: dict[str, Any] | None = None,
) -> PolicyVerificationOutcome:
    """Verifies a single policy chunk against the canonical source-approval registry.

    Fails closed: returns is_valid=False with a specific reason code on any failure.
    """
    if registry is None:
        try:
            registry = load_canonical_registry()
        except Exception as e:
            return PolicyVerificationOutcome(
                is_valid=False,
                reason=PolicyVerificationReason.REGISTRY_INVALID,
                message=f"Failed to load canonical registry: {e}",
            )

    reg_version = registry.get("registry_version")
    if not isinstance(reg_version, str) or not reg_version:
        return PolicyVerificationOutcome(
            is_valid=False,
            reason=PolicyVerificationReason.REGISTRY_INVALID,
            message="Registry missing valid registry_version",
        )

    reg_hash = compute_registry_content_hash(registry)
    documents = registry.get("documents")
    if not isinstance(documents, list):
        return PolicyVerificationOutcome(
            is_valid=False,
            reason=PolicyVerificationReason.REGISTRY_INVALID,
            message="Registry missing documents list",
        )

    # 1. Resolve document identity: (title, document_type, version, source_url_or_ref)
    target_ident = (
        chunk.title,
        chunk.document_type,
        chunk.version,
        chunk.source_url_or_ref,
    )
    reg_doc = None
    for d in documents:
        if not isinstance(d, dict):
            continue
        ident = (
            d.get("title"),
            d.get("document_type"),
            d.get("version"),
            d.get("source_url_or_ref"),
        )
        if ident == target_ident:
            reg_doc = d
            break

    if reg_doc is None:
        return PolicyVerificationOutcome(
            is_valid=False,
            reason=PolicyVerificationReason.UNREGISTERED_DOCUMENT,
            message="Document identity not found in registry",
            registry_version=reg_version,
            registry_hash=reg_hash,
        )

    # 2. Check public approval
    if not reg_doc.get("approved_for_public_deployment", False):
        return PolicyVerificationOutcome(
            is_valid=False,
            reason=PolicyVerificationReason.NOT_APPROVED,
            message="Document not approved for public deployment",
            registry_version=reg_version,
            registry_hash=reg_hash,
        )

    # 3. Check synthetic flag & provenance
    if bool(chunk.is_synthetic) != bool(reg_doc.get("is_synthetic")):
        return PolicyVerificationOutcome(
            is_valid=False,
            reason=PolicyVerificationReason.PROVENANCE_MISMATCH,
            message="Synthetic provenance flag mismatch",
            registry_version=reg_version,
            registry_hash=reg_hash,
        )
    if not chunk.is_synthetic:
        # Release-1 corpus must be synthetic
        return PolicyVerificationOutcome(
            is_valid=False,
            reason=PolicyVerificationReason.PROVENANCE_MISMATCH,
            message="Non-synthetic document in release-1 registry",
            registry_version=reg_version,
            registry_hash=reg_hash,
        )

    # 4. Check chunk index bounds
    chunk_count = reg_doc.get("chunk_count")
    if (
        isinstance(chunk.chunk_index, bool)
        or not isinstance(chunk.chunk_index, int)
        or chunk.chunk_index < 0
        or chunk_count is None
        or chunk.chunk_index >= chunk_count
    ):
        return PolicyVerificationOutcome(
            is_valid=False,
            reason=PolicyVerificationReason.CHUNK_INDEX_OUT_OF_BOUNDS,
            message="Chunk index out of bounds",
            registry_version=reg_version,
            registry_hash=reg_hash,
        )

    chunk_hashes = reg_doc.get("chunk_hashes")
    if not isinstance(chunk_hashes, list) or len(chunk_hashes) != chunk_count:
        return PolicyVerificationOutcome(
            is_valid=False,
            reason=PolicyVerificationReason.REGISTRY_INVALID,
            message="Registry chunk_hashes malformed or count mismatch",
            registry_version=reg_version,
            registry_hash=reg_hash,
        )

    # 5. Recompute chunk hash and compare
    try:
        computed_hash = compute_chunk_hash(chunk.chunk_index, chunk.chunk_text)
    except Exception as e:
        return PolicyVerificationOutcome(
            is_valid=False,
            reason=PolicyVerificationReason.CHUNK_HASH_MISMATCH,
            message=f"Failed to compute chunk hash: {e}",
            registry_version=reg_version,
            registry_hash=reg_hash,
        )

    expected_hash = chunk_hashes[chunk.chunk_index]
    if computed_hash != expected_hash:
        return PolicyVerificationOutcome(
            is_valid=False,
            reason=PolicyVerificationReason.CHUNK_HASH_MISMATCH,
            message="Computed chunk hash does not match registry",
            chunk_hash=computed_hash,
            doc_hash=reg_doc.get("doc_hash"),
            registry_version=reg_version,
            registry_hash=reg_hash,
        )

    return PolicyVerificationOutcome(
        is_valid=True,
        chunk_hash=computed_hash,
        doc_hash=reg_doc.get("doc_hash"),
        registry_version=reg_version,
        registry_hash=reg_hash,
    )


def load_policy_chunks_from_db(
    conn: Connection,
    chunk_ids: Sequence[UUID],
) -> dict[UUID, PolicyChunkRecord]:
    """Loads policy chunks and their parent document metadata from PostgreSQL."""
    if not chunk_ids:
        return {}

    query = text(
        """
        SELECT
            c.chunk_id,
            c.chunk_index,
            c.chunk_text,
            d.title,
            d.document_type,
            d.version,
            d.source_url_or_ref,
            d.is_synthetic
        FROM document_chunks c
        JOIN documents d ON c.document_id = d.document_id
        WHERE c.chunk_id = ANY(:chunk_ids)
        """
    )
    rows = conn.execute(query, {"chunk_ids": list(chunk_ids)}).fetchall()

    records: dict[UUID, PolicyChunkRecord] = {}
    for r in rows:
        cid = r.chunk_id if isinstance(r.chunk_id, UUID) else UUID(str(r.chunk_id))
        records[cid] = PolicyChunkRecord(
            chunk_id=cid,
            chunk_index=r.chunk_index,
            chunk_text=r.chunk_text,
            title=r.title,
            document_type=r.document_type,
            version=r.version,
            source_url_or_ref=r.source_url_or_ref,
            is_synthetic=bool(r.is_synthetic),
        )
    return records
