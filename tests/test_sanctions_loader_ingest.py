"""
Tests for atomic, immutable watchlist version ingestion.

Verifies:
- Atomic insertion in single transaction
- Idempotent no-op upon identical reload
- Conflict rejection upon modified reload
- Coexistence of distinct versions
- Pre-write validation atomicity
"""

import datetime
import uuid

import pytest
from sqlalchemy import Engine, text

from meridian.agents.sanctions.errors import (
    WatchlistValidationError,
    WatchlistVersionConflict,
)
from meridian.agents.sanctions.types import NameType, WatchlistEntry
from meridian.loader.watchlist_corpus import (
    SYNTHETIC_WATCHLIST_NAME,
    SYNTHETIC_WATCHLIST_VERSION,
    get_synthetic_watchlist_corpus,
)
from meridian.loader.watchlist_ingest import ingest_watchlist_version


@pytest.fixture(autouse=True)
def clean_watchlist_entries(superuser_engine: Engine) -> None:
    """Clean test watchlist entries before and after tests."""
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM watchlist_entries"))
    yield
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM watchlist_entries"))


def test_ingest_initial_version_success(loader_role_engine: Engine) -> None:
    """Verify first-time load inserts all corpus entries atomically."""
    corpus = get_synthetic_watchlist_corpus()
    res = ingest_watchlist_version(loader_role_engine, corpus)

    assert res.inserted == 10
    assert res.already_existed is False
    assert res.watchlist_name == SYNTHETIC_WATCHLIST_NAME
    assert res.watchlist_version == SYNTHETIC_WATCHLIST_VERSION

    # Verify rows in database and created_at populated by server default
    with loader_role_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT entry_id, watchlist_name, watchlist_version, created_at "
                "FROM watchlist_entries "
                "WHERE watchlist_name = :w_name AND watchlist_version = :w_ver"
            ),
            {"w_name": SYNTHETIC_WATCHLIST_NAME, "w_ver": SYNTHETIC_WATCHLIST_VERSION},
        ).fetchall()
        assert len(rows) == 10
        for r in rows:
            assert r.created_at is not None


def test_ingest_identical_reload_is_idempotent_no_op(
    loader_role_engine: Engine,
) -> None:
    """Verify loading identical version a second time is an idempotent no-op."""
    corpus = get_synthetic_watchlist_corpus()
    res1 = ingest_watchlist_version(loader_role_engine, corpus)
    assert res1.inserted == 10
    assert res1.already_existed is False

    # Second load: identical content
    res2 = ingest_watchlist_version(loader_role_engine, corpus)
    assert res2.inserted == 0
    assert res2.already_existed is True
    assert res2.watchlist_name == SYNTHETIC_WATCHLIST_NAME
    assert res2.watchlist_version == SYNTHETIC_WATCHLIST_VERSION

    # Row count remains 10
    with loader_role_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM watchlist_entries")).scalar()
        assert count == 10


def test_ingest_conflicting_reload_raises(loader_role_engine: Engine) -> None:
    """
    Verify reloading the same version with modified content raises
    WatchlistVersionConflict.
    """
    corpus = get_synthetic_watchlist_corpus()
    ingest_watchlist_version(loader_role_engine, corpus)

    # Modify an entry's DOB under the same version name
    modified_corpus = list(corpus)
    first = modified_corpus[0]
    modified_corpus[0] = WatchlistEntry(
        entry_id=first.entry_id,
        watchlist_name=first.watchlist_name,
        watchlist_version=first.watchlist_version,
        subject_key=first.subject_key,
        name_type=first.name_type,
        listed_name=first.listed_name,
        date_of_birth=datetime.date(1999, 12, 31),
        is_synthetic=first.is_synthetic,
        source=first.source,
    )
    # Also update aliases of the same subject for consistency
    for i in range(1, len(modified_corpus)):
        if modified_corpus[i].subject_key == first.subject_key:
            mod = modified_corpus[i]
            modified_corpus[i] = WatchlistEntry(
                entry_id=mod.entry_id,
                watchlist_name=mod.watchlist_name,
                watchlist_version=mod.watchlist_version,
                subject_key=mod.subject_key,
                name_type=mod.name_type,
                listed_name=mod.listed_name,
                date_of_birth=datetime.date(1999, 12, 31),
                is_synthetic=mod.is_synthetic,
                source=mod.source,
            )

    with pytest.raises(WatchlistVersionConflict, match="already exists with differing"):
        ingest_watchlist_version(loader_role_engine, modified_corpus)

    # Verify existing version was NOT mutated
    with loader_role_engine.connect() as conn:
        stored_dob = conn.execute(
            text("SELECT date_of_birth FROM watchlist_entries WHERE entry_id = :eid"),
            {"eid": first.entry_id},
        ).scalar()
        assert stored_dob == first.date_of_birth


def test_ingest_distinct_versions_coexist(loader_role_engine: Engine) -> None:
    """Verify distinct version identifiers can coexist without conflict."""
    corpus_v1 = get_synthetic_watchlist_corpus()
    res1 = ingest_watchlist_version(loader_role_engine, corpus_v1)
    assert res1.inserted == 10

    # Build v2
    corpus_v2 = [
        WatchlistEntry(
            entry_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"v2:{e.entry_id}"),
            watchlist_name=e.watchlist_name,
            watchlist_version="v2",
            subject_key=e.subject_key,
            name_type=e.name_type,
            listed_name=e.listed_name,
            date_of_birth=e.date_of_birth,
            is_synthetic=True,
            source="MERIDIAN_SYNTHETIC_WATCHLIST_v2",
        )
        for e in corpus_v1
    ]

    res2 = ingest_watchlist_version(loader_role_engine, corpus_v2)
    assert res2.inserted == 10

    # Total rows = 20
    with loader_role_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM watchlist_entries")).scalar()
        assert count == 20


def test_ingest_invalid_version_fails_pre_write(
    loader_role_engine: Engine,
) -> None:
    """
    Verify an invalid version fails validation before transaction and
    writes nothing.
    """
    bad_entry = WatchlistEntry(
        entry_id=uuid.uuid4(),
        watchlist_name="invalid_list",
        watchlist_version="v1",
        subject_key="S1",
        name_type=NameType.PRIMARY,
        listed_name="Test",
        date_of_birth=None,
        is_synthetic=False,  # Violates is_synthetic=True
        source="test",
    )

    with pytest.raises(WatchlistValidationError, match="is_synthetic=True"):
        ingest_watchlist_version(loader_role_engine, [bad_entry])

    with loader_role_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM watchlist_entries")).scalar()
        assert count == 0
