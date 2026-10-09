"""
Domain types and enums for F11 sanctions and watchlist screening.
"""

import datetime
import uuid
from dataclasses import dataclass
from enum import Enum

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
