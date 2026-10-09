"""
Tests for deterministic synthetic watchlist corpus reproducibility and hash stability.
"""

from meridian.agents.sanctions.validation import validate_watchlist_entries
from meridian.loader.watchlist_corpus import (
    SYNTHETIC_WATCHLIST_CONTENT_HASH,
    SYNTHETIC_WATCHLIST_CORPUS,
    SYNTHETIC_WATCHLIST_NAME,
    SYNTHETIC_WATCHLIST_VERSION,
    _build_synthetic_corpus,
    compute_corpus_content_hash,
    get_synthetic_watchlist_corpus,
    make_entry_id,
)

EXPECTED_FROZEN_CORPUS_HASH = (
    "c75d513d01882871d58a4550952182c27abbb56aac79ec34e67f2c883c1c7738"
)


def test_corpus_passes_whole_version_validation() -> None:
    """Verify that the synthetic corpus passes all validation invariants."""
    corpus = get_synthetic_watchlist_corpus()
    validate_watchlist_entries(corpus)
    assert len(corpus) == 10


def test_corpus_frozen_content_hash() -> None:
    """
    Verify the content hash against the frozen manifest digest.
    Demonstrates reproducibility across runs.
    """
    assert SYNTHETIC_WATCHLIST_CONTENT_HASH == EXPECTED_FROZEN_CORPUS_HASH
    recomputed = compute_corpus_content_hash(SYNTHETIC_WATCHLIST_CORPUS)
    assert recomputed == EXPECTED_FROZEN_CORPUS_HASH


def test_corpus_entry_ids_are_deterministic_uuid5() -> None:
    """Verify entry IDs are strictly deterministic UUIDv5 derived from natural keys."""
    for entry in SYNTHETIC_WATCHLIST_CORPUS:
        expected_id = make_entry_id(
            entry.watchlist_name,
            entry.watchlist_version,
            entry.subject_key,
            entry.name_type,
            entry.listed_name,
        )
        assert entry.entry_id == expected_id


def test_corpus_determinism_multiple_builds() -> None:
    """Verify independent corpus construction produces identical content."""
    build1 = _build_synthetic_corpus()
    build2 = _build_synthetic_corpus()
    assert build1 == build2
    assert compute_corpus_content_hash(build1) == compute_corpus_content_hash(build2)


def test_corpus_metadata_and_synthetic_only() -> None:
    """Verify all entries are marked synthetic and have explicit name and version."""
    for entry in SYNTHETIC_WATCHLIST_CORPUS:
        assert entry.is_synthetic is True
        assert entry.watchlist_name == SYNTHETIC_WATCHLIST_NAME
        assert entry.watchlist_version == SYNTHETIC_WATCHLIST_VERSION
        assert entry.source.startswith("MERIDIAN_SYNTHETIC")
