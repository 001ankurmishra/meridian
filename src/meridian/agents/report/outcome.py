"""Investigation outcome definitions."""

import uuid
from dataclasses import dataclass

from meridian.agents.graph.structure_signals import ChainDepthResult, CycleResult
from meridian.agents.graph.subgraph import SubgraphResult
from meridian.agents.policy.policy_agent import PolicyAgentResult
from meridian.agents.transaction.amount_deviation import AmountDeviationResult
from meridian.agents.transaction.beneficiary_age import BeneficiaryAgeResult
from meridian.agents.transaction.transaction_velocity import TransactionVelocityComputed


@dataclass(frozen=True)
class TransactionOutcome:
    """Outcome of the transaction agent."""

    result: AmountDeviationResult
    agent_run_id: uuid.UUID
    velocity_result: TransactionVelocityComputed | None = None
    beneficiary_age_result: BeneficiaryAgeResult | None = None


@dataclass(frozen=True)
class GraphOutcome:
    """Outcome of the graph agent."""

    result: SubgraphResult
    agent_run_id: uuid.UUID
    cycle_result: CycleResult | None = None
    chain_result: ChainDepthResult | None = None


@dataclass(frozen=True)
class PolicyOutcome:
    """Outcome of the policy agent."""

    result: PolicyAgentResult
    agent_run_id: uuid.UUID


@dataclass(frozen=True)
class InvestigationOutcome:
    """The collected results of an investigation run."""

    investigation_run_id: uuid.UUID
    alert_type: str
    transaction: TransactionOutcome | None
    graph: GraphOutcome | None
    policy: PolicyOutcome
