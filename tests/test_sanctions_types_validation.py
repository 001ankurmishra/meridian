"""
Tests for domain types and whole-version validation invariants.
"""

import datetime
import uuid

import pytest

from meridian.agents.sanctions.errors import (
    WatchlistIntegrityViolation,
    WatchlistValidationError,
)
from meridian.agents.sanctions.types import (
    DobComparison,
    NameType,
    SanctionsCandidate,
    SanctionsMatchResult,
    ScreeningOutcome,
    WatchlistEntry,
)
from meridian.agents.sanctions.validation import validate_watchlist_entries


def _make_valid_entry(
    entry_id: uuid.UUID | None = None,
    subject_key: str = "SUBJ-001",
    name_type: NameType = NameType.PRIMARY,
    listed_name: str = "Test Subject",
    dob: datetime.date | None = datetime.date(1980, 1, 1),
    watchlist_name: str = "test_list",
    watchlist_version: str = "v1",
    is_synthetic: bool = True,
    source: str = "test_source",
) -> WatchlistEntry:
    return WatchlistEntry(
        entry_id=entry_id or uuid.uuid4(),
        watchlist_name=watchlist_name,
        watchlist_version=watchlist_version,
        subject_key=subject_key,
        name_type=name_type,
        listed_name=listed_name,
        date_of_birth=dob,
        is_synthetic=is_synthetic,
        source=source,
    )


def test_validation_empty_entries_raises() -> None:
    with pytest.raises(WatchlistValidationError, match="zero entries"):
        validate_watchlist_entries([])


def test_validation_missing_watchlist_name_raises() -> None:
    e = _make_valid_entry(watchlist_name="   ")
    with pytest.raises(WatchlistValidationError, match="non-empty string"):
        validate_watchlist_entries([e])


def test_validation_missing_watchlist_version_raises() -> None:
    e = _make_valid_entry(watchlist_version="")
    with pytest.raises(WatchlistValidationError, match="non-empty string"):
        validate_watchlist_entries([e])


def test_validation_mismatched_version_within_batch_raises() -> None:
    e1 = _make_valid_entry(subject_key="SUBJ-1", watchlist_version="v1")
    e2 = _make_valid_entry(subject_key="SUBJ-2", watchlist_version="v2")
    with pytest.raises(WatchlistValidationError, match="watchlist_version"):
        validate_watchlist_entries([e1, e2])


def test_validation_non_synthetic_raises() -> None:
    e = _make_valid_entry(is_synthetic=False)
    with pytest.raises(WatchlistValidationError, match="is_synthetic=True"):
        validate_watchlist_entries([e])


def test_validation_duplicate_entry_id_raises() -> None:
    shared_id = uuid.uuid4()
    e1 = _make_valid_entry(entry_id=shared_id, subject_key="SUBJ-1")
    e2 = _make_valid_entry(entry_id=shared_id, subject_key="SUBJ-2")
    with pytest.raises(WatchlistValidationError, match="Duplicate entry_id"):
        validate_watchlist_entries([e1, e2])


def test_validation_blank_listed_name_raises() -> None:
    e = _make_valid_entry(listed_name="  ")
    with pytest.raises(WatchlistValidationError, match="empty after normalization"):
        validate_watchlist_entries([e])


def test_validation_empty_after_normalization_raises() -> None:
    e = _make_valid_entry(listed_name="\u00a0\u00a0")
    with pytest.raises(WatchlistValidationError, match="empty after normalization"):
        validate_watchlist_entries([e])


def test_validation_duplicate_natural_key_raises() -> None:
    e1 = _make_valid_entry(
        subject_key="SUBJ-1", name_type=NameType.PRIMARY, listed_name="John Doe"
    )
    e2 = _make_valid_entry(
        subject_key="SUBJ-1", name_type=NameType.PRIMARY, listed_name="John Doe"
    )
    with pytest.raises(WatchlistValidationError, match="Duplicate natural key"):
        validate_watchlist_entries([e1, e2])


def test_validation_multiple_primaries_for_subject_raises() -> None:
    e1 = _make_valid_entry(
        subject_key="SUBJ-1", name_type=NameType.PRIMARY, listed_name="John Doe"
    )
    e2 = _make_valid_entry(
        subject_key="SUBJ-1", name_type=NameType.PRIMARY, listed_name="Jonathan Doe"
    )
    with pytest.raises(WatchlistValidationError, match="exactly 1 is required"):
        validate_watchlist_entries([e1, e2])


def test_validation_missing_primary_for_subject_raises() -> None:
    e1 = _make_valid_entry(
        subject_key="SUBJ-1", name_type=NameType.ALIAS, listed_name="John Doe"
    )
    with pytest.raises(WatchlistValidationError, match="exactly 1 is required"):
        validate_watchlist_entries([e1])


def test_validation_inconsistent_dob_for_subject_raises() -> None:
    e1 = _make_valid_entry(
        subject_key="SUBJ-1",
        name_type=NameType.PRIMARY,
        listed_name="John Doe",
        dob=datetime.date(1980, 1, 1),
    )
    e2 = _make_valid_entry(
        subject_key="SUBJ-1",
        name_type=NameType.ALIAS,
        listed_name="Johnny Doe",
        dob=datetime.date(1985, 5, 5),
    )
    with pytest.raises(WatchlistValidationError, match="Inconsistent date_of_birth"):
        validate_watchlist_entries([e1, e2])


def test_validation_integrity_violation_mode() -> None:
    e = _make_valid_entry(is_synthetic=False)
    with pytest.raises(WatchlistIntegrityViolation):
        validate_watchlist_entries([e], as_integrity_violation=True)


def test_sanctions_match_result_invariants() -> None:
    """Verify SanctionsMatchResult post-init contract."""
    # NOT_PERFORMED must have reason_code and empty candidates
    with pytest.raises(ValueError, match="reason_code must be set"):
        SanctionsMatchResult(
            outcome=ScreeningOutcome.NOT_PERFORMED,
            reason_code=None,
            candidates=(),
            watchlist_name="list",
            watchlist_version="v1",
        )

    # CANDIDATE_MATCHES_FOUND must have candidates and no reason_code
    with pytest.raises(ValueError, match="candidates must not be empty"):
        SanctionsMatchResult(
            outcome=ScreeningOutcome.CANDIDATE_MATCHES_FOUND,
            reason_code=None,
            candidates=(),
            watchlist_name="list",
            watchlist_version="v1",
        )

    # NO_CANDIDATE_MATCH must have empty candidates and no reason_code
    candidate = SanctionsCandidate(
        subject_key="S1",
        matched_entries=(_make_valid_entry(),),
        dob_comparison=DobComparison.EQUAL,
        subject_dob=None,
        customer_dob=None,
    )
    with pytest.raises(ValueError, match="candidates must be empty"):
        SanctionsMatchResult(
            outcome=ScreeningOutcome.NO_CANDIDATE_MATCH,
            reason_code=None,
            candidates=(candidate,),
            watchlist_name="list",
            watchlist_version="v1",
        )
