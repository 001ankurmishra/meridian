"""Deterministic graph-structure signals (computation only).

These are prototype measurements, not validated real-world performance metrics.
They compute purely structural properties over TRANSACTED_WITH edges.
They do not produce a risk score, risk level, or AML conclusion.
They are computation-only, read-only, and unwired.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Final, Sequence

from sqlalchemy import Engine, text

from meridian.agents.graph.errors import InvalidGraphInputError
from meridian.agents.graph.subgraph import (
    get_bounded_subgraph,
    get_entity_id_for_account,
)

MAX_CYCLE_HOPS: Final[int] = 4
MAX_CHAIN_HOPS: Final[int] = 4


@dataclass(frozen=True)
class CycleFound:
    account_id: uuid.UUID
    cycle_entity_ids: tuple[uuid.UUID, ...]
    cycle_relationship_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class CycleNotFound:
    account_id: uuid.UUID


@dataclass(frozen=True)
class CycleIncompleteTruncated:
    account_id: uuid.UUID


CycleResult = CycleFound | CycleNotFound | CycleIncompleteTruncated


@dataclass(frozen=True)
class ChainDepthComputed:
    account_id: uuid.UUID
    depth: int
    chain_entity_ids: tuple[uuid.UUID, ...]
    chain_relationship_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class ChainDepthIncompleteTruncated:
    account_id: uuid.UUID
    lower_bound_depth: int
    chain_entity_ids: tuple[uuid.UUID, ...]
    chain_relationship_ids: tuple[uuid.UUID, ...]


ChainDepthResult = ChainDepthComputed | ChainDepthIncompleteTruncated


def _validate_uuid(value: object, label: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise InvalidGraphInputError(f"{label} is not a valid UUID: {value!r}") from exc


def compute_cycle_through_account(
    engine: Engine,
    account_id: uuid.UUID,
    max_hops: int = MAX_CYCLE_HOPS,
) -> CycleResult:
    """Compute whether a directed TRANSACTED_WITH cycle exists through the account.

    Uses get_bounded_subgraph for safety. Truncation from non-TRANSACTED_WITH
    edges is conservative.

    Args:
        engine: Read-only SQLAlchemy Engine.
        account_id: The starting account UUID.
        max_hops: Maximum cycle length to search for.

    Returns:
        CycleFound if a cycle exists (even if truncated=True).
        CycleIncompleteTruncated if no cycle is found but graph was truncated.
        CycleNotFound if no cycle exists and graph was not truncated.

    Raises:
        InvalidGraphInputError: If inputs are invalid.
        EntityNotFoundError: If the account does not exist.
    """
    account_id = _validate_uuid(account_id, "account_id")
    if type(max_hops) is not int:
        raise InvalidGraphInputError("max_hops must be an int")
    if max_hops < 2:
        raise InvalidGraphInputError("max_hops must be >= 2 for cycle")

    start_entity_id = get_entity_id_for_account(engine, account_id)
    subgraph = get_bounded_subgraph(engine, start_entity_id, max_hops)

    rel_ids = subgraph.relationship_ids
    if not rel_ids:
        if subgraph.truncated:
            return CycleIncompleteTruncated(account_id=account_id)
        return CycleNotFound(account_id=account_id)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT relationship_id, source_entity_id, "
                "target_entity_id, relationship_type "
                "FROM graph_relationships "
                "WHERE relationship_id = ANY(:rel_ids)"
            ),
            {"rel_ids": list(rel_ids)},
        ).fetchall()

    adj: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]] = {}
    for row in rows:
        r_id: uuid.UUID = row[0]
        u: uuid.UUID = row[1]
        v: uuid.UUID = row[2]
        r_type: str = row[3]

        if r_type != "TRANSACTED_WITH":
            continue
        if u == v:
            continue

        if u not in adj:
            adj[u] = {}

        if v not in adj[u]:
            adj[u][v] = r_id
        else:
            if str(r_id) < str(adj[u][v]):
                adj[u][v] = r_id

    cycles: list[tuple[tuple[uuid.UUID, ...], tuple[uuid.UUID, ...]]] = []
    stack: list[tuple[uuid.UUID, list[uuid.UUID], list[uuid.UUID]]] = [
        (start_entity_id, [start_entity_id], [])
    ]

    while stack:
        curr, p_nodes, p_edges = stack.pop()

        for nxt, edge in adj.get(curr, {}).items():
            if nxt == start_entity_id:
                if 2 <= len(p_edges) + 1 <= max_hops:
                    cycles.append((tuple(p_nodes + [nxt]), tuple(p_edges + [edge])))
            elif nxt not in p_nodes:
                if len(p_edges) + 1 < max_hops:
                    stack.append((nxt, p_nodes + [nxt], p_edges + [edge]))

    if not cycles:
        if subgraph.truncated:
            return CycleIncompleteTruncated(account_id=account_id)
        return CycleNotFound(account_id=account_id)

    def cycle_key(
        c: tuple[tuple[uuid.UUID, ...], tuple[uuid.UUID, ...]],
    ) -> tuple[int, tuple[str, ...]]:
        p_nodes, p_edges = c
        str_nodes = tuple(str(x) for x in p_nodes)
        return (len(p_edges), str_nodes)

    best_cycle = min(cycles, key=cycle_key)

    return CycleFound(
        account_id=account_id,
        cycle_entity_ids=best_cycle[0],
        cycle_relationship_ids=best_cycle[1],
    )


def compute_outbound_chain_depth(
    engine: Engine,
    account_id: uuid.UUID,
    max_hops: int = MAX_CHAIN_HOPS,
) -> ChainDepthResult:
    """Compute the bounded outbound directed TRANSACTED_WITH chain depth.

    Uses get_bounded_subgraph for safety. Truncation from non-TRANSACTED_WITH
    edges is conservative. A truncated max_depth is a lower bound.

    Args:
        engine: Read-only SQLAlchemy Engine.
        account_id: The starting account UUID.
        max_hops: Maximum chain depth to explore.

    Returns:
        ChainDepthComputed if exploration completes without truncation.
        ChainDepthIncompleteTruncated if the bounded graph was truncated.

    Raises:
        InvalidGraphInputError: If inputs are invalid.
        EntityNotFoundError: If the account does not exist.
    """
    account_id = _validate_uuid(account_id, "account_id")
    if type(max_hops) is not int:
        raise InvalidGraphInputError("max_hops must be an int")
    if max_hops < 1:
        raise InvalidGraphInputError("max_hops must be >= 1 for chain")

    start_entity_id = get_entity_id_for_account(engine, account_id)
    subgraph = get_bounded_subgraph(engine, start_entity_id, max_hops)

    rel_ids = subgraph.relationship_ids
    rows: Sequence[Any] = []
    if rel_ids:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT relationship_id, source_entity_id, "
                    "target_entity_id, relationship_type "
                    "FROM graph_relationships "
                    "WHERE relationship_id = ANY(:rel_ids)"
                ),
                {"rel_ids": list(rel_ids)},
            ).fetchall()

    adj: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]] = {}
    for row in rows:
        r_id: uuid.UUID = row[0]
        u: uuid.UUID = row[1]
        v: uuid.UUID = row[2]
        r_type: str = row[3]

        if r_type != "TRANSACTED_WITH":
            continue
        if u == v:
            continue

        if u not in adj:
            adj[u] = {}

        if v not in adj[u]:
            adj[u][v] = r_id
        else:
            if str(r_id) < str(adj[u][v]):
                adj[u][v] = r_id

    chains: list[tuple[tuple[uuid.UUID, ...], tuple[uuid.UUID, ...]]] = []
    stack: list[tuple[uuid.UUID, list[uuid.UUID], list[uuid.UUID]]] = [
        (start_entity_id, [start_entity_id], [])
    ]

    while stack:
        curr, p_nodes, p_edges = stack.pop()

        if len(p_edges) < max_hops:
            for nxt, edge in adj.get(curr, {}).items():
                if nxt not in p_nodes:
                    stack.append((nxt, p_nodes + [nxt], p_edges + [edge]))

        chains.append((tuple(p_nodes), tuple(p_edges)))

    def chain_sort_key(
        c: tuple[tuple[uuid.UUID, ...], tuple[uuid.UUID, ...]],
    ) -> tuple[int, tuple[str, ...]]:
        p_nodes, p_edges = c
        str_nodes = tuple(str(x) for x in p_nodes)
        return (-len(p_edges), str_nodes)

    best_chain = min(chains, key=chain_sort_key)

    if subgraph.truncated:
        return ChainDepthIncompleteTruncated(
            account_id=account_id,
            lower_bound_depth=len(best_chain[1]),
            chain_entity_ids=best_chain[0],
            chain_relationship_ids=best_chain[1],
        )

    return ChainDepthComputed(
        account_id=account_id,
        depth=len(best_chain[1]),
        chain_entity_ids=best_chain[0],
        chain_relationship_ids=best_chain[1],
    )
