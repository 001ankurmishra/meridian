"""TransactionAgent dispatch slice."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Engine

from meridian.agents.transaction.amount_deviation import (
    AmountDeviationResult,
    compute_amount_deviation,
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
    ],
}


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
        tool_calls=_TRANSACTION_AGENT_TOOL_CALLS,
    )

    return TransactionAgentDispatchResult(
        investigation_run_id=investigation_run_id,
        result=result,
    )
