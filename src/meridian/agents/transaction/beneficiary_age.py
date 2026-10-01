"""Transaction beneficiary age signal computation (F3).

Computes how long the destination account's beneficiary record existed
before the alerted transaction occurred.

Inputs: engine (application-role SQLAlchemy Engine), transaction_id.
Outputs: BeneficiaryAgeComputed if a matching record with a non-null added_at
    is found; BeneficiaryAgeUnknown otherwise.
Side effects: none (read-only, no writes).
Failure modes:
  - TransactionNotFoundError if transaction_id does not exist.
  - InvalidTransactionError if the transaction has no source_account_id,
    or its source account cannot be resolved to a customer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import Engine, text

from meridian.agents.transaction.errors import (
    InvalidTransactionError,
    TransactionNotFoundError,
)

REASON_NO_DESTINATION_ACCOUNT: Final[str] = (
    "transaction has no destination_account_id; beneficiary cannot be resolved"
)
REASON_NO_BENEFICIARY_RECORD: Final[str] = (
    "no matching beneficiary record for this customer and destination account"
)
REASON_ADDED_AT_MISSING: Final[str] = (
    "all matching beneficiary records have a NULL added_at"
)
REASON_ADDED_AFTER_TRANSACTION: Final[str] = (
    "earliest matching beneficiary record was added after the transaction occurred"
)


@dataclass(frozen=True)
class BeneficiaryAgeComputed:
    """Result when the beneficiary age can be computed."""

    alerted_transaction_id: uuid.UUID
    source_account_id: uuid.UUID
    destination_account_id: uuid.UUID
    alerted_occurred_at: datetime
    beneficiary_added_at: datetime
    beneficiary_age: timedelta
    beneficiary_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class BeneficiaryAgeUnknown:
    """Result when the beneficiary age cannot be computed."""

    alerted_transaction_id: uuid.UUID
    source_account_id: uuid.UUID
    reason: str


BeneficiaryAgeResult = BeneficiaryAgeComputed | BeneficiaryAgeUnknown


def _validate_transaction_id(transaction_id: uuid.UUID | str) -> uuid.UUID:
    """Coerce and validate transaction_id to a uuid.UUID.

    Accepts uuid.UUID or a coercible string. Raises InvalidTransactionError
    for anything else, before any database query.
    Note: duplicated from amount_deviation.py
    """
    if isinstance(transaction_id, uuid.UUID):
        return transaction_id
    try:
        return uuid.UUID(str(transaction_id))
    except (ValueError, AttributeError) as exc:
        raise InvalidTransactionError(
            f"transaction_id is not a valid UUID: {transaction_id!r}"
        ) from exc


def compute_beneficiary_age(
    engine: Engine,
    transaction_id: uuid.UUID | str,
) -> BeneficiaryAgeResult:
    """Compute how long the matching beneficiary record existed before the alerted
    transaction occurred.

    Args:
        engine: Application-role SQLAlchemy Engine (read-only access).
        transaction_id: UUID of the alerted transaction.

    Returns:
        BeneficiaryAgeComputed if a matching beneficiary with a valid added_at
        exists; BeneficiaryAgeUnknown otherwise.

    Raises:
        InvalidTransactionError: If transaction_id is not a valid UUID,
            the transaction has no source_account_id, or its source
            account cannot be resolved to a customer.
        TransactionNotFoundError: If transaction_id does not exist.
    """
    tid = _validate_transaction_id(transaction_id)

    with engine.connect() as conn:
        alerted_row = conn.execute(
            text(
                "SELECT transaction_id, source_account_id, "
                "destination_account_id, occurred_at "
                "FROM transactions WHERE transaction_id = :tid"
            ),
            {"tid": tid},
        ).fetchone()

        if alerted_row is None:
            raise TransactionNotFoundError(f"Transaction {tid} does not exist.")

        source_account_id = alerted_row[1]
        destination_account_id = alerted_row[2]
        alerted_occurred_at = alerted_row[3]

        if source_account_id is None:
            raise InvalidTransactionError("transaction has no source_account_id")

        customer_row = conn.execute(
            text(
                "SELECT customer_id FROM accounts WHERE account_id = :source_account_id"
            ),
            {"source_account_id": source_account_id},
        ).fetchone()

        if customer_row is None:
            raise InvalidTransactionError(
                f"Source account {source_account_id} cannot be resolved to a customer."
            )

        customer_id: uuid.UUID = customer_row[0]

        if destination_account_id is None:
            return BeneficiaryAgeUnknown(
                alerted_transaction_id=tid,
                source_account_id=source_account_id,
                reason=REASON_NO_DESTINATION_ACCOUNT,
            )

        ben_rows = conn.execute(
            text(
                "SELECT beneficiary_id, added_at "
                "FROM beneficiaries "
                "WHERE customer_id = :customer_id "
                "  AND account_id = :destination_account_id"
            ),
            {
                "customer_id": customer_id,
                "destination_account_id": destination_account_id,
            },
        ).fetchall()

        if len(ben_rows) == 0:
            return BeneficiaryAgeUnknown(
                alerted_transaction_id=tid,
                source_account_id=source_account_id,
                reason=REASON_NO_BENEFICIARY_RECORD,
            )

        # Sort by beneficiary_id as required
        sorted_rows = sorted(ben_rows, key=lambda row: str(row[0]))
        beneficiary_ids = tuple(row[0] for row in sorted_rows)

        # Get earliest non-null added_at
        non_null_added_ats = [row[1] for row in ben_rows if row[1] is not None]

        if not non_null_added_ats:
            return BeneficiaryAgeUnknown(
                alerted_transaction_id=tid,
                source_account_id=source_account_id,
                reason=REASON_ADDED_AT_MISSING,
            )

        earliest_added_at = min(non_null_added_ats)

        if earliest_added_at > alerted_occurred_at:
            return BeneficiaryAgeUnknown(
                alerted_transaction_id=tid,
                source_account_id=source_account_id,
                reason=REASON_ADDED_AFTER_TRANSACTION,
            )

        return BeneficiaryAgeComputed(
            alerted_transaction_id=tid,
            source_account_id=source_account_id,
            destination_account_id=destination_account_id,
            alerted_occurred_at=alerted_occurred_at,
            beneficiary_added_at=earliest_added_at,
            beneficiary_age=alerted_occurred_at - earliest_added_at,
            beneficiary_ids=beneficiary_ids,
        )
