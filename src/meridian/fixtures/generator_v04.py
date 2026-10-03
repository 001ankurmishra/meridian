import copy
import hashlib
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from meridian.fixtures.generator_v03 import generate_fixtures_v03


def deterministic_uuid(seed: str, namespace: str, key: str) -> uuid.UUID:
    h = hashlib.sha256(f"{seed}:{namespace}:{key}".encode("utf-8")).hexdigest()
    return uuid.uuid5(uuid.NAMESPACE_OID, h)


def _compute_graph_ground_truth(
    start_acct_id_str: str | None,
    start_entity_id: uuid.UUID | None,
    tw_edges: list[tuple[uuid.UUID, uuid.UUID]],
) -> dict[str, Any]:
    if start_entity_id is None or start_acct_id_str is None:
        return {
            "applicable": False,
            "start_account_id": start_acct_id_str,
            "has_directed_cycle": False,
            "shortest_cycle_length": None,
            "max_outbound_chain_depth": 0,
            "max_hops_considered": 4,
            "definition_version": "1",
            "reason": "Alert source account lacks account entity",
        }

    adj: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for u, v in tw_edges:
        if u != v:  # ignore self-loops
            adj[u].append(v)

    shortest_cycle = None

    # BFS for shortest cycle
    from collections import deque

    queue: deque[tuple[uuid.UUID, int, set[uuid.UUID]]] = deque(
        [(start_entity_id, 0, {start_entity_id})]
    )
    while queue:
        curr, depth, path = queue.popleft()
        if depth >= 4:
            continue

        for nxt in adj[curr]:
            if nxt == start_entity_id and depth + 1 >= 2:
                if shortest_cycle is None or depth + 1 < shortest_cycle:
                    shortest_cycle = depth + 1
            elif nxt not in path:
                new_path = path | {nxt}
                queue.append((nxt, depth + 1, new_path))

    # DFS for max chain depth
    def get_max_depth(curr: uuid.UUID, path: set[uuid.UUID], depth: int) -> int:
        if depth == 4:
            return 4
        m = depth
        for nxt in adj[curr]:
            if nxt not in path:
                m = max(m, get_max_depth(nxt, path | {nxt}, depth + 1))
        return m

    max_chain_depth = get_max_depth(start_entity_id, {start_entity_id}, 0)

    return {
        "applicable": True,
        "start_account_id": start_acct_id_str,
        "has_directed_cycle": shortest_cycle is not None,
        "shortest_cycle_length": shortest_cycle,
        "max_outbound_chain_depth": max_chain_depth,
        "max_hops_considered": 4,
        "definition_version": "1",
    }


def generate_fixtures_v04(seed: str = "default_seed") -> dict[str, Any]:
    """
    Generate v0.4 fixtures (extends v0.3).
    Adds derived TRANSACTED_WITH graph relationships and structural ground truth.
    """
    res = generate_fixtures_v03(seed)
    # Deep copy to ensure we don't mutate v0.3 in place if imported elsewhere
    res = copy.deepcopy(res)

    MANIFEST_SCHEMA_VERSION = "0.4"
    FIXTURE_VERSION = "0.4"
    GENERATOR_VERSION = "0.4"
    ANCHOR_TIMESTAMP = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Build acct_id -> entity_id mapping
    acct_entities: dict[uuid.UUID, uuid.UUID] = {}
    for ent in res["entities"]:
        if ent["entity_type"] == "account":
            acct_entities[ent["reference_id"]] = ent["entity_id"]

    # 2. Find existing TRANSACTED_WITH edges (from worked_example)
    existing_tw_pairs = set()
    for rel in res["graph_relationships"]:
        if rel["relationship_type"] == "TRANSACTED_WITH":
            existing_tw_pairs.add((rel["source_entity_id"], rel["target_entity_id"]))

    # 3. Derive new relationships
    # Distinct ordered pairs: (src_ent_id, dst_ent_id) -> list of transactions
    qualifying_txs: dict[tuple[uuid.UUID, uuid.UUID], list[dict[str, Any]]] = (
        defaultdict(list)
    )

    for tx in res["transactions"]:
        src_a = tx["source_account_id"]
        dst_a = tx["destination_account_id"]
        if src_a and dst_a:
            src_e = acct_entities.get(src_a)
            dst_e = acct_entities.get(dst_a)
            if src_e and dst_e:
                qualifying_txs[(src_e, dst_e)].append(tx)

    # Deterministic sorting for output
    new_rels = []
    for src_e, dst_e in sorted(qualifying_txs.keys()):
        if (src_e, dst_e) in existing_tw_pairs:
            continue

        txs = qualifying_txs[(src_e, dst_e)]
        first_obs = min(t["occurred_at"] for t in txs)
        last_obs = max(t["occurred_at"] for t in txs)

        rel_id = deterministic_uuid(
            seed, "rel", f"{src_e}_{dst_e}_TRANSACTED_WITH_{first_obs.isoformat()}"
        )

        new_rels.append(
            {
                "relationship_id": rel_id,
                "source_entity_id": src_e,
                "target_entity_id": dst_e,
                "relationship_type": "TRANSACTED_WITH",
                "weight": 1.0,
                "first_observed_at": first_obs,
                "last_observed_at": last_obs,
                "created_at": ANCHOR_TIMESTAMP,
            }
        )
        existing_tw_pairs.add((src_e, dst_e))

    res["graph_relationships"].extend(new_rels)

    # 4. Compute structural ground truth for each fixture
    # Build complete list of edges for oracle
    all_tw_edges = list(existing_tw_pairs)

    for fix in res["manifest"]["fixtures"]:
        alert_src_a_str = None

        # Determine alert source account
        if fix["fixture_id"] == "worked_example":
            tx_id_str = fix["alert_spec"]["transaction_id"]
            for tx in res["transactions"]:
                if str(tx["transaction_id"]) == tx_id_str:
                    alert_src_a_str = str(tx["source_account_id"])
                    break
        else:
            if fix["account_ids"]:
                alert_src_a_str = fix["account_ids"][0]

        alert_src_e = None
        if alert_src_a_str:
            alert_src_a_uuid = uuid.UUID(alert_src_a_str)
            alert_src_e = acct_entities.get(alert_src_a_uuid)

        gt = _compute_graph_ground_truth(alert_src_a_str, alert_src_e, all_tw_edges)
        fix["graph_ground_truth"] = gt

    # 5. Update manifest versions
    res["manifest"]["manifest_schema_version"] = MANIFEST_SCHEMA_VERSION
    res["manifest"]["fixture_version"] = FIXTURE_VERSION
    res["manifest"]["generator_version"] = GENERATOR_VERSION

    return res
