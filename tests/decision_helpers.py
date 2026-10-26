"""Seed an evidence-backed COMPLETE report for decision boundary tests."""

import uuid

from sqlalchemy import Engine, text

from meridian.evidence.evidence import record_evidence_with_connection
from meridian.findings.findings import record_finding_with_connection
from meridian.recommendations.recommendations import (
    record_recommendation_with_connection,
)


def seed_supported_report(engine: Engine, case_id: uuid.UUID) -> uuid.UUID:
    run, agent = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        customer = conn.execute(
            text(
                "SELECT a.customer_id FROM alerts a "
                "JOIN cases c ON c.alert_id=a.alert_id "
                "WHERE c.case_id=:c"
            ),
            {"c": case_id},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO investigation_runs "
                "(investigation_run_id,case_id,status,started_at,"
                "completed_at,created_at) "
                "VALUES (:r,:c,'COMPLETE',now(),now(),now())"
            ),
            {"r": run, "c": case_id},
        )
        conn.execute(
            text(
                "INSERT INTO agent_runs "
                "(agent_run_id,investigation_run_id,agent_name,status,"
                "started_at,tool_calls) "
                "VALUES (:a,:r,'TestAgent','SUCCESS',now(),'[]')"
            ),
            {"a": agent, "r": run},
        )
        evidence = record_evidence_with_connection(
            conn, run, "customer_reference", "customers", customer, agent
        )
        finding = record_finding_with_connection(
            conn,
            run,
            "Synthetic customer record exists",
            None,
            "Source is available for human review",
            [evidence.evidence_id],
            "LOW",
        )
        record_recommendation_with_connection(
            conn,
            run,
            "Review the referenced synthetic customer record",
            [finding.finding_id],
        )
    return run
