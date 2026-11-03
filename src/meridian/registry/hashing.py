"""Canonical byte framing and SHA-256 hashing functions for policy provenance.

Contract version: v1
Adheres strictly to the Meridian byte-level encoding specification:
- Integer encoding: big-endian U32 and U64 with strict bounds and type checks.
- String framing: U32(len(b)) || b with strict UTF-8 encoding.
- Optional strings: 0x00 for None; 0x01 || FRAME(s) for non-NULL strings.
- Booleans: 0x00 for False, 0x01 for True.
- Domain separation: unique ASCII domain tags followed by a single zero byte.
"""

import hashlib
import struct
from collections.abc import Sequence

# Domain separation tags (ASCII followed by 0x00)
CHUNK_DOMAIN_TAG: bytes = b"meridian.policy-chunk.v1\x00"
DOC_DOMAIN_TAG: bytes = b"meridian.policy-doc.v1\x00"
SOURCE_DOMAIN_TAG: bytes = b"meridian.policy-source.v1\x00"


def encode_u32(n: int) -> bytes:
    """Encodes an unsigned 32-bit integer as exactly four big-endian bytes.

    Rejects negative numbers, overflow, non-integers, and booleans.
    Never silently truncates or wraps.
    """
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"Expected int for U32, got {type(n).__name__}")
    if n < 0 or n > 0xFFFFFFFF:
        raise ValueError(f"U32 out of range [0, 4294967295]: {n}")
    return struct.pack(">I", n)


def encode_u64(n: int) -> bytes:
    """Encodes an unsigned 64-bit integer as exactly eight big-endian bytes.

    Rejects negative numbers, overflow, non-integers, and booleans.
    Never silently truncates or wraps.
    """
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"Expected int for U64, got {type(n).__name__}")
    if n < 0 or n > 0xFFFFFFFFFFFFFFFF:
        raise ValueError(f"U64 out of range [0, 18446744073709551615]: {n}")
    return struct.pack(">Q", n)


def frame_string(s: str) -> bytes:
    """Frames a string as U32(len(b)) || b, where b is strict UTF-8 encoded.

    Length is the number of encoded bytes, not Unicode characters.
    Rejects invalid strings including lone surrogates. Performs no
    normalization, trimming, case conversion, or newline conversion.
    """
    if not isinstance(s, str):
        raise TypeError(f"Expected str, got {type(s).__name__}")
    try:
        b = s.encode("utf-8", errors="strict")
    except UnicodeEncodeError as e:
        raise ValueError(f"String cannot be strictly encoded as UTF-8: {e}") from e
    return encode_u32(len(b)) + b


def frame_optional_string(s: str | None) -> bytes:
    """Frames an optional string: 0x00 if None; 0x01 || FRAME(s) if not None."""
    if s is None:
        return b"\x00"
    if not isinstance(s, str):
        raise TypeError(f"Expected str or None, got {type(s).__name__}")
    return b"\x01" + frame_string(s)


def encode_bool(b: bool) -> bytes:
    """Encodes a boolean: 0x01 for True, 0x00 for False. Rejects non-booleans."""
    if not isinstance(b, bool):
        raise TypeError(f"Expected bool, got {type(b).__name__}")
    return b"\x01" if b else b"\x00"


def compute_chunk_digest(chunk_index: int, chunk_text: str) -> bytes:
    """Computes raw 32-byte SHA-256 digest for a document chunk.

    chunk_hash(i, text) = SHA-256(
        b"meridian.policy-chunk.v1\\x00" || U32(i) || FRAME(text)
    )
    """
    payload = CHUNK_DOMAIN_TAG + encode_u32(chunk_index) + frame_string(chunk_text)
    return hashlib.sha256(payload).digest()


def compute_chunk_hash(chunk_index: int, chunk_text: str) -> str:
    """Computes lowercase 64-hex SHA-256 hash for a document chunk."""
    return compute_chunk_digest(chunk_index, chunk_text).hex()


def compute_source_text_digest(text: str) -> bytes:
    """Computes raw 32-byte SHA-256 digest for policy source text.

    source_text_sha256 = SHA-256(
        b"meridian.policy-source.v1\\x00" || FRAME(spec.text)
    )
    """
    payload = SOURCE_DOMAIN_TAG + frame_string(text)
    return hashlib.sha256(payload).digest()


def compute_source_text_hash(text: str) -> str:
    """Computes lowercase 64-hex SHA-256 hash for policy source text."""
    return compute_source_text_digest(text).hex()


def compute_doc_digest(
    title: str,
    document_type: str,
    version: str,
    source_url_or_ref: str | None,
    is_synthetic: bool,
    raw_chunk_digests: Sequence[bytes | str],
) -> bytes:
    """Computes raw 32-byte SHA-256 digest for a policy document.

    doc_hash = SHA-256(
        b"meridian.policy-doc.v1\\x00"
        || FRAME(title)
        || FRAME(document_type)
        || FRAME(version)
        || OPT(source_url_or_ref)
        || BYTE(is_synthetic)
        || U32(n_chunks)
        || raw_chunk_digest_0
        || ...
        || raw_chunk_digest_n_minus_1
    )
    """
    parsed_digests: list[bytes] = []
    for idx, d in enumerate(raw_chunk_digests):
        if isinstance(d, str):
            try:
                raw_d = bytes.fromhex(d)
            except ValueError as e:
                raise ValueError(
                    f"Invalid hex string for chunk digest at index {idx}: {e}"
                ) from e
        elif isinstance(d, (bytes, bytearray)):
            raw_d = bytes(d)
        else:
            raise TypeError(
                f"Chunk digest at index {idx} must be bytes or hex str, "
                f"got {type(d).__name__}"
            )
        if len(raw_d) != 32:
            raise ValueError(
                f"Chunk digest at index {idx} must be exactly 32 bytes, "
                f"got {len(raw_d)}"
            )
        parsed_digests.append(raw_d)

    payload = (
        DOC_DOMAIN_TAG
        + frame_string(title)
        + frame_string(document_type)
        + frame_string(version)
        + frame_optional_string(source_url_or_ref)
        + encode_bool(is_synthetic)
        + encode_u32(len(parsed_digests))
        + b"".join(parsed_digests)
    )
    return hashlib.sha256(payload).digest()


def compute_doc_hash(
    title: str,
    document_type: str,
    version: str,
    source_url_or_ref: str | None,
    is_synthetic: bool,
    raw_chunk_digests: Sequence[bytes | str],
) -> str:
    """Computes lowercase 64-hex SHA-256 hash for a policy document."""
    return compute_doc_digest(
        title=title,
        document_type=document_type,
        version=version,
        source_url_or_ref=source_url_or_ref,
        is_synthetic=is_synthetic,
        raw_chunk_digests=raw_chunk_digests,
    ).hex()
