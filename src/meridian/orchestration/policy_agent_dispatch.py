"""PolicyAgent dispatch slice."""
import uuid

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from meridian.agents.policy.policy_agent import (
    PolicyAgentResult,
    retrieve_policy_evidence,
)
from meridian.orchestration.agent_run_tracking import record_agent_run


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
    )
