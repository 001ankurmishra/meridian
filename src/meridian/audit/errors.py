class AuditError(Exception):
    """Base class for audit domain errors."""


class CaseNotFoundError(AuditError):
    """Raised when get_case_audit_trail() is asked to reconstruct a case_id
    that does not exist in the `cases` table."""
