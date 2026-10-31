# ruff: noqa: E501
"""Unit and regression tests for the policy approval registry generator.

Verifies:
- Exactly four expected synthetic documents in POLICY_CORPUS_V1.
- No duplicate identities in the registry.
- Deterministic entry ordering.
- Byte-identical registry generation across different PYTHONHASHSEED values.
- Regenerated registry matches the committed bytes on disk.
- Source-text hashes correspond to the actual corpus text.
- Source-to-chunk token coverage, paragraph ordering, and decoding invariants.
"""

import os
import re
import subprocess
import sys
from typing import List

import pytest

from meridian.agents.policy.chunking import (
    OVERLAP_MAX,
    TARGET_MAX,
    chunk_document,
    chunk_document_tokens,
    tokenizer,
)
from meridian.loader.policy_corpus import POLICY_CORPUS_V1
from meridian.registry.generator import (
    generate_policy_registry,
    get_canonical_registry_path,
    load_canonical_registry,
    serialize_registry_json,
)
from meridian.registry.hashing import compute_source_text_hash


class TestRegistryContents:
    """Verifies contents and integrity of the policy approval registry."""

    def test_exactly_four_synthetic_documents(self) -> None:
        reg = load_canonical_registry()
        docs = reg["documents"]
        assert len(docs) == 4, f"Expected exactly 4 documents, got {len(docs)}"

        for doc in docs:
            assert doc["is_synthetic"] is True
            assert doc["approved_for_public_deployment"] is True
            assert doc["document_type"] == "internal_policy"
            assert doc["version"] == "v1"
            assert doc["source_url_or_ref"] == "meridian-synthetic-policy-corpus-v1"
            assert isinstance(doc["chunk_count"], int)
            assert doc["chunk_count"] == len(doc["chunk_hashes"])
            assert doc["chunk_count"] in (2, 3)

        total_chunks = sum(d["chunk_count"] for d in docs)
        assert total_chunks == 10, (
            f"Expected 10 total chunks across 4 documents, got {total_chunks}"
        )

    def test_no_duplicate_identities(self) -> None:
        reg = load_canonical_registry()
        identities = [
            (d["title"], d["document_type"], d["version"], d["source_url_or_ref"])
            for d in reg["documents"]
        ]
        assert len(identities) == len(set(identities)), (
            "Duplicate identity detected in registry"
        )

    def test_deterministic_entry_ordering(self) -> None:
        reg = load_canonical_registry()
        titles = [d["title"] for d in reg["documents"]]
        sorted_titles = sorted(titles)
        assert titles == sorted_titles, (
            "Registry documents must be sorted by identity key"
        )

    def test_regenerated_registry_matches_committed_bytes(self) -> None:
        committed_path = get_canonical_registry_path()
        committed_bytes = committed_path.read_bytes()

        fresh_reg = generate_policy_registry(POLICY_CORPUS_V1)
        fresh_serialized = serialize_registry_json(fresh_reg).encode("utf-8")

        assert fresh_serialized == committed_bytes, (
            "Regenerated registry does not match committed bytes on disk. "
            "Corpus or chunking contract was modified without updating the registry."
        )

    def test_source_text_hashes_correspond_to_actual_corpus(self) -> None:
        reg = load_canonical_registry()
        doc_by_title = {d["title"]: d for d in reg["documents"]}

        for spec in POLICY_CORPUS_V1:
            assert spec.title in doc_by_title
            reg_entry = doc_by_title[spec.title]
            expected_sha = compute_source_text_hash(spec.text)
            assert reg_entry["source_text_sha256"] == expected_sha


class TestRegistryCrossProcessDeterminism:
    """Verifies that serialization is identical across different PYTHONHASHSEED values."""

    @pytest.mark.parametrize("seed", ["0", "1", "42", "1337", "random"])
    def test_reproducible_across_hashseeds(self, seed: str) -> None:
        code = (
            "from meridian.registry.generator import generate_policy_registry, serialize_registry_json; "
            "from meridian.loader.policy_corpus import POLICY_CORPUS_V1; "
            "import sys; "
            "reg = generate_policy_registry(POLICY_CORPUS_V1); "
            "sys.stdout.buffer.write(serialize_registry_json(reg).encode('utf-8'))"
        )
        env = dict(os.environ, PYTHONPATH="src", PYTHONHASHSEED=seed)
        res = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            check=True,
            env=env,
        )
        committed_bytes = get_canonical_registry_path().read_bytes()
        assert res.stdout == committed_bytes


class TestSourceToChunkIntegrity:
    """Source-to-chunk coverage, token sequence preservation, and paragraph ordering tests.

    Verifies:
    - Expected tokenized paragraph segments are processed in order.
    - Every source token from paragraph-tokenization is represented in the emitted chunk-token sequences.
    - Overlap does not conceal missing source tokens.
    - Decoded chunk strings correspond exactly to the token sequences produced by the chunker.
    """

    def test_token_sequences_and_source_coverage(self) -> None:
        for doc_idx, doc in enumerate(POLICY_CORPUS_V1):
            # 1. Paragraph tokenization segments
            raw_blocks = re.split(r"\n\s*\n", doc.text)
            tokenized_blocks: List[List[int]] = []
            for block in raw_blocks:
                if not block.strip():
                    continue
                tokens = tokenizer.encode(block, add_special_tokens=False)
                idx = 0
                while idx < len(tokens):
                    tokenized_blocks.append(tokens[idx : idx + TARGET_MAX])
                    idx += TARGET_MAX

            all_source_tokens = [tok for b in tokenized_blocks for tok in b]

            # 2. Extract emitted token sequences
            chunk_tokens = chunk_document_tokens(doc.text)
            assert len(chunk_tokens) > 0

            # 3. Verify decoded chunks correspond exactly to tokenizer.decode
            actual_chunks = chunk_document(doc.text)
            decoded_from_tokens = [tokenizer.decode(ct) for ct in chunk_tokens]
            assert actual_chunks == decoded_from_tokens, (
                f"Document {doc_idx} ({doc.title}): decoded chunks do not match token sequences"
            )

            # 4. Verify in-order stream reconstruction via overlap removal
            reconstructed_tokens: List[int] = []
            prev_chunk: List[int] | None = None
            for c_idx, ct in enumerate(chunk_tokens):
                if prev_chunk is None:
                    reconstructed_tokens.extend(ct)
                else:
                    overlap_size = min(OVERLAP_MAX, int(0.2 * len(prev_chunk)))
                    # Check that current chunk starts with the exact overlap tokens from prev chunk
                    assert ct[:overlap_size] == prev_chunk[-overlap_size:], (
                        f"Document {doc_idx} chunk {c_idx}: overlap tokens do not match previous chunk tail"
                    )
                    # Extend by the new (non-overlap) tokens
                    reconstructed_tokens.extend(ct[overlap_size:])
                prev_chunk = ct

            # 5. Full coverage invariant: every source token is represented in order
            assert reconstructed_tokens == all_source_tokens, (
                f"Document {doc_idx} ({doc.title}): source token coverage mismatch! "
                f"Reconstructed {len(reconstructed_tokens)} vs Source {len(all_source_tokens)}"
            )
