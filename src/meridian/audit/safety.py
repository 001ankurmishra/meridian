"""Bounded failure diagnostics shared by persistence and response boundaries."""

from sqlalchemy.exc import SQLAlchemyError

ERROR_CODES = frozenset({
    "WATCHLIST_INTEGRITY_VIOLATION", "NORMALIZATION_VERSION_MISMATCH",
    "DATABASE_ERROR", "UNEXPECTED_ERROR", "INVALID_INPUT", "AGENT_ERROR",
})


def error_code(exc: Exception) -> str:
    """Classify without serializing exception text, SQL parameters or PII."""
    reason = getattr(exc, "reason_code", None)
    if isinstance(reason, str) and reason in ERROR_CODES:
        return reason
    if isinstance(exc, SQLAlchemyError):
        return "DATABASE_ERROR"
    if isinstance(exc, (ValueError, TypeError)):
        return "INVALID_INPUT"
    return "AGENT_ERROR"


def safe_stored_error(value: str | None) -> str | None:
    """Suppress legacy raw errors on read without rewriting append-only records."""
    if value is None:
        return None
    return value if value in ERROR_CODES else "AGENT_ERROR"
