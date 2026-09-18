"""PolicyAgent dispatch slice."""

import uuid

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from meridian.agents.policy.policy_agent import (
    PolicyAgentResult,
    retrieve_policy_evidence,
)
from meridian.orchestration.agent_run_tracking import record_agent_run

# Coarse, per-agent-run tool-call summary for PolicyAgent (F9).
# Describes the fixed, deterministic hybrid retrieval PolicyAgent is
# documented (docs/ARCHITECTURE.md #4.4, ADR-0004) to perform -- not a
# live trace of any individual invocation.
_POLICY_AGENT_TOOL_CALLS = {
    "tool": "hybrid_retrieval",
    "queries": [
        "document_chunks: PostgreSQL full-text search (FTS) candidates",
        "document_chunks: pgvector cosine-distance candidates",
        "reciprocal_rank_fusion: merge FTS and vector candidate rankings",
    ],
}


def run_policy_agent(
    engine: Engine,
    investigation_run_id: uuid.UUID,
    query: str,
) -> PolicyAgentResult:
    """Run PolicyAgent and record the invocation.

    Args:
        engine: Database engine.
        investigation_run_id: ID of the investigation run to attach this agent run to.
        query: The user-supplied query string for policy retrieval.

    Returns:
        The exact result from the PolicyAgent domain layer.
    """

    def _do_retrieve() -> PolicyAgentResult:
        with Session(engine) as session:
            return retrieve_policy_evidence(session, query)

    return record_agent_run(
        engine,
        investigation_run_id,
        "PolicyAgent",
        _do_retrieve,
        tool_calls=_POLICY_AGENT_TOOL_CALLS,
    )
