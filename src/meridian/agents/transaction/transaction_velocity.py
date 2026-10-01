"""Transaction velocity signal computation (F3 Slice 2).

Computes the number of outgoing transactions made by the customer in the
trailing 24 hours (inclusive of the alerted transaction).

There is intentionally NO Unknown result type: the count always exists because
the alerted transaction itself is counted. Invalid inputs raise exceptions as in
amount_deviation.
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

# PROTOTYPE signal-definition parameter, NOT a risk threshold;
# subject to revisiting at calibration.
VELOCITY_WINDOW_HOURS: Final[int] = 24


@dataclass(frozen=True)
class TransactionVelocityComputed:
    """Result for transaction velocity."""
    alerted_transaction_id: uuid.UUID
    source_account_id: uuid.UUID
    window_hours: int
    window_start: datetime
    window_end: datetime
    transaction_count: int
    source_transaction_ids: tuple[uuid.UUID, ...]


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


def compute_transaction_velocity(
    engine: Engine,
    transaction_id: uuid.UUID | str,
) -> TransactionVelocityComputed:
    """Compute the alerted transaction's velocity (outgoing txns in 24h window).

    Args:
        engine: Application-role SQLAlchemy Engine (read-only access).
        transaction_id: UUID of the alerted transaction.

    Returns:
        TransactionVelocityComputed with the count and source transaction IDs.

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
                "SELECT transaction_id, source_account_id, occurred_at "
                "FROM transactions WHERE transaction_id = :tid"
            ),
            {"tid": tid},
        ).fetchone()

        if alerted_row is None:
            raise TransactionNotFoundError(
                f"Transaction {tid} does not exist."
            )

        source_account_id = alerted_row[1]
        alerted_occurred_at = alerted_row[2]

        if source_account_id is None:
            raise InvalidTransactionError(
                "transaction has no source_account_id"
            )

        customer_row = conn.execute(
            text(
                "SELECT customer_id FROM accounts "
                "WHERE account_id = :source_account_id"
            ),
            {"source_account_id": source_account_id},
        ).fetchone()

        if customer_row is None:
            raise InvalidTransactionError(
                f"Source account {source_account_id} cannot be resolved to a customer."
            )

        customer_id: uuid.UUID = customer_row[0]
        window_start = alerted_occurred_at - timedelta(hours=VELOCITY_WINDOW_HOURS)

        history_rows = conn.execute(
            text(
                "SELECT t.transaction_id "
                "FROM transactions t "
                "JOIN accounts a ON a.account_id = t.source_account_id "
                "WHERE a.customer_id = :customer_id "
                "  AND t.occurred_at >= :window_start "
                "  AND t.occurred_at <= :alerted_occurred_at "
                "ORDER BY t.occurred_at ASC, t.transaction_id ASC"
            ),
            {
                "customer_id": customer_id,
                "window_start": window_start,
                "alerted_occurred_at": alerted_occurred_at,
            },
        ).fetchall()

        source_ids: tuple[uuid.UUID, ...] = tuple(row[0] for row in history_rows)

        return TransactionVelocityComputed(
            alerted_transaction_id=tid,
            source_account_id=source_account_id,
            window_hours=VELOCITY_WINDOW_HOURS,
            window_start=window_start,
            window_end=alerted_occurred_at,
            transaction_count=len(source_ids),
            source_transaction_ids=source_ids,
        )
