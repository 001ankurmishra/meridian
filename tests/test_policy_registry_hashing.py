# ruff: noqa: E501
"""Unit tests for canonical byte framing and SHA-256 hashing.

Tests:
- Fixed golden vectors with committed expected hexadecimal digests.
- Non-ASCII text, non-breaking spaces, CRLF, trailing whitespace.
- NULL optional source reference.
- Invalid Unicode (lone surrogates).
- Integer boundaries, overflow and invalid types (including bool).
- Domain separation.
- Length-framing collision cases.
- Changed chunk ordering produces a different document hash.
"""

import pytest

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


class TestIntegerEncoding:
    """Tests for U32 and U64 big-endian encoding."""

    def test_u32_valid_boundaries(self) -> None:
        assert encode_u32(0) == b"\x00\x00\x00\x00"
        assert encode_u32(1) == b"\x00\x00\x00\x01"
        assert encode_u32(255) == b"\x00\x00\x00\xff"
        assert encode_u32(65535) == b"\x00\x00\xff\xff"
        assert encode_u32(0xFFFFFFFF) == b"\xff\xff\xff\xff"

    def test_u32_overflow_and_negative(self) -> None:
        with pytest.raises(ValueError, match="U32 out of range"):
            encode_u32(-1)
        with pytest.raises(ValueError, match="U32 out of range"):
            encode_u32(0x100000000)

    def test_u32_rejects_bool_and_non_int(self) -> None:
        with pytest.raises(TypeError, match="Expected int for U32"):
            encode_u32(True)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="Expected int for U32"):
            encode_u32(False)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="Expected int for U32"):
            encode_u32(1.5)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="Expected int for U32"):
            encode_u32("42")  # type: ignore[arg-type]

    def test_u64_valid_boundaries(self) -> None:
        assert encode_u64(0) == b"\x00\x00\x00\x00\x00\x00\x00\x00"
        assert encode_u64(1) == b"\x00\x00\x00\x00\x00\x00\x00\x01"
        assert encode_u64(0xFFFFFFFFFFFFFFFF) == b"\xff\xff\xff\xff\xff\xff\xff\xff"

    def test_u64_overflow_and_negative(self) -> None:
        with pytest.raises(ValueError, match="U64 out of range"):
            encode_u64(-1)
        with pytest.raises(ValueError, match="U64 out of range"):
            encode_u64(0x10000000000000000)

    def test_u64_rejects_bool_and_non_int(self) -> None:
        with pytest.raises(TypeError, match="Expected int for U64"):
            encode_u64(True)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="Expected int for U64"):
            encode_u64(False)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="Expected int for U64"):
            encode_u64(3.14)  # type: ignore[arg-type]


class TestStringFraming:
    """Tests for string and optional string framing."""

    def test_empty_string(self) -> None:
        assert frame_string("") == b"\x00\x00\x00\x00"

    def test_ascii_string(self) -> None:
        assert frame_string("hello") == b"\x00\x00\x00\x05hello"

    def test_non_ascii_unicode(self) -> None:
        # "café" -> 'caf' (3 bytes) + 'é' (2 bytes: \xc3\xa9) = 5 bytes
        framed = frame_string("café")
        assert framed == b"\x00\x00\x00\x05caf\xc3\xa9"

    def test_non_breaking_space_and_crlf_and_whitespace(self) -> None:
        raw = "Line 1\r\nLine 2 with \u00a0 space and trailing   "
        b = raw.encode("utf-8")
        assert frame_string(raw) == encode_u32(len(b)) + b

    def test_rejects_surrogates(self) -> None:
        with pytest.raises(
            ValueError, match="String cannot be strictly encoded as UTF-8"
        ):
            frame_string("\ud800")

    def test_rejects_non_str(self) -> None:
        with pytest.raises(TypeError, match="Expected str"):
            frame_string(123)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="Expected str"):
            frame_string(b"raw bytes")  # type: ignore[arg-type]

    def test_frame_optional_string(self) -> None:
        assert frame_optional_string(None) == b"\x00"
        assert frame_optional_string("") == b"\x01\x00\x00\x00\x00"
        assert frame_optional_string("ref") == b"\x01\x00\x00\x00\x03ref"

        with pytest.raises(TypeError, match="Expected str or None"):
            frame_optional_string(42)  # type: ignore[arg-type]


class TestBooleanEncoding:
    """Tests for boolean encoding."""

    def test_bool_encoding(self) -> None:
        assert encode_bool(True) == b"\x01"
        assert encode_bool(False) == b"\x00"

    def test_rejects_non_bool(self) -> None:
        with pytest.raises(TypeError, match="Expected bool"):
            encode_bool(1)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="Expected bool"):
            encode_bool(0)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="Expected bool"):
            encode_bool("True")  # type: ignore[arg-type]


