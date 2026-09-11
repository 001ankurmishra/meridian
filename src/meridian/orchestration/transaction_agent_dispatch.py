"""TransactionAgent dispatch slice."""
import uuid
from dataclasses import dataclass

from sqlalchemy import Engine

from meridian.agents.transaction.amount_deviation import (
    AmountDeviationResult,
    compute_amount_deviation,
)
from meridian.orchestration.agent_run_tracking import record_agent_run
from meridian.orchestration.investigation_run import create_investigation_run


@dataclass(frozen=True)
class TransactionAgentDispatchResult:
    """Result of the TransactionAgent dispatch."""

    investigation_run_id: uuid.UUID
    result: AmountDeviationResult


def run_transaction_agent(
    engine: Engine,
    case_id: uuid.UUID,
    transaction_id: uuid.UUID,
) -> TransactionAgentDispatchResult:
    """Dispatch the TransactionAgent for an investigation.

    Args:
        engine: Application-role SQLAlchemy Engine.
        case_id: The UUID of the case to investigate.
        transaction_id: The UUID of the transaction.

    Returns:
        A minimal frozen dataclass with the investigation_run_id and the F3 result.
    """
    inv_run = create_investigation_run(engine, case_id)

    result = record_agent_run(
        engine,
        inv_run.investigation_run_id,
        "TransactionAgent",
        compute_amount_deviation,
        engine,
        transaction_id,
    )

    return TransactionAgentDispatchResult(
        investigation_run_id=inv_run.investigation_run_id,
        result=result,
    )
