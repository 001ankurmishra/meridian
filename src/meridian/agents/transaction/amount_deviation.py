"""Compute the deviation of an alerted transaction's amount from the trailing
90-day average of the customer's outgoing transactions.

Inputs: engine (application-role SQLAlchemy Engine), transaction_id.
Outputs: AmountDeviationComputed if >=1 qualifying historical transaction
    exists; AmountDeviationUnknown otherwise.
Side effects: none (read-only, no writes).
Failure modes:
  - TransactionNotFoundError if transaction_id does not exist.
  - InvalidTransactionError if the transaction has no source_account_id,
    or its source account cannot be resolved to a customer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Engine, text

from meridian.agents.transaction.errors import (
    InvalidTransactionError,
    TransactionNotFoundError,
)


@dataclass(frozen=True)
class AmountDeviationComputed:
    """Result when qualifying historical transactions exist."""

    alerted_transaction_id: uuid.UUID
    alerted_amount: Decimal
    historical_average: Decimal
    deviation_multiple: Decimal
    historical_transaction_count: int
    source_transaction_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class AmountDeviationUnknown:
    """Result when deviation cannot be computed."""

    alerted_transaction_id: uuid.UUID
    reason: str


AmountDeviationResult = AmountDeviationComputed | AmountDeviationUnknown


def _validate_transaction_id(transaction_id: uuid.UUID | str) -> uuid.UUID:
    """Coerce and validate transaction_id to a uuid.UUID.

    Accepts uuid.UUID or a coercible string. Raises InvalidTransactionError
    for anything else, before any database query.
    """
    if isinstance(transaction_id, uuid.UUID):
        return transaction_id
    try:
        return uuid.UUID(str(transaction_id))
    except (ValueError, AttributeError) as exc:
        raise InvalidTransactionError(
            f"transaction_id is not a valid UUID: {transaction_id!r}"
        ) from exc


def compute_amount_deviation(
    engine: Engine,
    transaction_id: uuid.UUID,
) -> AmountDeviationResult:
    """Compute the alerted transaction's deviation from the customer's
    trailing 90-day outgoing transaction average.

    Args:
        engine: Application-role SQLAlchemy Engine (read-only access).
        transaction_id: UUID of the alerted transaction.

    Returns:
        AmountDeviationComputed if >=1 qualifying historical transaction
        exists; AmountDeviationUnknown otherwise.

    Raises:
        InvalidTransactionError: If transaction_id is not a valid UUID,
            the transaction has no source_account_id, or its source
            account cannot be resolved to a customer.
        TransactionNotFoundError: If transaction_id does not exist.
    """
    # 1. Validate transaction_id (before any query)
    tid = _validate_transaction_id(transaction_id)

    with engine.connect() as conn:
        # 2. Fetch the alerted transaction
        alerted_row = conn.execute(
            text(
                "SELECT transaction_id, source_account_id, amount, occurred_at "
                "FROM transactions WHERE transaction_id = :tid"
            ),
            {"tid": tid},
        ).fetchone()

        if alerted_row is None:
            raise TransactionNotFoundError(
                f"Transaction {tid} does not exist."
            )

        source_account_id = alerted_row[1]
        alerted_amount: Decimal = alerted_row[2]
        alerted_occurred_at = alerted_row[3]

        # 3. source_account_id must not be NULL
        if source_account_id is None:
            raise InvalidTransactionError(
                "transaction has no source_account_id; amount deviation "
                "requires an outgoing transaction from a customer account"
            )

        # 4. Resolve source account to customer
        customer_row = conn.execute(
            text(
                "SELECT customer_id FROM accounts "
                "WHERE account_id = :source_account_id"
            ),
            {"source_account_id": source_account_id},
        ).fetchone()

        if customer_row is None:
            raise InvalidTransactionError(
                f"Source account {source_account_id} cannot be resolved "
                f"to a customer."
            )

        customer_id: uuid.UUID = customer_row[0]

        # 5. Qualifying history query
        history_rows = conn.execute(
            text(
                "SELECT t.transaction_id, t.amount "
                "FROM transactions t "
                "JOIN accounts a ON a.account_id = t.source_account_id "
                "WHERE a.customer_id = :customer_id "
                "  AND t.occurred_at >= :alerted_occurred_at - INTERVAL '90 days' "
                "  AND t.occurred_at < :alerted_occurred_at "
                "  AND t.transaction_id != :alerted_transaction_id"
            ),
            {
                "customer_id": customer_id,
                "alerted_occurred_at": alerted_occurred_at,
                "alerted_transaction_id": tid,
            },
        ).fetchall()

        # 6. Zero qualifying rows
        if len(history_rows) == 0:
            return AmountDeviationUnknown(
                alerted_transaction_id=tid,
                reason=(
                    "no qualifying historical transactions in the "
                    "90-day trailing window"
                ),
            )

        # 7. Compute average in Python from returned Decimal amounts
        amounts: list[Decimal] = [row[1] for row in history_rows]
        source_ids: tuple[uuid.UUID, ...] = tuple(
            row[0] for row in history_rows
        )
        historical_average = sum(amounts, Decimal("0")) / len(amounts)

        # 8. Zero average
        if historical_average == 0:
            return AmountDeviationUnknown(
                alerted_transaction_id=tid,
                reason=(
                    "historical average is zero; deviation multiple "
                    "is undefined"
                ),
            )

        # 9. Compute deviation multiple
        deviation_multiple = alerted_amount / historical_average

        # 10. Return computed result
        return AmountDeviationComputed(
            alerted_transaction_id=tid,
            alerted_amount=alerted_amount,
            historical_average=historical_average,
            deviation_multiple=deviation_multiple,
            historical_transaction_count=len(history_rows),
            source_transaction_ids=source_ids,
        )
