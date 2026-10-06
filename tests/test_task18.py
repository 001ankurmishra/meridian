"""Task 18 graph structure signal authoring unit tests."""

import uuid

import pytest

from meridian.agents.graph.structure_signals import (
    ChainDepthComputed,
    ChainDepthIncompleteTruncated,
    CycleFound,
    CycleIncompleteTruncated,
    CycleNotFound,
)
from meridian.agents.graph.subgraph import SubgraphResult
from meridian.agents.policy.policy_agent import (
    PolicyEvidenceInsufficient,
)
from meridian.agents.report.authoring import build_authoring_drafts
from meridian.agents.report.outcome import (
    GraphOutcome,
    InvestigationOutcome,
    PolicyOutcome,
)


def _make_dummy_outcome(
    graph_outcome: GraphOutcome | None = None,
) -> InvestigationOutcome:
    return InvestigationOutcome(
        investigation_run_id=uuid.uuid4(),
        alert_type="test",
        transaction=None,
        graph=graph_outcome,
        policy=PolicyOutcome(
            result=PolicyEvidenceInsufficient(), agent_run_id=uuid.uuid4()
        ),
    )


def test_authoring_suppresses_cycle_not_found() -> None:
    dummy_subgraph = SubgraphResult(
        start_entity_id=uuid.uuid4(),
        max_hops=3,
        node_entity_ids=(),
        relationship_ids=(),
        truncated=False,
    )
    graph_outcome = GraphOutcome(
        result=dummy_subgraph,
        agent_run_id=uuid.uuid4(),
        cycle_result=CycleNotFound(account_id=uuid.uuid4()),
    )
    drafts = build_authoring_drafts(_make_dummy_outcome(graph_outcome))
    assert not any("cycle" in e.key for e in drafts.evidence)
    assert not any("cycle" in f.observed_fact.lower() for f in drafts.findings)


def test_authoring_suppresses_cycle_truncated() -> None:
    dummy_subgraph = SubgraphResult(
        start_entity_id=uuid.uuid4(),
        max_hops=3,
        node_entity_ids=(),
        relationship_ids=(),
        truncated=False,
    )
    graph_outcome = GraphOutcome(
        result=dummy_subgraph,
        agent_run_id=uuid.uuid4(),
        cycle_result=CycleIncompleteTruncated(account_id=uuid.uuid4()),
    )
    drafts = build_authoring_drafts(_make_dummy_outcome(graph_outcome))
    assert not any("cycle" in e.key for e in drafts.evidence)
    assert not any("cycle" in f.observed_fact.lower() for f in drafts.findings)


def test_authoring_authors_cycle_found() -> None:
    agent_run_id = uuid.uuid4()
    rel_ids = (uuid.uuid4(), uuid.uuid4())
    dummy_subgraph = SubgraphResult(
        start_entity_id=uuid.uuid4(),
        max_hops=3,
        node_entity_ids=(),
        relationship_ids=(),
        truncated=False,
    )
    graph_outcome = GraphOutcome(
        result=dummy_subgraph,
        agent_run_id=agent_run_id,
        cycle_result=CycleFound(
            account_id=uuid.uuid4(),
            cycle_entity_ids=(uuid.uuid4(), uuid.uuid4()),
            cycle_relationship_ids=rel_ids,
        ),
    )
    drafts = build_authoring_drafts(_make_dummy_outcome(graph_outcome))

    # Verify evidence
    cycle_ev = [
        e for e in drafts.evidence if e.evidence_type == "graph_cycle_relationship"
    ]
    assert len(cycle_ev) == 2
    assert {e.reference_id for e in cycle_ev} == set(rel_ids)

    # Verify finding
    cycle_finding = [f for f in drafts.findings if "Graph cycle:" in f.observed_fact]
    assert len(cycle_finding) == 1
    assert "2 directed TRANSACTED_WITH relationship(s)" in (
        cycle_finding[0].observed_fact or ""
    )
    assert "PROTOTYPE" in (cycle_finding[0].interpretation or "")
    assert set(cycle_finding[0].evidence_keys) == {e.key for e in cycle_ev}
    assert all(e.agent_run_id == agent_run_id for e in cycle_ev)


def test_authoring_suppresses_chain_depth_0() -> None:
    dummy_subgraph = SubgraphResult(
        start_entity_id=uuid.uuid4(),
        max_hops=3,
        node_entity_ids=(),
        relationship_ids=(),
        truncated=False,
    )
    graph_outcome = GraphOutcome(
        result=dummy_subgraph,
        agent_run_id=uuid.uuid4(),
        chain_result=ChainDepthComputed(
            account_id=uuid.uuid4(),
            depth=0,
            chain_entity_ids=(uuid.uuid4(),),
            chain_relationship_ids=(),
        ),
    )
    drafts = build_authoring_drafts(_make_dummy_outcome(graph_outcome))
    assert not any("chain" in e.key for e in drafts.evidence)
    assert not any("chain" in f.observed_fact.lower() for f in drafts.findings)


def test_authoring_suppresses_chain_truncated() -> None:
    dummy_subgraph = SubgraphResult(
        start_entity_id=uuid.uuid4(),
        max_hops=3,
        node_entity_ids=(),
        relationship_ids=(),
        truncated=False,
    )
    graph_outcome = GraphOutcome(
        result=dummy_subgraph,
        agent_run_id=uuid.uuid4(),
        chain_result=ChainDepthIncompleteTruncated(
            account_id=uuid.uuid4(),
            lower_bound_depth=3,
            chain_entity_ids=(),
            chain_relationship_ids=(),
        ),
    )
    drafts = build_authoring_drafts(_make_dummy_outcome(graph_outcome))
    assert not any("chain" in e.key for e in drafts.evidence)
    assert not any("chain" in f.observed_fact.lower() for f in drafts.findings)


@pytest.mark.parametrize("depth", [1, 2, 3, 4])
def test_authoring_authors_chain_depth_1_plus(depth: int) -> None:
    agent_run_id = uuid.uuid4()
    rel_ids = tuple(uuid.uuid4() for _ in range(depth))
    dummy_subgraph = SubgraphResult(
        start_entity_id=uuid.uuid4(),
        max_hops=3,
        node_entity_ids=(),
        relationship_ids=(),
        truncated=False,
    )
    graph_outcome = GraphOutcome(
        result=dummy_subgraph,
        agent_run_id=agent_run_id,
        chain_result=ChainDepthComputed(
            account_id=uuid.uuid4(),
            depth=depth,
            chain_entity_ids=tuple(uuid.uuid4() for _ in range(depth + 1)),
            chain_relationship_ids=rel_ids,
        ),
    )
    drafts = build_authoring_drafts(_make_dummy_outcome(graph_outcome))

    # Verify evidence
    chain_ev = [
        e for e in drafts.evidence if e.evidence_type == "graph_chain_relationship"
    ]
    assert len(chain_ev) == depth
    assert {e.reference_id for e in chain_ev} == set(rel_ids)

    # Verify finding
    chain_finding = [f for f in drafts.findings if "Graph chain:" in f.observed_fact]
    assert len(chain_finding) == 1
    assert f"chain of depth {depth}" in (chain_finding[0].observed_fact or "")
    assert "PROTOTYPE" in (chain_finding[0].interpretation or "")
    assert set(chain_finding[0].evidence_keys) == {e.key for e in chain_ev}
    assert all(e.agent_run_id == agent_run_id for e in chain_ev)
