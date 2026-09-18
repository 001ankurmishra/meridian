"""Orchestrator for the F2 MVP.

Manages agent dispatch sequence, evidence evaluation, and investigation lifecycle.
"""
# ruff: noqa: E501

import uuid
from datetime import datetime, timezone

from sqlalchemy import Engine, text

from meridian.agents.policy.policy_agent import PolicyEvidenceFound
from meridian.agents.transaction.amount_deviation import (
    AmountDeviationComputed,
)
from meridian.orchestration.errors import InvestigationError
from meridian.orchestration.graph_agent_dispatch import run_graph_agent
from meridian.orchestration.investigation_run import create_investigation_run
from meridian.orchestration.policy_agent_dispatch import run_policy_agent
from meridian.orchestration.transaction_agent_dispatch import run_transaction_agent


def orchestrate_investigation(engine: Engine, case_id: uuid.UUID) -> str:
    """Execute the locked F2 investigation orchestration workflow.

    Args:
        engine: Application-role SQLAlchemy Engine.
        case_id: The UUID of the case to investigate.

    Returns:
        The final status string (e.g., 'COMPLETE', 'INCOMPLETE_INSUFFICIENT_EVIDENCE').

    Raises:
        InvestigationError: If the case does not exist, is not OPEN, or already
            has an investigation run.
        Exception: Any hard failure from an agent, after recording the run as FAILED.
    """
    with engine.begin() as conn:
        case_row = conn.execute(
            text("SELECT alert_id, status FROM cases WHERE case_id = :cid"),
            {"cid": case_id},
        ).fetchone()

        if not case_row:
            raise InvestigationError(f"Case {case_id} not found.")
        if case_row.status != "OPEN":
            raise InvestigationError(f"Case {case_id} is not OPEN.")

        inv_row = conn.execute(
            text("SELECT 1 FROM investigation_runs WHERE case_id = :cid"),
            {"cid": case_id},
        ).fetchone()
        if inv_row:
            raise InvestigationError(
                f"Case {case_id} already has an investigation run."
            )

        alert_row = conn.execute(
            text(
                "SELECT customer_id, transaction_id, alert_type FROM alerts WHERE alert_id = :aid"
            ),
            {"aid": case_row.alert_id},
        ).fetchone()
        if not alert_row:
            raise InvestigationError(f"Alert {case_row.alert_id} not found.")

    # Step 4.2 - Create investigation run
    inv_run = create_investigation_run(engine, case_id)
    inv_id = inv_run.investigation_run_id

    def _mark_failed(exc: Exception) -> None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE investigation_runs SET status = 'FAILED', "
                    "completed_at = :now WHERE investigation_run_id = :inv_id"
                ),
                {"now": datetime.now(timezone.utc), "inv_id": inv_id},
            )
        raise exc

    has_tx_evidence = False
    has_policy_evidence = False
    tx_result = None

    # Step 4.3 - Agent Dispatch

    # 1. TransactionAgent
    if alert_row.transaction_id is not None:
        try:
            dispatch_result = run_transaction_agent(
                engine, inv_id, alert_row.transaction_id
            )
            tx_result = dispatch_result.result
            if isinstance(tx_result, AmountDeviationComputed):
                has_tx_evidence = True
        except Exception as e:
            _mark_failed(e)

    # 2. GraphAgent
    if has_tx_evidence and isinstance(tx_result, AmountDeviationComputed):
        try:
            run_graph_agent(engine, inv_id, tx_result.source_account_id, max_hops=3)
        except Exception as e:
            _mark_failed(e)

    # 3. PolicyAgent
    try:
        policy_dispatch_result = run_policy_agent(engine, inv_id, alert_row.alert_type)
        if isinstance(policy_dispatch_result, PolicyEvidenceFound):
            has_policy_evidence = True
    except Exception as e:
        _mark_failed(e)

    # Step 4.4 - Orchestrator Status Conclusion
    if has_tx_evidence and has_policy_evidence:
        final_status = "COMPLETE"
    else:
        final_status = "INCOMPLETE_INSUFFICIENT_EVIDENCE"

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE investigation_runs SET status = :status, "
                "completed_at = :now WHERE investigation_run_id = :inv_id"
            ),
            {
                "status": final_status,
                "now": datetime.now(timezone.utc),
                "inv_id": inv_id,
            },
        )

    return final_status
