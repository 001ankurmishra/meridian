"""Orchestrator for the F2 MVP.

Manages agent dispatch sequence, evidence evaluation, and investigation lifecycle.
"""
# ruff: noqa: E501

import uuid
from datetime import datetime, timezone

from sqlalchemy import Engine, text

from meridian.agents.policy.policy_agent import PolicyEvidenceFound
from meridian.agents.report.authoring import author_investigation_records
from meridian.agents.report.outcome import (
    GraphOutcome,
    InvestigationOutcome,
    PolicyOutcome,
    TransactionOutcome,
)
from meridian.agents.transaction.amount_deviation import (
    AmountDeviationComputed,
    AmountDeviationUnknown,
)
from meridian.orchestration.errors import InvestigationError
from meridian.orchestration.graph_agent_dispatch import run_graph_agent
from meridian.orchestration.investigation_run import create_investigation_run
from meridian.orchestration.policy_agent_dispatch import run_policy_agent
from meridian.orchestration.transaction_agent_dispatch import run_transaction_agent
from meridian.risk_engine.risk_signals import (
    compute_risk_score,
    record_risk_signal_with_connection,
)


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

    has_tx_evidence = False
    has_policy_evidence = False
    tx_result = None
    fatal_error = None

    tx_outcome: TransactionOutcome | None = None
    graph_outcome: GraphOutcome | None = None
    policy_outcome: PolicyOutcome | None = None

    # Step 4.3 - Agent Dispatch

    # 1. TransactionAgent
    if alert_row.transaction_id is not None:
        try:
            agent_run_id = uuid.uuid4()
            dispatch_result = run_transaction_agent(
                engine, inv_id, alert_row.transaction_id, agent_run_id=agent_run_id
            )
            tx_result = dispatch_result.result
            if isinstance(tx_result, AmountDeviationComputed):
                has_tx_evidence = True
            tx_outcome = TransactionOutcome(result=tx_result, agent_run_id=agent_run_id)
        except Exception as e:
            fatal_error = e

    # 2. GraphAgent
    if isinstance(tx_result, (AmountDeviationComputed, AmountDeviationUnknown)):
        try:
            agent_run_id = uuid.uuid4()
            graph_dispatch_result = run_graph_agent(
                engine,
                inv_id,
                tx_result.source_account_id,
                max_hops=3,
                agent_run_id=agent_run_id,
            )
            graph_outcome = GraphOutcome(
                result=graph_dispatch_result.result, agent_run_id=agent_run_id
            )
        except Exception:
            # GraphAgent failure does NOT determine final investigation status
            pass

    # 3. PolicyAgent
    try:
        agent_run_id = uuid.uuid4()
        policy_dispatch_result = run_policy_agent(
            engine, inv_id, alert_row.alert_type, agent_run_id=agent_run_id
        )
        if isinstance(policy_dispatch_result, PolicyEvidenceFound):
            has_policy_evidence = True
        policy_outcome = PolicyOutcome(
            result=policy_dispatch_result, agent_run_id=agent_run_id
        )
    except Exception as e:
        if fatal_error is None:
            fatal_error = e

    # Step 4.4 - Orchestrator Status Conclusion
    if fatal_error is not None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE investigation_runs SET status = 'FAILED', "
                    "completed_at = :now WHERE investigation_run_id = :inv_id"
                ),
                {"now": datetime.now(timezone.utc), "inv_id": inv_id},
            )
        raise fatal_error
    if has_tx_evidence and has_policy_evidence:
        final_status = "COMPLETE"
    else:
        final_status = "INCOMPLETE_INSUFFICIENT_EVIDENCE"

    if policy_outcome is not None:
        outcome = InvestigationOutcome(
            investigation_run_id=inv_id,
            alert_type=alert_row.alert_type,
            transaction=tx_outcome,
            graph=graph_outcome,
            policy=policy_outcome,
        )
        try:
            with engine.begin() as conn:
                author_investigation_records(conn, outcome)

                if isinstance(tx_result, AmountDeviationComputed):
                    risk_score_result = compute_risk_score(tx_result)
                    record_risk_signal_with_connection(
                        conn=conn,
                        investigation_run_id=inv_id,
                        customer_id=alert_row.customer_id,
                        transaction_id=alert_row.transaction_id,
                        result=risk_score_result,
                    )
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
        except Exception as e:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE investigation_runs SET status = 'FAILED', "
                        "completed_at = :now WHERE investigation_run_id = :inv_id"
                    ),
                    {"now": datetime.now(timezone.utc), "inv_id": inv_id},
                )
            raise e
    else:
        # Fallback if policy_outcome is somehow None but fatal_error was not raised.
        # This shouldn't happen, but satisfies types and invariants.
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
