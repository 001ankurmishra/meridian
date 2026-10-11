"""
Domain types and enums for F11 sanctions and watchlist screening.
"""

import datetime
import uuid
from dataclasses import dataclass
from enum import Enum

from meridian.agents.sanctions.errors import WatchlistValidationError

MATCHING_RULE_ID = "exact_norm_name_v1"


class NameType(str, Enum):
    """Classification of listed name in a watchlist subject record."""

    PRIMARY = "primary"
    ALIAS = "alias"


class DobComparison(str, Enum):
    """Result of date-of-birth comparison between customer and subject."""

    EQUAL = "EQUAL"
    DIFFERENT = "DIFFERENT"
    NOT_COMPARABLE = "NOT_COMPARABLE"


class ScreeningOutcome(str, Enum):
    """Deterministic domain outcome of candidate screening."""

    CANDIDATE_MATCHES_FOUND = "CANDIDATE_MATCHES_FOUND"
    NO_CANDIDATE_MATCH = "NO_CANDIDATE_MATCH"
    NOT_PERFORMED = "NOT_PERFORMED"


class AbstentionReason(str, Enum):
    """Controlled abstention reasons permitted under ADR-0008 D8."""

    CUSTOMER_NAME_MISSING = "CUSTOMER_NAME_MISSING"
    CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION = (
        "CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION"
    )
    WATCHLIST_VERSION_NOT_LOADED = "WATCHLIST_VERSION_NOT_LOADED"


@dataclass(frozen=True)
class WatchlistEntry:
    """
    Immutable representation of a single listed name entry on a watchlist.
    """

    entry_id: uuid.UUID
    watchlist_name: str
    watchlist_version: str
    subject_key: str
    name_type: NameType
    listed_name: str
    date_of_birth: datetime.date | None
    is_synthetic: bool = True
    source: str = "SYNTHETIC_SANCTIONS_CORPUS"
    created_at: datetime.datetime | None = None


def _require_non_blank_str(value: object, field_name: str, owner: str) -> None:
    """Raise WatchlistValidationError unless value is a non-blank string.

    Messages name the field only and never echo the offending value.
    """
    if not isinstance(value, str) or not value.strip():
        raise WatchlistValidationError(
            f"{owner} requires a non-empty string {field_name}."
        )


@dataclass(frozen=True)
class LoadedWatchlistVersion:
    """
    A fully loaded, pinned watchlist version (replacement contract, Task 23b).

    Invariants enforced at construction (structural checks only; whole-version
    validation remains in validate_watchlist_entries, run by the reader):
    - watchlist_name and watchlist_version are non-blank strings.
    - entries is a tuple (not a list or other mutable sequence).
    - entries is non-empty.
    - every element is a WatchlistEntry carrying this container's
      watchlist_name and watchlist_version.

    The dataclass is frozen, so attributes cannot be reassigned, and entries
    is an immutable tuple. Exception messages never contain entry data.
    """

    watchlist_name: str
    watchlist_version: str
    entries: tuple[WatchlistEntry, ...]

    def __post_init__(self) -> None:
        owner = "LoadedWatchlistVersion"
        _require_non_blank_str(self.watchlist_name, "watchlist_name", owner)
        _require_non_blank_str(self.watchlist_version, "watchlist_version", owner)
        if not isinstance(self.entries, tuple):
            raise WatchlistValidationError(f"{owner}.entries must be a tuple.")
        if len(self.entries) == 0:
            raise WatchlistValidationError(
                f"{owner}.entries must contain at least one entry."
            )
        if not all(isinstance(e, WatchlistEntry) for e in self.entries):
            raise WatchlistValidationError(
                f"{owner}.entries must contain only WatchlistEntry instances."
            )
        if any(
            e.watchlist_name != self.watchlist_name
            or e.watchlist_version != self.watchlist_version
            for e in self.entries
        ):
            raise WatchlistValidationError(
                f"{owner}.entries must all carry the container's "
                "watchlist_name and watchlist_version."
            )


@dataclass(frozen=True)
class WatchlistVersionNotLoaded:
    """
    Returned (not raised) when the requested pinned watchlist version has
    zero rows. The matcher converts it, and only it, into controlled
    abstention NOT_PERFORMED(WATCHLIST_VERSION_NOT_LOADED).
    """

    watchlist_name: str
    watchlist_version: str

    def __post_init__(self) -> None:
        owner = "WatchlistVersionNotLoaded"
        _require_non_blank_str(self.watchlist_name, "watchlist_name", owner)
        _require_non_blank_str(self.watchlist_version, "watchlist_version", owner)


WatchlistReadResult = LoadedWatchlistVersion | WatchlistVersionNotLoaded


@dataclass(frozen=True)
class SanctionsCandidate:
    """
    Candidate match record for a watchlist subject.

    A candidate exists when normalized customer name equals any normalized
    listed name (primary or alias) for the subject.
    DOB is an attribute for human review, never an identity gate.
    """

    subject_key: str
    matched_entries: tuple[WatchlistEntry, ...]
    dob_comparison: DobComparison
    subject_dob: datetime.date | None
    customer_dob: datetime.date | None


@dataclass(frozen=True)
class SanctionsMatchResult:
    """
    Complete output of a candidate screening run.

    Consistent with ADR-0008 D7/D8 invariants:
    - outcome is CANDIDATE_MATCHES_FOUND iff candidate_count > 0.
    - outcome is NOT_PERFORMED iff reason_code is non-None.
    - outcome is NO_CANDIDATE_MATCH iff candidate_count == 0 and reason_code is None.
    """

    outcome: ScreeningOutcome
    reason_code: AbstentionReason | None
    candidates: tuple[SanctionsCandidate, ...]
    watchlist_name: str
    watchlist_version: str
    matching_rule_id: str = MATCHING_RULE_ID
    normalization_version: str = "v1"

    def __post_init__(self) -> None:
        if self.outcome == ScreeningOutcome.NOT_PERFORMED:
            if self.reason_code is None:
                raise ValueError(
                    "reason_code must be set when outcome is NOT_PERFORMED"
                )
            if len(self.candidates) > 0:
                raise ValueError(
                    "candidates must be empty when outcome is NOT_PERFORMED"
                )
        elif self.outcome == ScreeningOutcome.CANDIDATE_MATCHES_FOUND:
            if self.reason_code is not None:
                raise ValueError(
                    "reason_code must be None when outcome is "
                    "CANDIDATE_MATCHES_FOUND"
                )
            if len(self.candidates) == 0:
                raise ValueError(
                    "candidates must not be empty when outcome is "
                    "CANDIDATE_MATCHES_FOUND"
                )
        elif self.outcome == ScreeningOutcome.NO_CANDIDATE_MATCH:
            if self.reason_code is not None:
                raise ValueError(
                    "reason_code must be None when outcome is NO_CANDIDATE_MATCH"
                )
            if len(self.candidates) > 0:
                raise ValueError(
                    "candidates must be empty when outcome is NO_CANDIDATE_MATCH"
                )
