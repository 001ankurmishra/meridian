"""Error hierarchy for amount deviation analysis operations."""


class AmountDeviationError(Exception):
    """Base exception for amount deviation operations."""


class TransactionNotFoundError(AmountDeviationError):
    """Raised when the specified transaction does not exist."""


class InvalidTransactionError(AmountDeviationError):
    """Raised when the transaction is unsuitable for amount deviation analysis.

    Covers: missing source_account_id, unresolvable customer for the
    source account, malformed transaction_id inputs.
    """
