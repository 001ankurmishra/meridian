"""GraphAgent dispatch slice."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Engine

from meridian.agents.graph.subgraph import (
    SubgraphResult,
    get_bounded_subgraph,
    get_entity_id_for_account,
)
from meridian.agents.graph.structure_signals import (
    CycleResult,
    ChainDepthResult,
    compute_cycle_through_account,
    compute_outbound_chain_depth,
)
from meridian.orchestration.agent_run_tracking import record_agent_run

# Coarse, per-agent-run tool-call summary for GraphAgent (F9).
# This describes the fixed, deterministic set of SQL queries
# the primitive operations are known to run.
_GRAPH_AGENT_TOOL_CALLS = {
    "tool": "sql_query",
    "queries": [
        "entities: resolve account_id to entity_id",
        "graph_relationships: bounded undirected reachability "
        "and directed edge extraction",
        "graph_relationships: compute cycle through account",
        "graph_relationships: compute outbound chain depth",
    ],
}


@dataclass(frozen=True)
class GraphAgentExecutionResult:
    """Internal execution result wrapping multiple graph outputs."""
    subgraph: SubgraphResult
    cycle: CycleResult
    chain: ChainDepthResult


@dataclass(frozen=True)
class GraphAgentDispatchResult:
    """Result of the GraphAgent dispatch."""

    investigation_run_id: uuid.UUID
    result: SubgraphResult
    cycle_result: CycleResult
    chain_result: ChainDepthResult


def _execute_graph_agent(
    engine: Engine,
    account_id: uuid.UUID,
    max_hops: int,
) -> GraphAgentExecutionResult:
    """Helper to execute the graph operations.

    1. Resolves the account to its entity_id.
    2. Runs the bounded subgraph retrieval.
    3. Computes cycle through account.
    4. Computes outbound chain depth.
    """
    entity_id = get_entity_id_for_account(engine, account_id)
    subgraph = get_bounded_subgraph(engine, entity_id, max_hops)
    cycle = compute_cycle_through_account(engine, account_id)
    chain = compute_outbound_chain_depth(engine, account_id)
    return GraphAgentExecutionResult(subgraph=subgraph, cycle=cycle, chain=chain)


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
    exec_result = record_agent_run(
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
        result=exec_result.subgraph,
        cycle_result=exec_result.cycle,
        chain_result=exec_result.chain,
    )
