"""Error hierarchy for alert intake and case management operations."""


class AlertIntakeError(Exception):
    """Base exception for alert intake operations."""


class AlertValidationError(AlertIntakeError):
    """Raised when alert intake input validation fails.

    Covers: missing/invalid customer_id, empty/invalid alert_type,
    invalid alert_reasons, malformed UUIDs, nonexistent customer,
    and transaction ownership failures.
    """
