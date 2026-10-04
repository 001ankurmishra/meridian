"""Entity resolution logic."""

from .matching import (
    MATCHED_FIELDS,
    NORMALIZATION_VERSION,
    RULE_ID,
    CandidateLink,
    CustomerIdentityRecord,
    IneligibleRecord,
    ResolutionResult,
    compute_er_candidates,
    find_candidate_links,
)

__all__ = [
    "MATCHED_FIELDS",
    "NORMALIZATION_VERSION",
    "RULE_ID",
    "CandidateLink",
    "CustomerIdentityRecord",
    "IneligibleRecord",
    "ResolutionResult",
    "compute_er_candidates",
    "find_candidate_links",
]
