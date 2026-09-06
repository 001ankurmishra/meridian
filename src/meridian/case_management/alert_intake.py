"""Alert intake: validate input, create an alert and its linked case atomically.

This module implements the F1 "Alert Intake" feature of the case_management
module. It follows the established loader pattern: parameterized
sqlalchemy.text() statements within engine.begin() for atomic operations.

Inputs: customer_id, alert_type, alert_reasons, optional transaction_id,
        optional source_system, optional raised_at.
Outputs: AlertIntakeResult (alert_id, case_id).
Side effects: One INSERT into alerts, one INSERT into cases.
Failure modes:
  - AlertValidationError for any input or database-validation failure.
  - Underlying SQLAlchemy/database exceptions propagate unchanged.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Engine, create_engine, text

from meridian.case_management.errors import AlertValidationError
from meridian.config import settings


@dataclass(frozen=True)
class AlertIntakeResult:
    """Result of a successful alert-and-case creation."""

    alert_id: uuid.UUID
    case_id: uuid.UUID


def get_app_engine() -> Engine:
    """Construct the application-role database engine.

    Uses settings.app_database_url exclusively. Raises RuntimeError if
    the URL is not configured. Never falls back to settings.database_url.
    """
    if settings.app_database_url is None:
        raise RuntimeError(
            "APP_DATABASE_URL is not configured. Cannot construct "
            "application database engine."
        )
    return create_engine(settings.app_database_url, pool_pre_ping=True)


def _validate_inputs(
    customer_id: uuid.UUID | None,
    alert_type: str,
    alert_reasons: dict[str, Any] | list[Any],
    transaction_id: uuid.UUID | None,
) -> None:
    """Validate all inputs before touching the database.

    Raises AlertValidationError for any invalid input.
    """
    # 1. customer_id: required, must be a valid UUID
    if customer_id is None:
        raise AlertValidationError("customer_id is required and cannot be None.")
    if not isinstance(customer_id, uuid.UUID):
        try:
            uuid.UUID(str(customer_id))
        except (ValueError, AttributeError):
            raise AlertValidationError(
                f"customer_id is not a valid UUID: {customer_id!r}"
            )

    # 2. alert_type: required, must be a non-empty string after stripping
    if not isinstance(alert_type, str):
        raise AlertValidationError(
            f"alert_type must be a string, got {type(alert_type).__name__}."
        )
    if not alert_type.strip():
        raise AlertValidationError(
            "alert_type must be a non-empty string after stripping whitespace."
        )

    # 3. alert_reasons: required, must be a non-empty dict or list, JSON-serializable
    if not isinstance(alert_reasons, (dict, list)):
        raise AlertValidationError(
            f"alert_reasons must be a dict or list, got {type(alert_reasons).__name__}."
        )
    if len(alert_reasons) == 0:
        raise AlertValidationError("alert_reasons must not be empty.")
    try:
        json.dumps(alert_reasons)
    except (TypeError, ValueError) as exc:
        raise AlertValidationError(
            f"alert_reasons is not JSON-serializable: {exc}"
        )

    # 4. transaction_id: optional, but if supplied must be a valid UUID
    if transaction_id is not None and not isinstance(transaction_id, uuid.UUID):
        try:
            uuid.UUID(str(transaction_id))
        except (ValueError, AttributeError):
            raise AlertValidationError(
                f"transaction_id is not a valid UUID: {transaction_id!r}"
            )


def create_alert_and_case(
    engine: Engine,
    customer_id: uuid.UUID,
    alert_type: str,
    alert_reasons: dict[str, Any] | list[Any],
    transaction_id: uuid.UUID | None = None,
    source_system: str | None = None,
    raised_at: datetime | None = None,
) -> AlertIntakeResult:
    """Create an alert and its linked case in a single atomic transaction.

    Args:
        engine: SQLAlchemy Engine (must be the application-role engine).
        customer_id: UUID of the customer this alert is for.
        alert_type: Non-empty string identifying the alert type.
        alert_reasons: Non-empty dict or list of reason codes/data (JSON-serializable).
        transaction_id: Optional UUID of the triggering transaction.
        source_system: Optional string identifying the source system. None -> NULL.
        raised_at: Optional datetime. None -> datetime.now(timezone.utc).

    Returns:
        AlertIntakeResult with the created alert_id and case_id.

    Raises:
        AlertValidationError: For any input or database validation failure.
        Other exceptions from SQLAlchemy/database propagate unchanged.
    """
    # Input validation (before touching the database)
    _validate_inputs(customer_id, alert_type, alert_reasons, transaction_id)

    # Generate IDs in Python
    alert_id = uuid.uuid4()
    case_id = uuid.uuid4()

    # Timestamps
    now = datetime.now(timezone.utc)
    effective_raised_at = raised_at if raised_at is not None else now

    # Serialize alert_reasons to JSON string for the parameter
    alert_reasons_json = json.dumps(alert_reasons)

    with engine.begin() as conn:
        # 1. Customer existence validation
        customer_exists = conn.execute(
            text("SELECT 1 FROM customers WHERE customer_id = :customer_id"),
            {"customer_id": customer_id},
        ).scalar()
        if customer_exists is None:
            raise AlertValidationError(
                f"Customer with customer_id={customer_id} does not exist."
            )

        # 2. Transaction existence/ownership validation (if transaction_id given)
        if transaction_id is not None:
            tx_owned = conn.execute(
                text(
                    "SELECT 1 "
                    "FROM transactions t "
                    "JOIN accounts a "
                    "  ON a.account_id = t.source_account_id "
                    "  OR a.account_id = t.destination_account_id "
                    "WHERE t.transaction_id = :transaction_id "
                    "  AND a.customer_id = :customer_id"
                ),
                {
                    "transaction_id": transaction_id,
                    "customer_id": customer_id,
                },
            ).scalar()
            if tx_owned is None:
                raise AlertValidationError(
                    f"Transaction {transaction_id} does not exist or does not "
                    f"belong to customer {customer_id}."
                )

        # 3. INSERT into alerts (RETURNING alert_id)
        returned_alert_id = conn.execute(
            text(
                "INSERT INTO alerts "
                "(alert_id, customer_id, transaction_id, alert_type, "
                "alert_reasons, raised_at, source_system, created_at) "
                "VALUES (:alert_id, :customer_id, :transaction_id, :alert_type, "
                ":alert_reasons, :raised_at, :source_system, :created_at) "
                "RETURNING alert_id"
            ),
            {
                "alert_id": alert_id,
                "customer_id": customer_id,
                "transaction_id": transaction_id,
                "alert_type": alert_type.strip(),
                "alert_reasons": alert_reasons_json,
                "raised_at": effective_raised_at,
                "source_system": source_system,
                "created_at": now,
            },
        ).scalar()

        # 4. INSERT into cases
        conn.execute(
            text(
                "INSERT INTO cases "
                "(case_id, alert_id, status, opened_at, created_at) "
                "VALUES (:case_id, :alert_id, :status, :opened_at, :created_at)"
            ),
            {
                "case_id": case_id,
                "alert_id": returned_alert_id,
                "status": "OPEN",
                "opened_at": now,
                "created_at": now,
            },
        )

    return AlertIntakeResult(alert_id=alert_id, case_id=case_id)