class TestGoldenVectors:
    """Independently fixed golden test vectors with committed hexadecimal literals."""

    def test_golden_vector_1_simple_chunk(self) -> None:
        # chunk_hash(0, "Test chunk text.")
        expected = "718690f7faaa232e13488a59379700b46af12203dd8a8ec1530e2cca3174f0b4"
        actual = compute_chunk_hash(0, "Test chunk text.")
        assert actual == expected
        assert compute_chunk_digest(0, "Test chunk text.").hex() == expected

    def test_golden_vector_2_complex_chunk(self) -> None:
        # Non-ASCII, NBSP (\u00a0), CRLF (\r\n), emoji, trailing spaces
        text = "Line 1\r\nLine 2 with \u00a0 non-breaking space and emoji \U0001f512 and trailing spaces   "
        expected = "1a0cf9b6866f9d11cce0569214a8bd022f0620ae195970236e3378bc0d40de74"
        actual = compute_chunk_hash(1, text)
        assert actual == expected

    def test_golden_vector_3_source_hash(self) -> None:
        text = "Source policy text with non-ASCII: €10,000 threshold."
        expected = "1ec1f748b7edf8b3b25ef497274850554997536047abc541deba55986c5a1dae"
        actual = compute_source_text_hash(text)
        assert actual == expected
        assert compute_source_text_digest(text).hex() == expected

    def test_golden_vector_4_doc_hash_null_source(self) -> None:
        # Title="Policy A", doc_type="internal_policy", version="v1", source=None, is_synthetic=True, 2 chunks
        c_zero = b"\x00" * 32
        c_one = b"\x01" * 32
        expected = "4cd558aa68cabc777b485db24828555aefd0a75a2c744e33727a1f7984204a9e"
        actual = compute_doc_hash(
            title="Policy A",
            document_type="internal_policy",
            version="v1",
            source_url_or_ref=None,
            is_synthetic=True,
            raw_chunk_digests=[c_zero, c_one],
        )
        assert actual == expected
        assert (
            compute_doc_digest(
                "Policy A", "internal_policy", "v1", None, True, [c_zero, c_one]
            ).hex()
            == expected
        )

    def test_golden_vector_5_doc_hash_with_source_ref(self) -> None:
        # Title="Policy B", doc_type="regulatory_guidance", version="v2", source="https://example.com/ref", is_synthetic=False, 1 chunk
        c_zero = b"\x00" * 32
        expected = "e6b764a6788554741acdf3d1b1d8c7fd716073d9eb605081ef449fe0368d465d"
        actual = compute_doc_hash(
            title="Policy B",
            document_type="regulatory_guidance",
            version="v2",
            source_url_or_ref="https://example.com/ref",
            is_synthetic=False,
            raw_chunk_digests=[c_zero],
        )
        assert actual == expected

    def test_golden_vector_6_reordered_chunks_different_hash(self) -> None:
        c_zero = b"\x00" * 32
        c_one = b"\x01" * 32
        expected_reversed = (
            "cc3a82db7fd0a9c720d4bdfd09e878c024ef95f87e01adf9bc6aa9e654b6af27"
        )
        actual_reversed = compute_doc_hash(
            title="Policy A",
            document_type="internal_policy",
            version="v1",
            source_url_or_ref=None,
            is_synthetic=True,
            raw_chunk_digests=[c_one, c_zero],  # reversed order
        )
        assert actual_reversed == expected_reversed
        # Must differ from [c_zero, c_one]
        forward = compute_doc_hash(
            title="Policy A",
            document_type="internal_policy",
            version="v1",
            source_url_or_ref=None,
            is_synthetic=True,
            raw_chunk_digests=[c_zero, c_one],
        )
        assert actual_reversed != forward


class TestSecurityAndCollisionResistance:
    """Tests for length-framing collision resistance and domain separation."""

    def test_length_framing_collision_resistance(self) -> None:
        # Without length framing, ("ab", "cd") and ("a", "bcd") would produce the same concatenated bytes
        h1 = compute_doc_hash(
            title="ab",
            document_type="cd",
            version="v1",
            source_url_or_ref=None,
            is_synthetic=True,
            raw_chunk_digests=[b"\x00" * 32],
        )
        h2 = compute_doc_hash(
            title="a",
            document_type="bcd",
            version="v1",
            source_url_or_ref=None,
            is_synthetic=True,
            raw_chunk_digests=[b"\x00" * 32],
        )
        assert h1 != h2

    def test_domain_separation(self) -> None:
        # Domain tags must be strictly distinct
        assert CHUNK_DOMAIN_TAG != DOC_DOMAIN_TAG
        assert CHUNK_DOMAIN_TAG != SOURCE_DOMAIN_TAG
        assert DOC_DOMAIN_TAG != SOURCE_DOMAIN_TAG

        # Even with identical subsequent framing, domain separation ensures distinct outputs
        # E.g. source hash of "test" vs chunk hash of 0, "test"
        # Source: b"meridian.policy-source.v1\x00" || FRAME("test")
        # If a domain tag is tampered or omitted, output changes
        s_hash = compute_source_text_hash("test")
        c_hash = compute_chunk_hash(0, "test")
        assert s_hash != c_hash

    def test_rejects_invalid_chunk_digest_length(self) -> None:
        with pytest.raises(ValueError, match="must be exactly 32 bytes"):
            compute_doc_hash(
                title="T",
                document_type="internal_policy",
                version="v1",
                source_url_or_ref=None,
                is_synthetic=True,
                raw_chunk_digests=[b"\x00" * 31],  # 31 bytes
            )
