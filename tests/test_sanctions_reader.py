"""
Tests for read-only exact-version watchlist reader.

Verifies:
- Exact-version querying with bound parameters
- Typed WatchlistVersionNotLoaded on zero rows
- Defense-in-depth WatchlistIntegrityViolation on corrupted data
- Architecture guard prohibiting MAX/latest/implicit pins
"""

from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from meridian.agents.sanctions.errors import (
    WatchlistIntegrityViolation,
    WatchlistVersionNotLoaded,
)
from meridian.agents.sanctions.reader import read_watchlist_version
from meridian.loader.watchlist_corpus import (
    SYNTHETIC_WATCHLIST_NAME,
    SYNTHETIC_WATCHLIST_VERSION,
    get_synthetic_watchlist_corpus,
)
from meridian.loader.watchlist_ingest import ingest_watchlist_version


@pytest.fixture(autouse=True)
def seed_watchlist(loader_role_engine: Engine, superuser_engine: Engine) -> None:
    """Ensure clean watchlist state and seed synthetic corpus."""
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM watchlist_entries"))
    ingest_watchlist_version(loader_role_engine, get_synthetic_watchlist_corpus())
    yield
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM watchlist_entries"))


def test_reader_loads_exact_version(app_role_engine: Engine) -> None:
    """Verify reading exact pinned version returns all 10 validated domain records."""
    entries = read_watchlist_version(
        app_role_engine,
        watchlist_name=SYNTHETIC_WATCHLIST_NAME,
        watchlist_version=SYNTHETIC_WATCHLIST_VERSION,
    )
    assert len(entries) == 10
    assert isinstance(entries, tuple)
    assert entries[0].watchlist_name == SYNTHETIC_WATCHLIST_NAME
    assert entries[0].watchlist_version == SYNTHETIC_WATCHLIST_VERSION


def test_reader_unloaded_version_raises(app_role_engine: Engine) -> None:
    """Verify querying an un-loaded version raises typed WatchlistVersionNotLoaded."""
    with pytest.raises(WatchlistVersionNotLoaded, match="is not loaded"):
        read_watchlist_version(
            app_role_engine,
            watchlist_name=SYNTHETIC_WATCHLIST_NAME,
            watchlist_version="9999.unloaded",
        )


def test_reader_missing_arguments_raises(app_role_engine: Engine) -> None:
    """Verify empty or whitespace name/version raises ValueError."""
    with pytest.raises(ValueError, match="watchlist_name"):
        read_watchlist_version(app_role_engine, "", "v1")

    with pytest.raises(ValueError, match="watchlist_version"):
        read_watchlist_version(app_role_engine, "list", "   ")


def test_reader_defense_in_depth_integrity_violation(
    superuser_engine: Engine,
    app_role_engine: Engine,
) -> None:
    """
    Verify that corrupted loaded rows trigger WatchlistIntegrityViolation.
    We inject a corrupt row by disabling the check constraint as superuser.
    """
    # Temporarily drop constraint and insert a malformed row without primary
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO watchlist_entries "
                "(entry_id, watchlist_name, watchlist_version, subject_key, "
                " name_type, listed_name, is_synthetic, source) "
                "VALUES (gen_random_uuid(), 'corrupt_list', 'v1', 'SUBJ-X', "
                "        'alias', 'Orphan Alias', true, 'test')"
            )
        )

    with pytest.raises(WatchlistIntegrityViolation, match="primary"):
        read_watchlist_version(
            app_role_engine,
            watchlist_name="corrupt_list",
            watchlist_version="v1",
        )


def test_reader_architecture_guard_no_max_or_latest() -> None:
    """
    Architecture guard per ADR-0008 D6:
    Verify reader query contains no MAX(version), ORDER BY version, or 'latest' lookups.
    """
    reader_file = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "meridian"
        / "agents"
        / "sanctions"
        / "reader.py"
    )
    content = reader_file.read_text().lower()

    assert "max(version)" not in content
    assert "max(" not in content
    assert "order by watchlist_version" not in content
    assert "order by version" not in content
    assert "latest" not in content
