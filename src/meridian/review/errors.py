class ReviewError(Exception):
    """Base class for review domain errors."""


class InvalidCaseTransitionError(ReviewError):
    """Requested action is not valid from the case's current status."""


class UnauthorizedDecisionError(ReviewError):
    """Actor is not authorized for the requested action on this case."""


class DecisionValidationError(ReviewError):
    """Input/domain validation failed."""
