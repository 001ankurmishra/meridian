"""Source-approval registry and verifier for Project Meridian."""

from meridian.registry.generator import (
    CANONICAL_REGISTRY_FILENAME,
    CHUNKER_ALGORITHM,
    HASH_ALGORITHM,
    REGISTRY_VERSION,
    generate_policy_registry,
    get_canonical_registry_path,
    load_canonical_registry,
    serialize_registry_json,
    write_policy_registry,
)
from meridian.registry.hashing import (
    CHUNK_DOMAIN_TAG,
    DOC_DOMAIN_TAG,
    SOURCE_DOMAIN_TAG,
    compute_chunk_digest,
    compute_chunk_hash,
    compute_doc_digest,
    compute_doc_hash,
    compute_source_text_digest,
    compute_source_text_hash,
    encode_bool,
    encode_u32,
    encode_u64,
    frame_optional_string,
    frame_string,
)
from meridian.registry.verifier import (
    VerificationReason,
    VerificationResult,
    verify_policy_database,
)

__all__ = [
    # Hashing and framing
    "encode_u32",
    "encode_u64",
    "frame_string",
    "frame_optional_string",
    "encode_bool",
    "CHUNK_DOMAIN_TAG",
    "DOC_DOMAIN_TAG",
    "SOURCE_DOMAIN_TAG",
    "compute_chunk_digest",
    "compute_chunk_hash",
    "compute_source_text_digest",
    "compute_source_text_hash",
    "compute_doc_digest",
    "compute_doc_hash",
    # Generator
    "REGISTRY_VERSION",
    "HASH_ALGORITHM",
    "CHUNKER_ALGORITHM",
    "CANONICAL_REGISTRY_FILENAME",
    "get_canonical_registry_path",
    "generate_policy_registry",
    "serialize_registry_json",
    "write_policy_registry",
    "load_canonical_registry",
    # Verifier
    "VerificationReason",
    "VerificationResult",
    "verify_policy_database",
]
