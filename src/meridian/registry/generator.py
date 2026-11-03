"""Deterministic source-approval registry generator for Project Meridian.

Builds the canonical JSON registry containing the approved synthetic policy documents,
their chunk hashes, doc hashes, chunker provenance, and source text SHA-256 digests.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from meridian.loader.policy_corpus import PolicyDocumentSpec
from meridian.registry.hashing import (
    compute_chunk_digest,
    compute_doc_hash,
    compute_source_text_hash,
)

REGISTRY_VERSION: str = "meridian.policy-registry.v1"
HASH_ALGORITHM: str = "sha256"
CHUNKER_ALGORITHM: str = "meridian.paragraph-chunker.v1"
CANONICAL_REGISTRY_FILENAME: str = "policy_registry_v1.json"


def get_canonical_registry_path() -> Path:
    """Returns the absolute filesystem path to the committed canonical registry."""
    return Path(__file__).resolve().parent / CANONICAL_REGISTRY_FILENAME


def generate_policy_registry(
    corpus: Sequence["PolicyDocumentSpec"] | None = None,
) -> dict[str, Any]:
    """Generates the in-memory policy approval registry from policy document specs.

    Derives all chunks via the canonical chunk_document implementation and records
    pinned chunker parameters, model metadata, and hashes.
    """
    from meridian.agents.policy.chunking import (
        BGE_MODEL_MAX,
        MERIDIAN_SAFETY_CEILING,
        OVERLAP_MAX,
        OVERLAP_MIN,
        TARGET_MAX,
        TARGET_MIN,
        chunk_document,
    )
    from meridian.agents.policy.model_config import MODEL_NAME, MODEL_REVISION
    from meridian.loader.policy_corpus import POLICY_CORPUS_V1

    active_corpus = POLICY_CORPUS_V1 if corpus is None else corpus
    docs_data: list[dict[str, Any]] = []

    for doc in active_corpus:
        if not doc.is_synthetic:
            raise ValueError(
                f"Only synthetic documents permitted in release-1: {doc.title}"
            )

        chunks = chunk_document(doc.text)
        if not chunks:
            raise ValueError(f"Document produced 0 chunks: {doc.title}")

        raw_digests = [compute_chunk_digest(idx, c) for idx, c in enumerate(chunks)]
        chunk_hashes = [d.hex() for d in raw_digests]
        d_hash = compute_doc_hash(
            title=doc.title,
            document_type=doc.document_type,
            version=doc.version,
            source_url_or_ref=doc.source_url_or_ref,
            is_synthetic=doc.is_synthetic,
            raw_chunk_digests=raw_digests,
        )
        s_hash = compute_source_text_hash(doc.text)

        docs_data.append(
            {
                "approved_for_public_deployment": True,
                "chunk_count": len(chunks),
                "chunk_hashes": chunk_hashes,
                "doc_hash": d_hash,
                "document_type": doc.document_type,
                "is_synthetic": doc.is_synthetic,
                "source_text_sha256": s_hash,
                "source_url_or_ref": doc.source_url_or_ref,
                "title": doc.title,
                "version": doc.version,
            }
        )

    # Sort deterministically by identity tuple:
    # (title, document_type, version, source_url_or_ref)
    docs_data.sort(
        key=lambda d: (
            d["title"],
            d["document_type"],
            d["version"],
            "" if d["source_url_or_ref"] is None else d["source_url_or_ref"],
        )
    )

    registry: dict[str, Any] = {
        "chunker": {
            "algorithm": CHUNKER_ALGORITHM,
            "model_name": MODEL_NAME,
            "model_revision": MODEL_REVISION,
            "parameters": {
                "bge_model_max": BGE_MODEL_MAX,
                "overlap_max": OVERLAP_MAX,
                "overlap_min": OVERLAP_MIN,
                "safety_ceiling": MERIDIAN_SAFETY_CEILING,
                "target_max": TARGET_MAX,
                "target_min": TARGET_MIN,
            },
        },
        "documents": docs_data,
        "hash_algorithm": HASH_ALGORITHM,
        "registry_version": REGISTRY_VERSION,
    }

    return registry


def serialize_registry_json(registry_data: dict[str, Any]) -> str:
    """Serializes the registry data dictionary to canonical UTF-8 JSON.

    Canonical format:
    - ensure_ascii=False
    - sort_keys=True
    - separators=(',', ':')
    - allow_nan=False
    - exactly one trailing LF newline
    """
    return (
        json.dumps(
            registry_data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )


def write_policy_registry(
    output_path: Path | str,
    corpus: Sequence["PolicyDocumentSpec"] | None = None,
) -> Path:
    """Generates and writes the policy registry to the specified file path."""
    target_path = Path(output_path).resolve()
    registry_data = generate_policy_registry(corpus)
    serialized = serialize_registry_json(registry_data)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(serialized, encoding="utf-8", newline="\n")
    return target_path


def load_canonical_registry(path: Path | str | None = None) -> dict[str, Any]:
    """Loads and parses the committed canonical registry JSON."""
    registry_path = Path(path).resolve() if path else get_canonical_registry_path()
    if not registry_path.is_file():
        raise FileNotFoundError(
            f"Canonical policy registry not found at: {registry_path}"
        )
    raw_content = registry_path.read_text(encoding="utf-8")
    loaded = json.loads(raw_content)
    if not isinstance(loaded, dict):
        raise ValueError("Invalid registry: root element must be a JSON object")
    return loaded
