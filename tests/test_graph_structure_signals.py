"""Test suite for deterministic graph structure signals."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Generator

import pytest
from sqlalchemy import Engine, create_engine, text

from meridian.agents.graph.errors import EntityNotFoundError, InvalidGraphInputError
from meridian.agents.graph.structure_signals import (
    ChainDepthComputed,
    ChainDepthIncompleteTruncated,
    CycleFound,
    CycleIncompleteTruncated,
    CycleNotFound,
    compute_cycle_through_account,
    compute_outbound_chain_depth,
)

# Avoid forbidden wording check failure:
# (this module is structurally analyzed, do not use the four prohibited phrases)


@pytest.fixture
def superuser_engine() -> Generator[Engine, None, None]:
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://meridian_user:meridian_pass@localhost:5432/meridian_db",
    )
    engine = create_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def app_engine() -> Generator[Engine, None, None]:
    db_url = os.environ.get(
        "APP_DATABASE_URL",
        "postgresql+psycopg://meridian_app:meridian_app_pass@localhost:5432/meridian_db",
    )
    engine = create_engine(db_url)
    yield engine
    engine.dispose()


def _seed_entity(
    superuser_engine: Engine,
    *,
    entity_id: uuid.UUID | None = None,
    entity_type: str = "account",
    reference_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    eid = entity_id or uuid.uuid4()
    rid = reference_id or uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO entities (entity_id, entity_type, "
                "reference_id, created_at) "
                "VALUES (:eid, :etype, :rid, :now)"
            ),
            {
                "eid": eid,
                "etype": entity_type,
                "rid": rid,
                "now": datetime.now(timezone.utc),
            },
        )
    return eid, rid


def _seed_relationship(
    superuser_engine: Engine,
    *,
    source_entity_id: uuid.UUID,
    target_entity_id: uuid.UUID,
    relationship_type: str = "TRANSACTED_WITH",
    relationship_id: uuid.UUID | None = None,
) -> uuid.UUID:
    rel_id = relationship_id or uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO graph_relationships ("
                "relationship_id, source_entity_id, target_entity_id, "
                "relationship_type, weight, first_observed_at, "
                "last_observed_at, created_at) "
                "VALUES (:rel_id, :src, :tgt, :rtype, 1.0, :now, :now, :now)"
            ),
            {
                "rel_id": rel_id,
                "src": source_entity_id,
                "tgt": target_entity_id,
                "rtype": relationship_type,
                "now": datetime.now(timezone.utc),
            },
        )
    return rel_id


def _cleanup(superuser_engine: Engine, entity_ids: list[uuid.UUID]) -> None:
    if not entity_ids:
        return
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM graph_relationships WHERE source_entity_id = ANY(:eids) "
                "OR target_entity_id = ANY(:eids)"
            ),
            {"eids": entity_ids},
        )
        conn.execute(
            text("DELETE FROM entities WHERE entity_id = ANY(:eids)"),
            {"eids": entity_ids},
        )


def test_forbidden_words_not_in_source() -> None:
    source_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
        "meridian",
        "agents",
        "graph",
        "structure_signals.py",
    )
    with open(source_path, "r", encoding="utf-8") as f:
        content = f.read().lower()

    assert "suspicious" not in content
    assert "money laundering" not in content
    assert "mule" not in content
    assert "recommend escalation" not in content


class TestStructureSignals:
    def test_cycle_invalid_max_hops(self, app_engine: Engine) -> None:
        with pytest.raises(InvalidGraphInputError, match="must be >= 2"):
            compute_cycle_through_account(app_engine, uuid.uuid4(), max_hops=1)
        with pytest.raises(InvalidGraphInputError, match="must be an int"):
            compute_cycle_through_account(app_engine, uuid.uuid4(), max_hops=True)

    def test_chain_invalid_max_hops(self, app_engine: Engine) -> None:
        with pytest.raises(InvalidGraphInputError, match="must be >= 1"):
            compute_outbound_chain_depth(app_engine, uuid.uuid4(), max_hops=0)
        with pytest.raises(InvalidGraphInputError, match="must be an int"):
            compute_outbound_chain_depth(app_engine, uuid.uuid4(), max_hops=False)

    def test_missing_entity_raises(self, app_engine: Engine) -> None:
        fake_id = uuid.uuid4()
        with pytest.raises(EntityNotFoundError):
            compute_cycle_through_account(app_engine, fake_id)

    def test_cycle_simple_3_hop(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e2, _ = _seed_entity(superuser_engine)
        e3, _ = _seed_entity(superuser_engine)
        try:
            r1 = _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e2
            )
            r2 = _seed_relationship(
                superuser_engine, source_entity_id=e2, target_entity_id=e3
            )
            r3 = _seed_relationship(
                superuser_engine, source_entity_id=e3, target_entity_id=e1
            )

            res = compute_cycle_through_account(app_engine, a1, max_hops=4)
            assert isinstance(res, CycleFound)
            assert res.account_id == a1
            assert len(res.cycle_relationship_ids) == 3
            assert set(res.cycle_relationship_ids) == {r1, r2, r3}
            assert set(res.cycle_entity_ids) == {e1, e2, e3}
        finally:
            _cleanup(superuser_engine, [e1, e2, e3])

    def test_cycle_two_node(self, superuser_engine: Engine, app_engine: Engine) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e2, _ = _seed_entity(superuser_engine)
        try:
            _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e2
            )
            _seed_relationship(
                superuser_engine, source_entity_id=e2, target_entity_id=e1
            )
            res = compute_cycle_through_account(app_engine, a1, max_hops=4)
            assert isinstance(res, CycleFound)
            assert len(res.cycle_relationship_ids) == 2
        finally:
            _cleanup(superuser_engine, [e1, e2])

    def test_cycle_self_loop_ignored(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        try:
            _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e1
            )
            res = compute_cycle_through_account(app_engine, a1, max_hops=4)
            assert isinstance(res, CycleNotFound)
        finally:
            _cleanup(superuser_engine, [e1])

    def test_cycle_longer_than_max_hops(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e2, _ = _seed_entity(superuser_engine)
        e3, _ = _seed_entity(superuser_engine)
        e4, _ = _seed_entity(superuser_engine)
        try:
            _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e2
            )
            _seed_relationship(
                superuser_engine, source_entity_id=e2, target_entity_id=e3
            )
            _seed_relationship(
                superuser_engine, source_entity_id=e3, target_entity_id=e4
            )
            _seed_relationship(
                superuser_engine, source_entity_id=e4, target_entity_id=e1
            )
            res = compute_cycle_through_account(app_engine, a1, max_hops=3)
            assert isinstance(res, CycleNotFound)
        finally:
            _cleanup(superuser_engine, [e1, e2, e3, e4])

    def test_cycle_bounded_by_max_hops(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e2, _ = _seed_entity(superuser_engine)
        try:
            _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e2
            )
            _seed_relationship(
                superuser_engine, source_entity_id=e2, target_entity_id=e1
            )
            res = compute_cycle_through_account(app_engine, a1, max_hops=2)
            assert isinstance(res, CycleFound)
            assert len(res.cycle_relationship_ids) == 2
        finally:
            _cleanup(superuser_engine, [e1, e2])

    def test_cycle_owns_filtered(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e2, _ = _seed_entity(superuser_engine)
        try:
            _seed_relationship(
                superuser_engine,
                source_entity_id=e1,
                target_entity_id=e2,
                relationship_type="OWNS",
            )
            _seed_relationship(
                superuser_engine,
                source_entity_id=e2,
                target_entity_id=e1,
                relationship_type="OWNS",
            )
            res = compute_cycle_through_account(app_engine, a1, max_hops=4)
            assert isinstance(res, CycleNotFound)
        finally:
            _cleanup(superuser_engine, [e1, e2])

    def test_chain_depth_0(self, superuser_engine: Engine, app_engine: Engine) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        try:
            res = compute_outbound_chain_depth(app_engine, a1, max_hops=4)
            assert isinstance(res, ChainDepthComputed)
            assert res.depth == 0
        finally:
            _cleanup(superuser_engine, [e1])

    def test_chain_depth_1(self, superuser_engine: Engine, app_engine: Engine) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e2, _ = _seed_entity(superuser_engine)
        try:
            _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e2
            )
            res = compute_outbound_chain_depth(app_engine, a1, max_hops=4)
            assert isinstance(res, ChainDepthComputed)
            assert res.depth == 1
        finally:
            _cleanup(superuser_engine, [e1, e2])

    def test_multi_hop_chain(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e2, _ = _seed_entity(superuser_engine)
        e3, _ = _seed_entity(superuser_engine)
        try:
            _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e2
            )
            _seed_relationship(
                superuser_engine, source_entity_id=e2, target_entity_id=e3
            )
            res = compute_outbound_chain_depth(app_engine, a1, max_hops=4)
            assert isinstance(res, ChainDepthComputed)
            assert res.depth == 2
        finally:
            _cleanup(superuser_engine, [e1, e2, e3])

    def test_chain_bounded_by_max_hops(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e2, _ = _seed_entity(superuser_engine)
        e3, _ = _seed_entity(superuser_engine)
        try:
            _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e2
            )
            _seed_relationship(
                superuser_engine, source_entity_id=e2, target_entity_id=e3
            )
            res = compute_outbound_chain_depth(app_engine, a1, max_hops=1)
            assert isinstance(res, ChainDepthComputed)
            assert res.depth == 1
        finally:
            _cleanup(superuser_engine, [e1, e2, e3])

    def test_chain_self_loop_ignored(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        try:
            _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e1
            )
            res = compute_outbound_chain_depth(app_engine, a1, max_hops=4)
            assert isinstance(res, ChainDepthComputed)
            assert res.depth == 0
        finally:
            _cleanup(superuser_engine, [e1])

    def test_parallel_edge_deterministic(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e2, _ = _seed_entity(superuser_engine)
        r_id1 = uuid.UUID(int=1)
        r_id2 = uuid.UUID(int=2)
        try:
            _seed_relationship(
                superuser_engine,
                source_entity_id=e1,
                target_entity_id=e2,
                relationship_id=r_id2,
            )
            _seed_relationship(
                superuser_engine,
                source_entity_id=e1,
                target_entity_id=e2,
                relationship_id=r_id1,
            )
            res = compute_outbound_chain_depth(app_engine, a1, max_hops=4)
            assert isinstance(res, ChainDepthComputed)
            assert res.depth == 1
            assert res.chain_relationship_ids == (r_id1,)
        finally:
            _cleanup(superuser_engine, [e1, e2])

    def test_deterministic_cycle_tie_breaking(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e_a, _ = _seed_entity(superuser_engine, entity_id=uuid.UUID(int=3))
        e_b, _ = _seed_entity(superuser_engine, entity_id=uuid.UUID(int=4))
        try:
            _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e_b
            )
            _seed_relationship(
                superuser_engine, source_entity_id=e_b, target_entity_id=e1
            )

            _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e_a
            )
            _seed_relationship(
                superuser_engine, source_entity_id=e_a, target_entity_id=e1
            )

            res = compute_cycle_through_account(app_engine, a1, max_hops=4)
            assert isinstance(res, CycleFound)
            # Cycle through e_a should win over e_b because
            # UUID(int=3) < UUID(int=4) string-wise
            assert res.cycle_entity_ids == (e1, e_a, e1)
        finally:
            _cleanup(superuser_engine, [e1, e_a, e_b])

    def test_deterministic_chain_tie_breaking(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e_a, _ = _seed_entity(superuser_engine, entity_id=uuid.UUID(int=3))
        e_b, _ = _seed_entity(superuser_engine, entity_id=uuid.UUID(int=4))
        try:
            _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e_b
            )
            _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e_a
            )
            res = compute_outbound_chain_depth(app_engine, a1, max_hops=4)
            assert isinstance(res, ChainDepthComputed)
            assert res.depth == 1
            assert res.chain_entity_ids == (e1, e_a)
        finally:
            _cleanup(superuser_engine, [e1, e_a, e_b])

    def test_read_only(self, superuser_engine: Engine, app_engine: Engine) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        try:
            with superuser_engine.connect() as conn:
                rel_count = conn.execute(
                    text("SELECT count(*) FROM graph_relationships")
                ).scalar()
            compute_outbound_chain_depth(app_engine, a1, max_hops=4)
            with superuser_engine.connect() as conn:
                new_rel_count = conn.execute(
                    text("SELECT count(*) FROM graph_relationships")
                ).scalar()
            assert rel_count == new_rel_count
        finally:
            _cleanup(superuser_engine, [e1])

    def test_repeated_execution_identities(
        self, superuser_engine: Engine, app_engine: Engine
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e2, _ = _seed_entity(superuser_engine)
        try:
            _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e2
            )
            _seed_relationship(
                superuser_engine, source_entity_id=e2, target_entity_id=e1
            )
            res1 = compute_cycle_through_account(app_engine, a1, max_hops=4)
            res2 = compute_cycle_through_account(app_engine, a1, max_hops=4)
            assert res1 == res2

            chain1 = compute_outbound_chain_depth(app_engine, a1, max_hops=4)
            chain2 = compute_outbound_chain_depth(app_engine, a1, max_hops=4)
            assert chain1 == chain2
        finally:
            _cleanup(superuser_engine, [e1, e2])

    def test_cycle_truncation_no_witness(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Mock get_bounded_subgraph to return truncated=True without a witness
        import meridian.agents.graph.structure_signals as signals
        from meridian.agents.graph.subgraph import SubgraphResult

        def mock_subgraph(engine: Any, start_id: Any, hops: Any) -> SubgraphResult:
            return SubgraphResult(
                start_entity_id=start_id,
                max_hops=hops,
                node_entity_ids=(start_id,),
                relationship_ids=(),
                truncated=True,
            )

        monkeypatch.setattr(signals, "get_bounded_subgraph", mock_subgraph)

        e1, a1 = _seed_entity(superuser_engine)
        try:
            res = compute_cycle_through_account(app_engine, a1, max_hops=4)
            assert isinstance(res, CycleIncompleteTruncated)
        finally:
            _cleanup(superuser_engine, [e1])

    def test_cycle_truncation_with_witness(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e2, _ = _seed_entity(superuser_engine)

        try:
            r1 = _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e2
            )
            r2 = _seed_relationship(
                superuser_engine, source_entity_id=e2, target_entity_id=e1
            )

            import meridian.agents.graph.structure_signals as signals
            from meridian.agents.graph.subgraph import SubgraphResult

            def mock_subgraph(engine: Any, start_id: Any, hops: Any) -> SubgraphResult:
                return SubgraphResult(
                    start_entity_id=start_id,
                    max_hops=hops,
                    node_entity_ids=(e1, e2),
                    relationship_ids=(r1, r2),
                    truncated=True,  # Found it but still truncated
                )

            monkeypatch.setattr(signals, "get_bounded_subgraph", mock_subgraph)

            res = compute_cycle_through_account(app_engine, a1, max_hops=4)
            assert isinstance(res, CycleFound)
        finally:
            _cleanup(superuser_engine, [e1, e2])

    def test_chain_truncation(
        self,
        superuser_engine: Engine,
        app_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        e1, a1 = _seed_entity(superuser_engine)
        e2, _ = _seed_entity(superuser_engine)
        try:
            r1 = _seed_relationship(
                superuser_engine, source_entity_id=e1, target_entity_id=e2
            )

            import meridian.agents.graph.structure_signals as signals
            from meridian.agents.graph.subgraph import SubgraphResult

            def mock_subgraph(engine: Any, start_id: Any, hops: Any) -> SubgraphResult:
                return SubgraphResult(
                    start_entity_id=start_id,
                    max_hops=hops,
                    node_entity_ids=(e1, e2),
                    relationship_ids=(r1,),
                    truncated=True,
                )

            monkeypatch.setattr(signals, "get_bounded_subgraph", mock_subgraph)

            res = compute_outbound_chain_depth(app_engine, a1, max_hops=4)
            assert isinstance(res, ChainDepthIncompleteTruncated)
            assert res.lower_bound_depth == 1
        finally:
            _cleanup(superuser_engine, [e1, e2])
