"""SanctionsAgent dispatch slice (Task 24 Stage 1).

Implements the standalone dispatch for F11 sanctions and watchlist screening
according to ADR-0008 D1, D3, D6, D8, and D9.

The dispatch wraps customer lookup and deterministic watchlist screening inside
record_agent_run(), maintaining strict outcome semantics:
- Controlled abstentions (WATCHLIST_VERSION_NOT_LOADED, CUSTOMER_NAME_MISSING,
  CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION) record agent_runs.status = SUCCESS.
- Technical failures (WATCHLIST_INTEGRITY_VIOLATION, NORMALIZATION_VERSION_MISMATCH,
  DATABASE_ERROR, UNEXPECTED_ERROR) record agent_runs.status = FAILED with an
  approved reason code in agent_runs.error.
- All screening-path exceptions are sanitized before reaching record_agent_run()
  to ensure no customer data, watchlist data, or raw exception strings are leaked.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from meridian.agents.sanctions.errors import (
    NormalizationVersionMismatch,
    WatchlistIntegrityViolation,
    WatchlistValidationError,
)
from meridian.agents.sanctions.matching import match_customer_against_watchlist
from meridian.agents.sanctions.reader import read_watchlist_version
from meridian.agents.sanctions.types import (
    SanctionsMatchResult,
)
from meridian.orchestration.agent_run_tracking import record_agent_run

# Pinned watchlist constants per ADR-0008 D6 and seeded corpus
PINNED_WATCHLIST_NAME: Final[str] = "meridian_synthetic_watchlist"
PINNED_WATCHLIST_VERSION: Final[str] = "v1"

# Approved ADR-0008 D8 technical failure reason codes
REASON_WATCHLIST_INTEGRITY_VIOLATION: Final[str] = "WATCHLIST_INTEGRITY_VIOLATION"
REASON_NORMALIZATION_VERSION_MISMATCH: Final[str] = "NORMALIZATION_VERSION_MISMATCH"
REASON_DATABASE_ERROR: Final[str] = "DATABASE_ERROR"
REASON_UNEXPECTED_ERROR: Final[str] = "UNEXPECTED_ERROR"

APPROVED_TECHNICAL_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        REASON_WATCHLIST_INTEGRITY_VIOLATION,
        REASON_NORMALIZATION_VERSION_MISMATCH,
        REASON_DATABASE_ERROR,
        REASON_UNEXPECTED_ERROR,
    }
)

# Static tool-calls summary for SanctionsAgent (ADR-0008 D6, F9 convention).
# Coarse, static description of queries; free of customer or watchlist data.
_SANCTIONS_AGENT_TOOL_CALLS: Final[dict[str, Any]] = {
    "tool": "sql_query",
    "queries": [
        "customers: lookup customer full_name and date_of_birth by customer_id",
        "watchlist_entries: read pinned watchlist version entries",
    ],
}


class SanctionsDispatchError(Exception):
    """Sanitized technical exception raised by SanctionsAgent dispatch.

    Its string representation is strictly one of the approved ADR-0008 reason codes.
    It contains no customer names, watchlist data, SQL fragments, or raw exceptions.
    """

    def __init__(self, reason_code: str) -> None:
        clean_code = (
            reason_code
            if reason_code in APPROVED_TECHNICAL_ERROR_CODES
            else REASON_UNEXPECTED_ERROR
        )
        super().__init__(clean_code)
        self.reason_code = clean_code

    def __str__(self) -> str:
        return self.reason_code

    def __repr__(self) -> str:
        return f"SanctionsDispatchError({self.reason_code!r})"


@dataclass(frozen=True)
class SanctionsAgentDispatchResult:
    """Result of the SanctionsAgent dispatch."""

    investigation_run_id: uuid.UUID
    result: SanctionsMatchResult
    agent_run_id: uuid.UUID | None = None


def _sanitize_and_classify_exception(exc: BaseException) -> SanctionsDispatchError:
    """Classify an arbitrary exception into a sanitized SanctionsDispatchError."""
    if isinstance(exc, SanctionsDispatchError):
        return exc
    if isinstance(exc, (WatchlistIntegrityViolation, WatchlistValidationError)):
        return SanctionsDispatchError(REASON_WATCHLIST_INTEGRITY_VIOLATION)
    if isinstance(exc, NormalizationVersionMismatch):
        return SanctionsDispatchError(REASON_NORMALIZATION_VERSION_MISMATCH)
    if isinstance(exc, SQLAlchemyError):
        return SanctionsDispatchError(REASON_DATABASE_ERROR)
    return SanctionsDispatchError(REASON_UNEXPECTED_ERROR)


def run_sanctions_agent(
    engine: Engine,
    investigation_run_id: uuid.UUID,
    customer_id: uuid.UUID,
    agent_run_id: uuid.UUID | None = None,
) -> SanctionsAgentDispatchResult:
    """Run SanctionsAgent screening and record execution via record_agent_run().

    Args:
        engine: Application-role SQLAlchemy Engine.
        investigation_run_id: UUID of the current investigation run.
        customer_id: UUID of the customer to screen.
        agent_run_id: Optional UUID to use for this agent run.

    Returns:
        SanctionsAgentDispatchResult holding investigation_run_id and the
        domain SanctionsMatchResult (including controlled abstentions).

    Raises:
        SanctionsDispatchError: When a technical failure occurs during screening.
    """

    def _execute_screening() -> SanctionsMatchResult:
        try:
            # 1. Validate customer_id argument
            if customer_id is None:
                raise SanctionsDispatchError(REASON_UNEXPECTED_ERROR) from None
            if not isinstance(customer_id, uuid.UUID):
                try:
                    cid = uuid.UUID(str(customer_id))
                except (ValueError, TypeError, AttributeError):
                    raise SanctionsDispatchError(REASON_UNEXPECTED_ERROR) from None
            else:
                cid = customer_id

            # 2. Fetch customer row using parameterized query
            try:
                with engine.connect() as conn:
                    row = conn.execute(
                        text(
                            "SELECT full_name, date_of_birth "
                            "FROM customers "
                            "WHERE customer_id = :cid"
                        ),
                        {"cid": cid},
                    ).fetchone()
            except SQLAlchemyError:
                raise SanctionsDispatchError(REASON_DATABASE_ERROR) from None
            except Exception as e:
                raise _sanitize_and_classify_exception(e) from None

            if row is None:
                # Nonexistent customer is a technical failure,
                # not a controlled abstention
                raise SanctionsDispatchError(REASON_UNEXPECTED_ERROR) from None

            customer_name: str | None = row.full_name
            customer_dob = row.date_of_birth

            # 3. Read pinned watchlist version
            try:
                watchlist_read_result = read_watchlist_version(
                    engine,
                    PINNED_WATCHLIST_NAME,
                    PINNED_WATCHLIST_VERSION,
                )
            except Exception as e:
                raise _sanitize_and_classify_exception(e) from None

            # 4. Match customer against watchlist
            try:
                return match_customer_against_watchlist(
                    customer_name,
                    customer_dob,
                    watchlist_read_result,
                )
            except Exception as e:
                raise _sanitize_and_classify_exception(e) from None

        except SanctionsDispatchError:
            raise
        except (WatchlistIntegrityViolation, WatchlistValidationError):
            raise SanctionsDispatchError(
                REASON_WATCHLIST_INTEGRITY_VIOLATION
            ) from None
        except NormalizationVersionMismatch:
            raise SanctionsDispatchError(
                REASON_NORMALIZATION_VERSION_MISMATCH
            ) from None
        except SQLAlchemyError:
            raise SanctionsDispatchError(REASON_DATABASE_ERROR) from None
        except Exception:
            raise SanctionsDispatchError(REASON_UNEXPECTED_ERROR) from None

    # Execute wrapped in record_agent_run()
    match_result = record_agent_run(
        engine,
        investigation_run_id,
        "SanctionsAgent",
        _execute_screening,
        tool_calls=_SANCTIONS_AGENT_TOOL_CALLS,
        agent_run_id=agent_run_id,
    )

    return SanctionsAgentDispatchResult(
        investigation_run_id=investigation_run_id,
        result=match_result,
        agent_run_id=agent_run_id,
    )
