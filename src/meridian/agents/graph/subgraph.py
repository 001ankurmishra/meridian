"""Bounded-depth subgraph retrieval and directed simple-path finding.

Read-only, deterministic, Fact/Signal-layer operations over the
``entities`` and ``graph_relationships`` tables.  Uses an in-memory
``networkx.MultiDiGraph`` built from the stored edge list; subgraph
reachability traverses the undirected view (for surrounding context),
while path-finding uses the directed graph (to honour edge direction).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

import networkx as nx  # type: ignore[import-untyped]
from sqlalchemy import Engine, text

from meridian.agents.graph.errors import EntityNotFoundError, InvalidGraphInputError

# ---------------------------------------------------------------------------
# Safety-cap constants — defensive limits to bound memory usage.
# These are NOT business thresholds; they exist only to prevent
# unbounded graph expansion in production.
# ---------------------------------------------------------------------------
MAX_SUBGRAPH_NODES: int = 500
MAX_SUBGRAPH_EDGES: int = 2000
MAX_PATHS_RETURNED: int = 100


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubgraphResult:
    """Bounded-depth subgraph around a start entity."""

    start_entity_id: uuid.UUID
    max_hops: int
    node_entity_ids: tuple[uuid.UUID, ...]
    relationship_ids: tuple[uuid.UUID, ...]
    truncated: bool


@dataclass(frozen=True)
class GraphPath:
    """A single directed simple path between two entities."""

    entity_ids: tuple[uuid.UUID, ...]
    relationship_ids: tuple[uuid.UUID, ...]  # len == len(entity_ids) - 1


@dataclass(frozen=True)
class SimplePathsResult:
    """All directed simple paths found between two entities."""

    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    max_hops: int
    paths: tuple[GraphPath, ...]  # may be empty — valid Fact, not error
    truncated: bool


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_uuid(value: object, label: str) -> uuid.UUID:
    """Ensure *value* is a ``uuid.UUID``; raise on mismatch."""
    if not isinstance(value, uuid.UUID):
        raise InvalidGraphInputError(f"{label} is not a valid UUID: {value!r}")
    return value


def _entity_exists(conn: Any, entity_id: uuid.UUID) -> bool:
    """Check whether an entity row exists (SELECT only)."""
    row = conn.execute(
        text("SELECT 1 FROM entities WHERE entity_id = :eid"),
        {"eid": entity_id},
    ).fetchone()
    return row is not None


def _build_digraph(conn: Any) -> nx.MultiDiGraph:
    """Load all ``graph_relationships`` rows into a ``networkx.MultiDiGraph``.

    Each edge is keyed by ``relationship_id`` and carries
    ``relationship_type``, ``weight``, ``source_entity_id``, and
    ``target_entity_id`` as attributes.
    """
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    rows = conn.execute(
        text(
            "SELECT relationship_id, source_entity_id, target_entity_id, "
            "relationship_type, weight "
            "FROM graph_relationships"
        )
    ).fetchall()

    for row in rows:
        rel_id = row[0]
        src = row[1]
        tgt = row[2]
        rel_type = row[3]
        weight = row[4]

        # Ensure both nodes are present so we can reason about them.
        g.add_node(src)
        g.add_node(tgt)

        # NetworkX MultiDiGraph preserves all parallel edges.
        # We use relationship_id as the key to uniquely identify them.
        g.add_edge(
            src,
            tgt,
            key=rel_id,
            relationship_id=rel_id,
            relationship_type=rel_type,
            weight=weight,
            source_entity_id=src,
            target_entity_id=tgt,
        )

    return g


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_entity_id_for_account(
    engine: Engine,
    account_id: uuid.UUID,
) -> uuid.UUID:
    """Resolve an ``account_id`` to its ``entity_id``.

    Looks up the ``entities`` table for a row with
    ``entity_type='account'`` and ``reference_id=account_id``.

    Raises:
        EntityNotFoundError: if no matching entity exists.
    """
    _validate_uuid(account_id, "account_id")

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT entity_id FROM entities "
                "WHERE entity_type = 'account' AND reference_id = :aid"
            ),
            {"aid": account_id},
        ).fetchone()

    if row is None:
        raise EntityNotFoundError(
            f"No entity with entity_type='account' and "
            f"reference_id={account_id} found."
        )

    entity_id: uuid.UUID = row[0]
    return entity_id


def get_bounded_subgraph(
    engine: Engine,
    start_entity_id: uuid.UUID,
    max_hops: int,
) -> SubgraphResult:
    """Return the bounded-depth subgraph around *start_entity_id*.

    Builds an in-memory ``networkx.MultiDiGraph`` from all
    ``graph_relationships`` rows.  Uses the **undirected** view
    (``G.to_undirected()``) to determine reachability within
    *max_hops* hops (since subgraph retrieval is about surrounding
    context in either direction).  Collects the ``relationship_id``
    values of edges among the visited nodes from the **original**
    directed graph so that edge direction is preserved in the result.

    If the visited node or edge count exceeds
    ``MAX_SUBGRAPH_NODES`` / ``MAX_SUBGRAPH_EDGES``, the traversal
    stops early and ``truncated`` is set to ``True``.

    Read-only: SELECT only.  Uses ``engine.connect()``, never
    ``engine.begin()``.

    Raises:
        InvalidGraphInputError: if *max_hops* < 1 or
            *start_entity_id* is malformed.
        EntityNotFoundError: if *start_entity_id* doesn't exist in
            the ``entities`` table.
    """
    start_entity_id = _validate_uuid(start_entity_id, "start_entity_id")
    if max_hops < 1:
        raise InvalidGraphInputError(
            f"max_hops must be >= 1, got {max_hops}"
        )

    with engine.connect() as conn:
        if not _entity_exists(conn, start_entity_id):
            raise EntityNotFoundError(
                f"Entity {start_entity_id} does not exist."
            )

        g = _build_digraph(conn)

    # If the start node has no edges at all it won't be in the graph,
    # but it is a valid entity.  Return it alone.
    if start_entity_id not in g:
        return SubgraphResult(
            start_entity_id=start_entity_id,
            max_hops=max_hops,
            node_entity_ids=(start_entity_id,),
            relationship_ids=(),
            truncated=False,
        )

    # Undirected view for reachability — traverses edges in both
    # directions to capture surrounding context.
    undirected = g.to_undirected()

    # Bounded BFS from start_entity_id, respecting MAX_SUBGRAPH_NODES.
    visited: set[uuid.UUID] = set()
    truncated = False
    current_layer: set[uuid.UUID] = {start_entity_id}
    visited.add(start_entity_id)

    for _hop in range(max_hops):
        next_layer: set[uuid.UUID] = set()
        for node in current_layer:
            for neighbour in undirected.neighbors(node):
                if neighbour not in visited:
                    visited.add(neighbour)
                    next_layer.add(neighbour)
                    if len(visited) >= MAX_SUBGRAPH_NODES:
                        truncated = True
                        break
            if truncated:
                break
        if truncated:
            break
        current_layer = next_layer
        if not current_layer:
            break

    # Collect directed edges among visited nodes from the ORIGINAL
    # directed graph (preserving source/target direction).
    relationship_ids: list[uuid.UUID] = []
    for u, v, data in g.edges(data=True):
        if u in visited and v in visited:
            rel_id: uuid.UUID = data["relationship_id"]
            relationship_ids.append(rel_id)
            if len(relationship_ids) >= MAX_SUBGRAPH_EDGES:
                truncated = True
                break

    return SubgraphResult(
        start_entity_id=start_entity_id,
        max_hops=max_hops,
        node_entity_ids=tuple(sorted(visited)),
        relationship_ids=tuple(sorted(relationship_ids)),
        truncated=truncated,
    )


def find_simple_paths(
    engine: Engine,
    source_entity_id: uuid.UUID,
    target_entity_id: uuid.UUID,
    max_hops: int,
) -> SimplePathsResult:
    """Find all directed simple paths between two entities.

    Builds an in-memory ``networkx.MultiDiGraph`` and uses
    ``nx.all_simple_edge_paths`` on the **directed** graph with
    ``cutoff=max_hops``.  A path must represent an actual directional
    chain of relationships, not mere reachability.

    For each path, builds a ``GraphPath`` with the ordered
    ``entity_ids`` and the ordered ``relationship_ids`` of the edges
    actually traversed (using the edge key).

    Stops and sets ``truncated=True`` if the number of paths found
    reaches ``MAX_PATHS_RETURNED``.  If zero paths exist, returns
    ``SimplePathsResult`` with ``paths=()`` — a valid,
    fully-determined result.

    Read-only: SELECT only.  Uses ``engine.connect()``, never
    ``engine.begin()``.

    Raises:
        InvalidGraphInputError: if inputs are invalid.
        EntityNotFoundError: if either entity does not exist.
    """
    source_entity_id = _validate_uuid(source_entity_id, "source_entity_id")
    target_entity_id = _validate_uuid(target_entity_id, "target_entity_id")
    if max_hops < 1:
        raise InvalidGraphInputError(
            f"max_hops must be >= 1, got {max_hops}"
        )

    with engine.connect() as conn:
        if not _entity_exists(conn, source_entity_id):
            raise EntityNotFoundError(
                f"Entity {source_entity_id} does not exist."
            )
        if not _entity_exists(conn, target_entity_id):
            raise EntityNotFoundError(
                f"Entity {target_entity_id} does not exist."
            )

        g = _build_digraph(conn)

    # If either node is not in the graph (no edges) there can be no
    # paths.
    if source_entity_id not in g or target_entity_id not in g:
        return SimplePathsResult(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            max_hops=max_hops,
            paths=(),
            truncated=False,
        )

    paths: list[GraphPath] = []
    truncated = False

    for edge_path in nx.all_simple_edge_paths(
        g, source_entity_id, target_entity_id, cutoff=max_hops
    ):
        # edge_path is a list of (u, v, key) tuples representing the traversed edges.
        rel_ids: list[uuid.UUID] = []
        node_ids: list[uuid.UUID] = [source_entity_id]

        for u, v, key in edge_path:
            # The key is the relationship_id because we set it in _build_digraph
            rel_ids.append(cast(uuid.UUID, key))
            node_ids.append(cast(uuid.UUID, v))

        paths.append(
            GraphPath(
                entity_ids=tuple(node_ids),
                relationship_ids=tuple(rel_ids),
            )
        )

        if len(paths) >= MAX_PATHS_RETURNED:
            truncated = True
            break

    return SimplePathsResult(
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        max_hops=max_hops,
        paths=tuple(paths),
        truncated=truncated,
    )
