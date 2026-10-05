"""TransactionAgent dispatch slice."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Engine

from meridian.agents.transaction.amount_deviation import (
    AmountDeviationResult,
    compute_amount_deviation,
)
from meridian.agents.transaction.beneficiary_age import (
    BeneficiaryAgeResult,
    compute_beneficiary_age,
)
from meridian.agents.transaction.transaction_velocity import (
    TransactionVelocityComputed,
    compute_transaction_velocity,
)
from meridian.orchestration.agent_run_tracking import record_agent_run

# Coarse, per-agent-run tool-call summary for TransactionAgent (F9).
# This describes the fixed, deterministic set of SQL queries
# compute_amount_deviation() is documented and known to run -- it is not
# derived from a live trace of any individual invocation, so it stays
# accurate only as long as it matches that function's actual behavior.
_TRANSACTION_AGENT_TOOL_CALLS = {
    "tool": "sql_query",
    "queries": [
        "transactions: lookup alerted transaction by transaction_id",
        "accounts: resolve source_account_id to customer_id",
        "transactions: trailing 90-day historical outgoing amounts for customer",
        "transactions: trailing 24-hour historical outgoing counts for customer",
        "accounts: resolve destination_account_id to beneficiary record",
    ],
}


@dataclass(frozen=True)
class TransactionAgentDispatchResult:
    """Result of the TransactionAgent dispatch."""

    investigation_run_id: uuid.UUID
    result: AmountDeviationResult
    velocity_result: TransactionVelocityComputed | None = None
    beneficiary_age_result: BeneficiaryAgeResult | None = None


def _run_all_transaction_computations(
    engine: Engine, transaction_id: uuid.UUID
) -> tuple[
    AmountDeviationResult,
    TransactionVelocityComputed | None,
    BeneficiaryAgeResult | None,
]:
    # Amount deviation must execute first and preserve its current behavior
    amt_result = compute_amount_deviation(engine, transaction_id)
    vel_result = compute_transaction_velocity(engine, transaction_id)
    ben_result = compute_beneficiary_age(engine, transaction_id)
    return amt_result, vel_result, ben_result


def run_transaction_agent(
    engine: Engine,
    investigation_run_id: uuid.UUID,
    transaction_id: uuid.UUID,
    agent_run_id: uuid.UUID | None = None,
) -> TransactionAgentDispatchResult:
    """Run the TransactionAgent (compute_amount_deviation).

    Args:
        engine: Application-role SQLAlchemy Engine.
        investigation_run_id: The UUID of the current investigation run.
        transaction_id: The UUID of the transaction to analyze.
        agent_run_id: Optional ID for the agent run.

    Returns:
        A minimal frozen dataclass with the investigation_run_id and the F3 result.
    """
    result = record_agent_run(
        engine,
        investigation_run_id,
        "TransactionAgent",
        _run_all_transaction_computations,
        engine,
        transaction_id,
        tool_calls=_TRANSACTION_AGENT_TOOL_CALLS,
        agent_run_id=agent_run_id,
    )

    return TransactionAgentDispatchResult(
        investigation_run_id=investigation_run_id,
        result=result[0],
        velocity_result=result[1],
        beneficiary_age_result=result[2],
    )
