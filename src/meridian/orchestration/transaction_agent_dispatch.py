"""TransactionAgent dispatch slice."""
import uuid
from dataclasses import dataclass

from sqlalchemy import Engine

from meridian.agents.transaction.amount_deviation import (
    AmountDeviationResult,
    compute_amount_deviation,
)
from meridian.orchestration.agent_run_tracking import record_agent_run


@dataclass(frozen=True)
class TransactionAgentDispatchResult:
    """Result of the TransactionAgent dispatch."""

    investigation_run_id: uuid.UUID
    result: AmountDeviationResult


def run_transaction_agent(
    engine: Engine,
    investigation_run_id: uuid.UUID,
    transaction_id: uuid.UUID,
) -> TransactionAgentDispatchResult:
    """Dispatch the TransactionAgent for an investigation.

    Args:
        engine: Application-role SQLAlchemy Engine.
        investigation_run_id: The UUID of the active investigation run.
        transaction_id: The UUID of the transaction.

    Returns:
        A minimal frozen dataclass with the investigation_run_id and the F3 result.
    """
    result = record_agent_run(
        engine,
        investigation_run_id,
        "TransactionAgent",
        compute_amount_deviation,
        engine,
        transaction_id,
    )

    return TransactionAgentDispatchResult(
        investigation_run_id=investigation_run_id,
        result=result,
    )
