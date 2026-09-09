"""Test suite for bounded-depth subgraph retrieval (F4 Slice 1).

Defines all fixtures locally. No tests/conftest.py dependency.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Generator
from unittest.mock import patch

import pytest
from sqlalchemy import Engine, create_engine, text

from meridian.agents.graph.errors import EntityNotFoundError, InvalidGraphInputError
from meridian.agents.graph.subgraph import (
    SimplePathsResult,
    SubgraphResult,
    find_simple_paths,
    get_bounded_subgraph,
    get_entity_id_for_account,
)

# ---------------------------------------------------------------------------
# Fixtures (all local to this file)
# ---------------------------------------------------------------------------


@pytest.fixture
def superuser_engine() -> Generator[Engine, None, None]:
    """Engine using the migrator/superuser role (DATABASE_URL)."""
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://meridian_user:meridian_pass@localhost:5432/meridian_db",
    )
    engine = create_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def app_engine() -> Generator[Engine, None, None]:
    """Engine using the least-privilege application role (APP_DATABASE_URL)."""
    db_url = os.environ.get(
        "APP_DATABASE_URL",
        "postgresql+psycopg://meridian_app:meridian_app_pass@localhost:5432/meridian_db",
    )
    engine = create_engine(db_url)
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)


def _seed_customer(
    engine: Engine,
    *,
    customer_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert a minimal customer row and return its ID."""
    cid = customer_id or uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers (customer_id, full_name, is_synthetic, "
                "created_at) VALUES (:cid, :name, true, :now)"
            ),
            {
                "cid": cid,
                "name": f"Test Customer {cid}",
                "now": _NOW,
            },
        )
    return cid


def _seed_account(
    engine: Engine,
    customer_id: uuid.UUID,
    *,
    account_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert a minimal account row and return its ID."""
    aid = account_id or uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (account_id, customer_id, status, created_at) "
                "VALUES (:aid, :cid, 'active', :now)"
            ),
            {"aid": aid, "cid": customer_id, "now": _NOW},
        )
    return aid


def _seed_entity(
    engine: Engine,
    *,
    entity_id: uuid.UUID | None = None,
    entity_type: str = "account",
    reference_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert an entity row and return its entity_id."""
    eid = entity_id or uuid.uuid4()
    rid = reference_id or uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO entities (entity_id, entity_type, reference_id, "
                "created_at) VALUES (:eid, :etype, :rid, :now)"
            ),
            {"eid": eid, "etype": entity_type, "rid": rid, "now": _NOW},
        )
    return eid


def _seed_relationship(
    engine: Engine,
    *,
    relationship_id: uuid.UUID | None = None,
    source_entity_id: uuid.UUID,
    target_entity_id: uuid.UUID,
    relationship_type: str = "TRANSACTED_WITH",
    weight: float = 1.0,
) -> uuid.UUID:
    """Insert a graph_relationships row and return its relationship_id."""
    rid = relationship_id or uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO graph_relationships "
                "(relationship_id, source_entity_id, target_entity_id, "
                "relationship_type, weight, first_observed_at, "
                "last_observed_at, created_at) "
                "VALUES (:rid, :src, :tgt, :rtype, :w, :now, :now, :now)"
            ),
            {
                "rid": rid,
                "src": source_entity_id,
                "tgt": target_entity_id,
                "rtype": relationship_type,
                "w": weight,
                "now": _NOW,
            },
        )
    return rid


def _cleanup_graph_data(
    engine: Engine,
    entity_ids: list[uuid.UUID],
    relationship_ids: list[uuid.UUID] | None = None,
    customer_ids: list[uuid.UUID] | None = None,
    account_ids: list[uuid.UUID] | None = None,
) -> None:
    """Remove seeded test data in FK-safe order.

    Deletes: graph_relationships FIRST (by relationship_id or matching
    source/target entity_id), THEN entities, THEN accounts, THEN
    customers.  Never a global DELETE or TRUNCATE.
    """
    with engine.begin() as conn:
        # 1. graph_relationships — by relationship_id if provided, else
        #    by matching source/target entity_id.
        if relationship_ids:
            for rid in relationship_ids:
                conn.execute(
                    text(
                        "DELETE FROM graph_relationships "
                        "WHERE relationship_id = :rid"
                    ),
                    {"rid": rid},
                )
        # Also clean by entity_id in case any were missed.
        for eid in entity_ids:
            conn.execute(
                text(
                    "DELETE FROM graph_relationships "
                    "WHERE source_entity_id = :eid OR target_entity_id = :eid"
                ),
                {"eid": eid},
            )

        # 2. entities
        for eid in entity_ids:
            conn.execute(
                text("DELETE FROM entities WHERE entity_id = :eid"),
                {"eid": eid},
            )

        # 3. accounts
        if account_ids:
            for aid in account_ids:
                conn.execute(
                    text("DELETE FROM accounts WHERE account_id = :aid"),
                    {"aid": aid},
                )

        # 4. customers
        if customer_ids:
            for cid in customer_ids:
                conn.execute(
                    text("DELETE FROM customers WHERE customer_id = :cid"),
                    {"cid": cid},
                )


