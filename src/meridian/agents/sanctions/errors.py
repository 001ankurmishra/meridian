"""
Typed exceptions for F11 sanctions and watchlist screening.

All exceptions inherit from SanctionsError.
"""


class SanctionsError(Exception):
    """Base exception for all sanctions/watchlist domain/infra errors."""


class WatchlistIntegrityViolation(SanctionsError):
    """Raised when loaded watchlist data violates domain validation invariants."""


class NormalizationVersionMismatch(SanctionsError):
    """Raised when imported normalization version differs from expected."""


class WatchlistValidationError(SanctionsError):
    """Raised when proposed watchlist version fails pre-load validation."""


class WatchlistVersionConflict(SanctionsError):
    """Raised when an immutable watchlist version already exists with differences."""
