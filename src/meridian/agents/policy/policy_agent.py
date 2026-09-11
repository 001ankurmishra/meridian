import uuid
from dataclasses import dataclass
from typing import List, Union

from sqlalchemy.orm import Session

from meridian.agents.policy.retrieval import retrieve_candidates


@dataclass(frozen=True)
class PolicyCitation:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    document_type: str
    version: str
    is_synthetic: bool
    chunk_index: int
    chunk_text: str
    rrf_score: float


@dataclass(frozen=True)
class PolicyEvidenceFound:
    citations: List[PolicyCitation]


@dataclass(frozen=True)
class PolicyEvidenceInsufficient:
    pass


PolicyAgentResult = Union[PolicyEvidenceFound, PolicyEvidenceInsufficient]


def retrieve_policy_evidence(
    session: Session,
    query: str,
    k: int = 60,
    top_k: int = 5,
    # PROTOTYPE-tier threshold. Requires calibration via labeled query set
    # per docs/EVALUATION.md §4. NOT a final or evaluated threshold.
    confidence_threshold: float = 0.01,
) -> PolicyAgentResult:
    """
    Retrieves policy evidence candidates and applies a minimum confidence threshold.
    Returns PolicyEvidenceFound with citations if any meet the threshold,
    otherwise PolicyEvidenceInsufficient.
    """
    candidates = retrieve_candidates(session, query, k=k, top_k=top_k)

    citations = []
    for candidate in candidates:
        if candidate["rrf_score"] >= confidence_threshold:
            citations.append(
                PolicyCitation(
                    chunk_id=candidate["chunk_id"],
                    document_id=candidate["document_id"],
                    title=candidate["title"],
                    document_type=candidate["document_type"],
                    version=candidate["version"],
                    is_synthetic=candidate["is_synthetic"],
                    chunk_index=candidate["chunk_index"],
                    chunk_text=candidate["chunk_text"],
                    rrf_score=candidate["rrf_score"],
                )
            )

    if not citations:
        return PolicyEvidenceInsufficient()

    return PolicyEvidenceFound(citations=citations)
