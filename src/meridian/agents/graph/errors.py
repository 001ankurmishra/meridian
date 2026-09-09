"""Error hierarchy for graph analysis operations."""


class GraphAnalysisError(Exception):
    """Base exception for graph analysis operations."""


class EntityNotFoundError(GraphAnalysisError):
    """Raised when the specified entity does not exist."""


class InvalidGraphInputError(GraphAnalysisError):
    """Raised when graph query inputs are invalid.

    Covers: max_hops < 1, malformed entity IDs.
    """