# ---------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------


class TestGetEntityIdForAccount:
    """Tests for get_entity_id_for_account."""

    def test_resolves_account_to_entity(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Seed a customer, account, and entity; resolve correctly."""
        cid = _seed_customer(superuser_engine)
        aid = _seed_account(superuser_engine, cid)
        eid = _seed_entity(
            superuser_engine,
            entity_type="account",
            reference_id=aid,
        )
        try:
            result = get_entity_id_for_account(app_engine, aid)
            assert result == eid
        finally:
            _cleanup_graph_data(
                superuser_engine,
                entity_ids=[eid],
                account_ids=[aid],
                customer_ids=[cid],
            )

    def test_nonexistent_account_raises(
        self,
        app_engine: Engine,
    ) -> None:
        """No entity for this account_id -> EntityNotFoundError."""
        fake_aid = uuid.uuid4()
        with pytest.raises(EntityNotFoundError):
            get_entity_id_for_account(app_engine, fake_aid)


class TestBoundedSubgraph:
    """Tests for get_bounded_subgraph."""

    def test_happy_path_subgraph(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Small chain: A -> B -> C -> D.

        With max_hops=3 from A, all 4 nodes and 3 edges are included.
        """
        e_a = _seed_entity(superuser_engine)
        e_b = _seed_entity(superuser_engine)
        e_c = _seed_entity(superuser_engine)
        e_d = _seed_entity(superuser_engine)

        r_ab = _seed_relationship(
            superuser_engine, source_entity_id=e_a, target_entity_id=e_b
        )
        r_bc = _seed_relationship(
            superuser_engine, source_entity_id=e_b, target_entity_id=e_c
        )
        r_cd = _seed_relationship(
            superuser_engine, source_entity_id=e_c, target_entity_id=e_d
        )

        entity_ids = [e_a, e_b, e_c, e_d]
        rel_ids = [r_ab, r_bc, r_cd]

        try:
            result = get_bounded_subgraph(app_engine, e_a, max_hops=3)
            assert isinstance(result, SubgraphResult)
            assert result.start_entity_id == e_a
            assert result.max_hops == 3
            assert set(result.node_entity_ids) == set(entity_ids)
            assert set(result.relationship_ids) == set(rel_ids)
            assert result.truncated is False
        finally:
            _cleanup_graph_data(
                superuser_engine,
                entity_ids=entity_ids,
                relationship_ids=rel_ids,
            )

    def test_hop_limit_boundary(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Chain A -> B -> C.

        max_hops=1 from A includes A and B (1 hop), but NOT C (2 hops).
        """
        e_a = _seed_entity(superuser_engine)
        e_b = _seed_entity(superuser_engine)
        e_c = _seed_entity(superuser_engine)

        r_ab = _seed_relationship(
            superuser_engine, source_entity_id=e_a, target_entity_id=e_b
        )
        r_bc = _seed_relationship(
            superuser_engine, source_entity_id=e_b, target_entity_id=e_c
        )

        entity_ids = [e_a, e_b, e_c]
        rel_ids = [r_ab, r_bc]

        try:
            result = get_bounded_subgraph(app_engine, e_a, max_hops=1)
            assert set(result.node_entity_ids) == {e_a, e_b}
            # Only r_ab is among visited nodes (C is excluded).
            assert set(result.relationship_ids) == {r_ab}
            assert result.truncated is False

            # max_hops=2 from A includes C.
            result2 = get_bounded_subgraph(app_engine, e_a, max_hops=2)
            assert set(result2.node_entity_ids) == {e_a, e_b, e_c}
            assert set(result2.relationship_ids) == {r_ab, r_bc}
        finally:
            _cleanup_graph_data(
                superuser_engine,
                entity_ids=entity_ids,
                relationship_ids=rel_ids,
            )

    def test_subgraph_truncation_on_cap(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Verify truncated=True by temporarily lowering the cap constants.

        Seeds a small chain of 5 nodes and patches MAX_SUBGRAPH_NODES=3
        to trigger truncation without seeding hundreds of rows.
        """
        entities = [_seed_entity(superuser_engine) for _ in range(5)]
        rels: list[uuid.UUID] = []
        for i in range(4):
            rid = _seed_relationship(
                superuser_engine,
                source_entity_id=entities[i],
                target_entity_id=entities[i + 1],
            )
            rels.append(rid)

        try:
            with patch(
                "meridian.agents.graph.subgraph.MAX_SUBGRAPH_NODES", 3
            ):
                result = get_bounded_subgraph(
                    app_engine, entities[0], max_hops=10
                )
                assert result.truncated is True
                assert len(result.node_entity_ids) <= 3
        finally:
            _cleanup_graph_data(
                superuser_engine,
                entity_ids=entities,
                relationship_ids=rels,
            )

    def test_subgraph_edge_truncation_on_cap(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Verify truncated=True when edge count exceeds MAX_SUBGRAPH_EDGES.

        Seeds a small graph and patches MAX_SUBGRAPH_EDGES=1 to trigger
        edge truncation.
        """
        e_a = _seed_entity(superuser_engine)
        e_b = _seed_entity(superuser_engine)
        e_c = _seed_entity(superuser_engine)

        r_ab = _seed_relationship(
            superuser_engine, source_entity_id=e_a, target_entity_id=e_b
        )
        r_bc = _seed_relationship(
            superuser_engine, source_entity_id=e_b, target_entity_id=e_c
        )

        entity_ids = [e_a, e_b, e_c]
        rel_ids = [r_ab, r_bc]

        try:
            with patch(
                "meridian.agents.graph.subgraph.MAX_SUBGRAPH_EDGES", 1
            ):
                result = get_bounded_subgraph(
                    app_engine, e_a, max_hops=5
                )
                assert result.truncated is True
                assert len(result.relationship_ids) <= 1
        finally:
            _cleanup_graph_data(
                superuser_engine,
                entity_ids=entity_ids,
                relationship_ids=rel_ids,
            )

    def test_parallel_edges_included_in_subgraph(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Seed A -> B twice. Bounded subgraph from A should include both edges."""
        e_a = _seed_entity(superuser_engine)
        e_b = _seed_entity(superuser_engine)

        r1 = _seed_relationship(
            superuser_engine,
            source_entity_id=e_a,
            target_entity_id=e_b,
            relationship_type="TRANSACTED_WITH",
        )
        r2 = _seed_relationship(
            superuser_engine,
            source_entity_id=e_a,
            target_entity_id=e_b,
            relationship_type="OWNS",
        )

        try:
            result = get_bounded_subgraph(app_engine, e_a, max_hops=1)
            assert set(result.node_entity_ids) == {e_a, e_b}
            assert set(result.relationship_ids) == {r1, r2}
        finally:
            _cleanup_graph_data(
                superuser_engine,
                entity_ids=[e_a, e_b],
                relationship_ids=[r1, r2],
            )


class TestFindSimplePaths:
    """Tests for find_simple_paths."""

    def test_find_simple_paths_worked_example(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Seed the Rahul -> Tech Solutions -> Global Traders chain locally.

        Mirror the worked_example.py graph_relationships construction
        (locally seeded, not via the shared loader).
        """
        # Entity IDs (locally generated — NOT from the loader).
        rahul_acct_eid = _seed_entity(superuser_engine)
        tech_sol_acct_eid = _seed_entity(superuser_engine)
        global_traders_acct_eid = _seed_entity(superuser_engine)
        another_acct_eid = _seed_entity(superuser_engine)

        r1 = _seed_relationship(
            superuser_engine,
            source_entity_id=rahul_acct_eid,
            target_entity_id=tech_sol_acct_eid,
        )
        r2 = _seed_relationship(
            superuser_engine,
            source_entity_id=tech_sol_acct_eid,
            target_entity_id=global_traders_acct_eid,
        )
        r3 = _seed_relationship(
            superuser_engine,
            source_entity_id=tech_sol_acct_eid,
            target_entity_id=another_acct_eid,
        )

        entity_ids = [
            rahul_acct_eid,
            tech_sol_acct_eid,
            global_traders_acct_eid,
            another_acct_eid,
        ]
        rel_ids = [r1, r2, r3]

        try:
            # Path from Rahul -> Global Traders (2 hops).
            result = find_simple_paths(
                app_engine,
                rahul_acct_eid,
                global_traders_acct_eid,
                max_hops=3,
            )
            assert isinstance(result, SimplePathsResult)
            assert len(result.paths) == 1

            path = result.paths[0]
            assert path.entity_ids == (
                rahul_acct_eid,
                tech_sol_acct_eid,
                global_traders_acct_eid,
            )
            assert path.relationship_ids == (r1, r2)
            assert result.truncated is False

            # Path from Rahul -> Another Company (2 hops).
            result2 = find_simple_paths(
                app_engine,
                rahul_acct_eid,
                another_acct_eid,
                max_hops=3,
            )
            assert len(result2.paths) == 1
            path2 = result2.paths[0]
            assert path2.entity_ids == (
                rahul_acct_eid,
                tech_sol_acct_eid,
                another_acct_eid,
            )
            assert path2.relationship_ids == (r1, r3)
        finally:
            _cleanup_graph_data(
                superuser_engine,
                entity_ids=entity_ids,
                relationship_ids=rel_ids,
            )

    def test_directionality_respected(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Directed chain A -> B -> C.

        find_simple_paths(C, A) must return NO paths — confirms directed
        traversal, not silently undirected.
        """
        e_a = _seed_entity(superuser_engine)
        e_b = _seed_entity(superuser_engine)
        e_c = _seed_entity(superuser_engine)

        r_ab = _seed_relationship(
            superuser_engine, source_entity_id=e_a, target_entity_id=e_b
        )
        r_bc = _seed_relationship(
            superuser_engine, source_entity_id=e_b, target_entity_id=e_c
        )

        entity_ids = [e_a, e_b, e_c]
        rel_ids = [r_ab, r_bc]

        try:
            # Forward: A -> C — should find 1 path.
            fwd = find_simple_paths(app_engine, e_a, e_c, max_hops=3)
            assert len(fwd.paths) == 1

            # Reverse: C -> A — should find NO paths.
            rev = find_simple_paths(app_engine, e_c, e_a, max_hops=3)
            assert len(rev.paths) == 0
            assert rev.truncated is False
        finally:
            _cleanup_graph_data(
                superuser_engine,
                entity_ids=entity_ids,
                relationship_ids=rel_ids,
            )

    def test_no_path_exists(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Two disconnected entities -> paths == (), truncated == False."""
        e_a = _seed_entity(superuser_engine)
        e_b = _seed_entity(superuser_engine)

        try:
            result = find_simple_paths(app_engine, e_a, e_b, max_hops=5)
            assert isinstance(result, SimplePathsResult)
            assert result.paths == ()
            assert result.truncated is False
        finally:
            _cleanup_graph_data(
                superuser_engine,
                entity_ids=[e_a, e_b],
            )

    def test_paths_truncation_on_cap(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Verify truncated=True when path count would exceed cap.

        Construct a graph with many parallel routes:
        A -> X1 -> B, A -> X2 -> B, ..., A -> Xn -> B.
        With MAX_PATHS_RETURNED patched to 2 and n=4 intermediates,
        truncation must kick in.
        """
        e_a = _seed_entity(superuser_engine)
        e_b = _seed_entity(superuser_engine)

        intermediates: list[uuid.UUID] = []
        all_rels: list[uuid.UUID] = []

        for _ in range(4):
            e_x = _seed_entity(superuser_engine)
            intermediates.append(e_x)
            r1 = _seed_relationship(
                superuser_engine,
                source_entity_id=e_a,
                target_entity_id=e_x,
            )
            r2 = _seed_relationship(
                superuser_engine,
                source_entity_id=e_x,
                target_entity_id=e_b,
            )
            all_rels.extend([r1, r2])

        all_entities = [e_a, e_b, *intermediates]

        try:
            with patch(
                "meridian.agents.graph.subgraph.MAX_PATHS_RETURNED", 2
            ):
                result = find_simple_paths(
                    app_engine, e_a, e_b, max_hops=3
                )
                assert result.truncated is True
                assert len(result.paths) == 2
        finally:
            _cleanup_graph_data(
                superuser_engine,
                entity_ids=all_entities,
                relationship_ids=all_rels,
            )

    def test_parallel_edges_yield_multiple_paths(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Seed A -> B twice with different relationship_ids.
        Paths A->B should return TWO paths, one for each relationship_id.
        """
        e_a = _seed_entity(superuser_engine)
        e_b = _seed_entity(superuser_engine)

        r1 = _seed_relationship(
            superuser_engine,
            source_entity_id=e_a,
            target_entity_id=e_b,
            relationship_type="TRANSACTED_WITH",
        )
        r2 = _seed_relationship(
            superuser_engine,
            source_entity_id=e_a,
            target_entity_id=e_b,
            relationship_type="OWNS",
        )

        try:
            result = find_simple_paths(app_engine, e_a, e_b, max_hops=2)
            assert len(result.paths) == 2

            # The paths can be returned in any order
            returned_rids = {p.relationship_ids[0] for p in result.paths}
            assert returned_rids == {r1, r2}
        finally:
            _cleanup_graph_data(
                superuser_engine,
                entity_ids=[e_a, e_b],
                relationship_ids=[r1, r2],
            )


class TestInputValidation:
    """Tests for input validation and error handling."""

    def test_invalid_max_hops_raises_subgraph(
        self,
        app_engine: Engine,
    ) -> None:
        """max_hops < 1 -> InvalidGraphInputError for get_bounded_subgraph."""
        fake_eid = uuid.uuid4()
        with pytest.raises(InvalidGraphInputError, match="max_hops must be >= 1"):
            get_bounded_subgraph(app_engine, fake_eid, max_hops=0)

        with pytest.raises(InvalidGraphInputError, match="max_hops must be >= 1"):
            get_bounded_subgraph(app_engine, fake_eid, max_hops=-1)

    def test_invalid_max_hops_raises_find_paths(
        self,
        app_engine: Engine,
    ) -> None:
        """max_hops < 1 -> InvalidGraphInputError for find_simple_paths."""
        fake_a = uuid.uuid4()
        fake_b = uuid.uuid4()
        with pytest.raises(InvalidGraphInputError, match="max_hops must be >= 1"):
            find_simple_paths(app_engine, fake_a, fake_b, max_hops=0)

    def test_nonexistent_entity_raises_subgraph(
        self,
        app_engine: Engine,
    ) -> None:
        """EntityNotFoundError for nonexistent start_entity_id."""
        fake_eid = uuid.uuid4()
        with pytest.raises(EntityNotFoundError, match="does not exist"):
            get_bounded_subgraph(app_engine, fake_eid, max_hops=2)

    def test_nonexistent_entity_raises_find_paths(
        self,
        app_engine: Engine,
    ) -> None:
        """EntityNotFoundError if either entity does not exist."""
        fake_a = uuid.uuid4()
        fake_b = uuid.uuid4()
        with pytest.raises(EntityNotFoundError, match="does not exist"):
            find_simple_paths(app_engine, fake_a, fake_b, max_hops=2)


class TestReadOnly:
    """Verify read-only behaviour."""

    def test_read_only_no_writes(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
    ) -> None:
        """Snapshot row counts on entities and graph_relationships
        before/after; assert unchanged.
        """
        # Seed a small graph.
        e_a = _seed_entity(superuser_engine)
        e_b = _seed_entity(superuser_engine)
        r_ab = _seed_relationship(
            superuser_engine, source_entity_id=e_a, target_entity_id=e_b
        )

        try:
            # Snapshot before.
            with superuser_engine.connect() as conn:
                entities_before = conn.execute(
                    text("SELECT count(*) FROM entities")
                ).scalar()
                rels_before = conn.execute(
                    text("SELECT count(*) FROM graph_relationships")
                ).scalar()

            # Run both functions.
            get_bounded_subgraph(app_engine, e_a, max_hops=2)
            find_simple_paths(app_engine, e_a, e_b, max_hops=2)

            # Snapshot after.
            with superuser_engine.connect() as conn:
                entities_after = conn.execute(
                    text("SELECT count(*) FROM entities")
                ).scalar()
                rels_after = conn.execute(
                    text("SELECT count(*) FROM graph_relationships")
                ).scalar()

            assert entities_before == entities_after
            assert rels_before == rels_after
        finally:
            _cleanup_graph_data(
                superuser_engine,
                entity_ids=[e_a, e_b],
                relationship_ids=[r_ab],
            )
