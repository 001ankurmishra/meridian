"""
Sanctions and watchlist screening package (F11).

Provides deterministic customer screening against pinned synthetic watchlists
following ADR-0008.
"""

from meridian.agents.sanctions.errors import (
    NormalizationVersionMismatch,
    SanctionsError,
    WatchlistIntegrityViolation,
    WatchlistValidationError,
    WatchlistVersionConflict,
    WatchlistVersionNotLoaded,
)
from meridian.agents.sanctions.matching import (
    compare_dob,
    match_customer_against_watchlist,
)
from meridian.agents.sanctions.normalization import (
    EXPECTED_NORMALIZATION_VERSION,
    NORMALIZATION_VERSION,
    normalize_full_name,
)
from meridian.agents.sanctions.reader import read_watchlist_version
from meridian.agents.sanctions.types import (
    MATCHING_RULE_ID,
    AbstentionReason,
    DobComparison,
    NameType,
    SanctionsCandidate,
    SanctionsMatchResult,
    ScreeningOutcome,
    WatchlistEntry,
)
from meridian.agents.sanctions.validation import validate_watchlist_entries

__all__ = [
    "MATCHING_RULE_ID",
    "EXPECTED_NORMALIZATION_VERSION",
    "NORMALIZATION_VERSION",
    "AbstentionReason",
    "DobComparison",
    "NameType",
    "NormalizationVersionMismatch",
    "SanctionsCandidate",
    "SanctionsError",
    "SanctionsMatchResult",
    "ScreeningOutcome",
    "WatchlistEntry",
    "WatchlistIntegrityViolation",
    "WatchlistValidationError",
    "WatchlistVersionConflict",
    "WatchlistVersionNotLoaded",
    "compare_dob",
    "match_customer_against_watchlist",
    "normalize_full_name",
    "read_watchlist_version",
    "validate_watchlist_entries",
]
