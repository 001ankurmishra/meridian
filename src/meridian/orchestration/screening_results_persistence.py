"""Persistence layer for F11 screening_results records.

This module implements the Stage 2a persistence function for storing sanctions
and watchlist screening results according to ADR-0008 D7, D8, and D9.
It operates within the caller's transaction on a caller-owned SQLAlchemy
Connection, enforces Python-level validation and agent-run guard verification,
and executes parameterized SQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Final

from sqlalchemy import Connection, text

from meridian.agents.sanctions.types import (
    AbstentionReason,
    ScreeningOutcome,
)

# Supported outcomes and reason codes per ADR-0008 D7 / D8
_VALID_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        ScreeningOutcome.CANDIDATE_MATCHES_FOUND.value,
        ScreeningOutcome.NO_CANDIDATE_MATCH.value,
        ScreeningOutcome.NOT_PERFORMED.value,
    }
)

_VALID_ABSTENTION_REASONS: Final[frozenset[str]] = frozenset(
    {
        AbstentionReason.CUSTOMER_NAME_MISSING.value,
        AbstentionReason.CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION.value,
        AbstentionReason.WATCHLIST_VERSION_NOT_LOADED.value,
    }
)


class InvalidScreeningResultInputError(ValueError):
    """Raised when screening result inputs fail validation before database access.

    Exception messages intentionally omit customer names, watchlist names,
    and untrusted outcome or reason_code values to prevent sensitive data
    leakage into logs or exception traces.
    """


class AgentRunGuardError(ValueError):
    """Raised when the referenced agent_runs row fails verification.

    Raised if the row is missing, belongs to a different agent or investigation,
    or does not have status = 'SUCCESS'. Exception messages intentionally omit
    customer names and watchlist names.
    """


def record_screening_result(
    conn: Connection,
    *,
    investigation_run_id: uuid.UUID,
    agent_run_id: uuid.UUID,
    customer_id: uuid.UUID,
    outcome: str | ScreeningOutcome,
    reason_code: str | AbstentionReason | None,
    candidate_count: int,
    watchlist_name: str,
    watchlist_version: str,
    matching_rule_id: str,
    normalization_version: str,
    screening_result_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Persist a single screening result row within an existing transaction.

    Stage 2a implementation (unwired): writes a row to `screening_results` after
    verifying input validity and the existence of a corresponding successful
    SanctionsAgent `agent_runs` record.

    Limitation note: In Stage 2a, `candidate_count` cannot be cross-checked
    against authored findings because candidate findings are created downstream
    in Stage 2b authoring. Full findings consistency checking is deferred to
    Stage 2b.

    Args:
        conn: Caller-owned SQLAlchemy Connection. This function does NOT
            begin, commit, roll back, or close a transaction.
        investigation_run_id: UUID of the investigation run.
        agent_run_id: UUID of the SanctionsAgent agent_run that produced this
            result.
        customer_id: UUID of the screened customer.
        outcome: Domain outcome string or ScreeningOutcome enum. Must be one of
            'CANDIDATE_MATCHES_FOUND', 'NO_CANDIDATE_MATCH', or 'NOT_PERFORMED'.
        reason_code: Controlled abstention reason string or AbstentionReason
            enum. Must be non-None if and only if outcome is 'NOT_PERFORMED'.
        candidate_count: Non-negative integer count of matched candidate
            records. Must be > 0 if and only if outcome is
            'CANDIDATE_MATCHES_FOUND'.
        watchlist_name: Non-empty name identifier of the screened watchlist.
        watchlist_version: Non-empty version identifier of the screened
            watchlist.
        matching_rule_id: Non-empty rule identifier used for matching.
        normalization_version: Non-empty normalization version string.
        screening_result_id: Optional explicit UUID for the result record.
            If omitted, a random UUID4 is generated.

    Returns:
        UUID of the persisted screening_result record.

    Raises:
        InvalidScreeningResultInputError: If any argument fails validation
            (unsupported outcome, invalid reason_code, inconsistent
            candidate_count, empty string identifiers, or invalid UUID types)
            prior to database interaction.
        AgentRunGuardError: If the referenced agent_run does not exist, has an
            unexpected agent name (not 'SanctionsAgent'), belongs to a different
            investigation_run_id, or has a status other than 'SUCCESS'.
        sqlalchemy.exc.IntegrityError: If unique constraints
            (uq_screening_results_investigation_run_id or
            uq_screening_results_agent_run_id) or foreign key constraints
            are violated at the database layer. Database integrity errors
            propagate unchanged.

    Side effects:
        Executes a SELECT query on `agent_runs` and an INSERT query on
        `screening_results` using the supplied connection. Does not commit
        or roll back.
    """
    # -------------------------------------------------------------------------
    # A. Validate inputs in Python before INSERT
    # -------------------------------------------------------------------------

    # Validate UUID types
    for param_name, param_val in [
        ("investigation_run_id", investigation_run_id),
        ("agent_run_id", agent_run_id),
        ("customer_id", customer_id),
    ]:
        if not isinstance(param_val, uuid.UUID):
            raise InvalidScreeningResultInputError(
                f"{param_name} must be a valid uuid.UUID instance"
            )

    if screening_result_id is not None and not isinstance(
        screening_result_id, uuid.UUID
    ):
        raise InvalidScreeningResultInputError(
            "screening_result_id must be a valid uuid.UUID instance"
        )

    # Validate string attributes (ensure non-empty without leaking values in messages)
    for field_name, str_val in [
        ("watchlist_name", watchlist_name),
        ("watchlist_version", watchlist_version),
        ("matching_rule_id", matching_rule_id),
        ("normalization_version", normalization_version),
    ]:
        if not isinstance(str_val, str) or not str_val.strip():
            raise InvalidScreeningResultInputError(
                f"{field_name} must be a non-empty string"
            )

    # Validate and normalize outcome
    if not isinstance(outcome, (str, ScreeningOutcome)):
        raise InvalidScreeningResultInputError(
            "outcome must be a str or ScreeningOutcome instance"
        )

    outcome_str: str = (
        outcome.value if isinstance(outcome, ScreeningOutcome) else outcome
    )
    if outcome_str not in _VALID_OUTCOMES:
        raise InvalidScreeningResultInputError(
            f"Unsupported outcome; must be one of {sorted(_VALID_OUTCOMES)}"
        )

    # Validate and normalize reason_code
    if reason_code is not None and not isinstance(reason_code, (str, AbstentionReason)):
        raise InvalidScreeningResultInputError(
            "reason_code must be a str, AbstentionReason instance, or None"
        )

    reason_code_str: str | None
    if isinstance(reason_code, AbstentionReason):
        reason_code_str = reason_code.value
    elif isinstance(reason_code, str):
        reason_code_str = reason_code
    else:
        reason_code_str = None

    if outcome_str == ScreeningOutcome.NOT_PERFORMED.value:
        if reason_code_str is None:
            raise InvalidScreeningResultInputError(
                "reason_code must be provided when outcome is NOT_PERFORMED"
            )
        if reason_code_str not in _VALID_ABSTENTION_REASONS:
            raise InvalidScreeningResultInputError(
                f"Unsupported reason_code; must be one of "
                f"{sorted(_VALID_ABSTENTION_REASONS)}"
            )
    else:
        if reason_code_str is not None:
            raise InvalidScreeningResultInputError(
                f"reason_code must be None when outcome is '{outcome_str}'"
            )

    # Validate candidate_count (reject bool which is a subclass of int)
    if isinstance(candidate_count, bool) or not isinstance(candidate_count, int):
        raise InvalidScreeningResultInputError("candidate_count must be an integer")

    if candidate_count < 0:
        raise InvalidScreeningResultInputError(
            f"candidate_count must be non-negative, got {candidate_count}"
        )

    if outcome_str == ScreeningOutcome.CANDIDATE_MATCHES_FOUND.value:
        if candidate_count <= 0:
            raise InvalidScreeningResultInputError(
                "candidate_count must be > 0 when outcome is CANDIDATE_MATCHES_FOUND"
            )
    else:
        if candidate_count != 0:
            raise InvalidScreeningResultInputError(
                f"candidate_count must be 0 when outcome is '{outcome_str}', "
                f"got {candidate_count}"
            )

    # -------------------------------------------------------------------------
    # B. Verify referenced agent_runs row
    # -------------------------------------------------------------------------
    guard_row = conn.execute(
        text(
            "SELECT agent_name, investigation_run_id, status "
            "FROM agent_runs "
            "WHERE agent_run_id = :agent_run_id"
        ),
        {"agent_run_id": agent_run_id},
    ).fetchone()

    if guard_row is None:
        raise AgentRunGuardError(
            f"Referenced agent_run_id '{agent_run_id}' does not exist in agent_runs"
        )

    agent_name, referenced_inv_run_id, agent_status = guard_row

    if agent_name != "SanctionsAgent":
        raise AgentRunGuardError(
            f"Referenced agent_run_id '{agent_run_id}' has agent_name '{agent_name}'; "
            "expected 'SanctionsAgent'"
        )

    if referenced_inv_run_id != investigation_run_id:
        raise AgentRunGuardError(
            f"Referenced agent_run_id '{agent_run_id}' belongs to investigation_run_id "
            f"'{referenced_inv_run_id}', which does not match supplied "
            f"investigation_run_id '{investigation_run_id}'"
        )

    if agent_status != "SUCCESS":
        raise AgentRunGuardError(
            f"Referenced agent_run_id '{agent_run_id}' has status '{agent_status}'; "
            "expected 'SUCCESS'"
        )

    # -------------------------------------------------------------------------
    # C. Insert the screening result
    # -------------------------------------------------------------------------
    persisted_id = (
        screening_result_id if screening_result_id is not None else uuid.uuid4()
    )
    now = datetime.now(timezone.utc)

    conn.execute(
        text(
            """
            INSERT INTO screening_results (
                screening_result_id,
                investigation_run_id,
                agent_run_id,
                customer_id,
                outcome,
                reason_code,
                candidate_count,
                watchlist_name,
                watchlist_version,
                matching_rule_id,
                normalization_version,
                created_at
            ) VALUES (
                :screening_result_id,
                :investigation_run_id,
                :agent_run_id,
                :customer_id,
                :outcome,
                :reason_code,
                :candidate_count,
                :watchlist_name,
                :watchlist_version,
                :matching_rule_id,
                :normalization_version,
                :created_at
            )
            """
        ),
        {
            "screening_result_id": persisted_id,
            "investigation_run_id": investigation_run_id,
            "agent_run_id": agent_run_id,
            "customer_id": customer_id,
            "outcome": outcome_str,
            "reason_code": reason_code_str,
            "candidate_count": candidate_count,
            "watchlist_name": watchlist_name,
            "watchlist_version": watchlist_version,
            "matching_rule_id": matching_rule_id,
            "normalization_version": normalization_version,
            "created_at": now,
        },
    )

    return persisted_id
