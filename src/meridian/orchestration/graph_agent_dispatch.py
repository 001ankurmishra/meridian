"""GraphAgent dispatch slice."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Engine

from meridian.agents.graph.subgraph import (
    SubgraphResult,
    get_bounded_subgraph,
    get_entity_id_for_account,
)
from meridian.orchestration.agent_run_tracking import record_agent_run

# Coarse, per-agent-run tool-call summary for GraphAgent (F11).
# This describes the fixed, deterministic set of SQL queries
# the primitive operations are known to run.
_GRAPH_AGENT_TOOL_CALLS = {
    "tool": "sql_query",
    "queries": [
        "entities: resolve account_id to entity_id",
        "graph_relationships: bounded undirected reachability "
        "and directed edge extraction",
    ],
}


@dataclass(frozen=True)
class GraphAgentDispatchResult:
    """Result of the GraphAgent dispatch."""

    investigation_run_id: uuid.UUID
    result: SubgraphResult


def _execute_graph_agent(
    engine: Engine,
    account_id: uuid.UUID,
    max_hops: int,
) -> SubgraphResult:
    """Helper to execute the graph operations.

    1. Resolves the account to its entity_id.
    2. Runs the bounded subgraph retrieval.
    """
    entity_id = get_entity_id_for_account(engine, account_id)
    return get_bounded_subgraph(engine, entity_id, max_hops)


def run_graph_agent(
    engine: Engine,
    investigation_run_id: uuid.UUID,
    account_id: uuid.UUID,
    max_hops: int,
    agent_run_id: uuid.UUID | None = None,
) -> GraphAgentDispatchResult:
    """Dispatch the GraphAgent for an investigation.

    Args:
        engine: Application-role SQLAlchemy Engine.
        investigation_run_id: The UUID of the active investigation run.
        account_id: The UUID of the account to analyze.
        max_hops: The maximum hops parameter for the bounded subgraph.
        agent_run_id: Optional ID for the agent run.

    Returns:
        A minimal frozen dataclass with the investigation_run_id and the F4 result.
    """
    result = record_agent_run(
        engine,
        investigation_run_id,
        "GraphAgent",
        _execute_graph_agent,
        engine,
        account_id,
        max_hops,
        tool_calls=_GRAPH_AGENT_TOOL_CALLS,
        agent_run_id=agent_run_id,
    )

    return GraphAgentDispatchResult(
        investigation_run_id=investigation_run_id,
        result=result,
    )
