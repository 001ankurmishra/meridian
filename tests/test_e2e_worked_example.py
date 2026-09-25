"""Phase 1 end-to-end worked-example integration test.

Exercises the full Meridian pipeline on real infrastructure with nothing simulated:
load → intake → orchestrate → report → decision → audit trail.

Requires LOADER_DATABASE_URL and DATABASE_URL environment variables.
"""

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, text

from meridian.agents.report.report_assembly import assemble_report
from meridian.audit.audit_trail import get_case_audit_trail
from meridian.case_management.alert_intake import create_alert_and_case
from meridian.evidence.evidence import (
    EVIDENCE_TYPE_ALERTED_TRANSACTION,
    EVIDENCE_TYPE_AMOUNT_DEVIATION_INPUT,
    EVIDENCE_TYPE_POLICY_CHUNK,
)
from meridian.loader.worked_example import generate_worked_example
from meridian.orchestration.investigation_orchestrator import (
    orchestrate_investigation,
)
from meridian.review.decisions import record_human_decision


def _find_rahul_fixture() -> (
    tuple[uuid.UUID, uuid.UUID, uuid.UUID]
):
    """Return (customer_id, account_id, transaction_980k_id) from the
    worked-example generator output."""
    we = generate_worked_example()

    rahul_customer: dict[str, Any] | None = None
    for c in we["customers"]:
        if c["full_name"] == "Rahul Sharma":
            rahul_customer = c
            break
    assert rahul_customer is not None, "Rahul Sharma not in worked example"
    customer_id: uuid.UUID = rahul_customer["customer_id"]

    rahul_account: dict[str, Any] | None = None
    for a in we["accounts"]:
        if a["customer_id"] == customer_id:
            rahul_account = a
            break
    assert rahul_account is not None, "Rahul account not found"
    account_id: uuid.UUID = rahul_account["account_id"]

    target_tx: dict[str, Any] | None = None
    for t in we["transactions"]:
        if (
            t["source_account_id"] == account_id
            and Decimal(str(t["amount"])) == Decimal("980000.00")
        ):
            target_tx = t
            break
    assert target_tx is not None, "980000 transaction not found"
    transaction_id: uuid.UUID = target_tx["transaction_id"]

    return customer_id, account_id, transaction_id


def _verify_referenced_row(
    conn: object,
    reference_table: str,
    reference_id: uuid.UUID,
) -> None:
    """Confirm that (reference_table, reference_id) resolves to a real
    row, using an allow-list of known tables."""
    assert hasattr(conn, "execute")  # typing guard
    if reference_table == "transactions":
        row = conn.execute(
            text(
                "SELECT 1 FROM transactions "
                "WHERE transaction_id = :rid"
            ),
            {"rid": reference_id},
        ).scalar()
        assert row is not None, (
            f"transactions row {reference_id} not found"
        )
    elif reference_table == "document_chunks":
        row = conn.execute(
            text(
                "SELECT 1 FROM document_chunks "
                "WHERE chunk_id = :rid"
            ),
            {"rid": reference_id},
        ).scalar()
        assert row is not None, (
            f"document_chunks row {reference_id} not found"
        )
    else:
        raise AssertionError(
            f"Unexpected reference_table: {reference_table}"
        )


def test_worked_example_end_to_end(
    superuser_engine: Engine,
    app_role_engine: Engine,
) -> None:
    """Full Phase 1 pipeline on real data, real embeddings, nothing simulated."""
    loader_url = os.environ.get("LOADER_DATABASE_URL")
    db_url = os.environ.get("DATABASE_URL")
    if not loader_url or not db_url:
        pytest.skip(
            "LOADER_DATABASE_URL or DATABASE_URL not set"
        )

    # --- Derive fixture identifiers from the generator ---
    customer_id, account_id, transaction_id = (
        _find_rahul_fixture()
    )

    # IDs created during the test, for cleanup
    analyst_id = uuid.uuid4()
    alert_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None

    # ==================== PRE-CLEAN ====================
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events"))
        conn.execute(text("DELETE FROM risk_signals"))
        conn.execute(text("DELETE FROM recommendations"))
        conn.execute(text("DELETE FROM findings"))
        conn.execute(text("DELETE FROM evidence"))
        conn.execute(text("DELETE FROM agent_runs"))
        conn.execute(text("DELETE FROM risk_signals"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))

    # ==================== LOAD ====================
    from meridian.loader.main import main as loader_main

    loader_main()

    # Confirm fixture rows exist
    with superuser_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT customer_id FROM customers "
                "WHERE customer_id = :cid"
            ),
            {"cid": customer_id},
        ).scalar()
        assert row is not None, "Rahul customer row missing"

        row = conn.execute(
            text(
                "SELECT account_id FROM accounts "
                "WHERE account_id = :aid"
            ),
            {"aid": account_id},
        ).scalar()
        assert row is not None, "Rahul account row missing"

        row = conn.execute(
            text(
                "SELECT transaction_id FROM transactions "
                "WHERE transaction_id = :tid"
            ),
            {"tid": transaction_id},
        ).scalar()
        assert row is not None, "980k transaction row missing"

    try:
        # ================== ANALYST ==================
        now = datetime.now(timezone.utc)
        analyst_email = f"analyst-{analyst_id}@e2e.test"
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users "
                    "(user_id, email, role, created_at) "
                    "VALUES (:uid, :email, :role, :now)"
                ),
                {
                    "uid": analyst_id,
                    "email": analyst_email,
                    "role": "analyst",
                    "now": now,
                },
            )

        # ================== INTAKE ==================
        intake = create_alert_and_case(
            app_role_engine,
            customer_id,
            "large_transaction",
            ["large_transaction", "new_beneficiary", "rapid_movement"],
            transaction_id=transaction_id,
            source_system="e2e-test",
        )
        alert_id = intake.alert_id
        case_id = intake.case_id

        # Assign analyst
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE cases "
                    "SET assigned_analyst_id = :aid "
                    "WHERE case_id = :cid"
                ),
                {"aid": analyst_id, "cid": case_id},
            )

        # ================ ORCHESTRATE ================
        status = orchestrate_investigation(
            app_role_engine, case_id
        )

        # --- 7a: Investigation completion ---
        assert status == "COMPLETE", (
            f"Orchestration status: {status}"
        )

        with app_role_engine.connect() as conn:
            inv_rows = conn.execute(
                text(
                    "SELECT investigation_run_id, status, "
                    "completed_at "
                    "FROM investigation_runs "
                    "WHERE case_id = :cid"
                ),
                {"cid": case_id},
            ).fetchall()

        assert len(inv_rows) == 1, (
            f"Expected 1 inv run, got {len(inv_rows)}"
        )
        run_id = inv_rows[0][0]
        assert inv_rows[0][1] == "COMPLETE"
        assert inv_rows[0][2] is not None  # completed_at

        # --- 7b: Agent runs ---
        with app_role_engine.connect() as conn:
            agent_rows = conn.execute(
                text(
                    "SELECT agent_name, status "
                    "FROM agent_runs "
                    "WHERE investigation_run_id = :rid"
                ),
                {"rid": run_id},
            ).fetchall()

        agent_names = {r[0] for r in agent_rows}
        assert "TransactionAgent" in agent_names
        assert "PolicyAgent" in agent_names
        for r in agent_rows:
            assert r[1] == "SUCCESS", (
                f"Agent {r[0]} status: {r[1]}"
            )

        # --- 7c: Findings and evidence ---
        with app_role_engine.connect() as conn:
            ev_rows = conn.execute(
                text(
                    "SELECT evidence_id, evidence_type, "
                    "reference_table, reference_id, "
                    "investigation_run_id "
                    "FROM evidence "
                    "WHERE investigation_run_id = :rid"
                ),
                {"rid": run_id},
            ).fetchall()
            finding_rows = conn.execute(
                text(
                    "SELECT finding_id, evidence_ids "
                    "FROM findings "
                    "WHERE investigation_run_id = :rid"
                ),
                {"rid": run_id},
            ).fetchall()

        assert len(ev_rows) > 0, "No evidence rows"
        assert len(finding_rows) > 0, "No finding rows"

        db_evidence_ids = {r[0] for r in ev_rows}
        ev_by_id = {
            r[0]: {
                "evidence_type": r[1],
                "reference_table": r[2],
                "reference_id": r[3],
                "investigation_run_id": r[4],
            }
            for r in ev_rows
        }

        db_finding_ids = [r[0] for r in finding_rows]

        # Identify INVESTIGATIVE finding(s) - cites
        # EVIDENCE_TYPE_ALERTED_TRANSACTION
        investigative_finding_ids: list[uuid.UUID] = []
        policy_finding_count = 0

        for f_row in finding_rows:
            f_id = f_row[0]
            f_ev_ids: list[uuid.UUID] = f_row[1]
            cites_alerted = any(
                ev_by_id[eid]["evidence_type"]
                == EVIDENCE_TYPE_ALERTED_TRANSACTION
                for eid in f_ev_ids
                if eid in ev_by_id
            )
            all_policy = all(
                ev_by_id[eid]["evidence_type"]
                == EVIDENCE_TYPE_POLICY_CHUNK
                for eid in f_ev_ids
                if eid in ev_by_id
            )
            if cites_alerted:
                investigative_finding_ids.append(f_id)
            if all_policy and len(f_ev_ids) > 0:
                policy_finding_count += 1

        assert len(investigative_finding_ids) == 1, (
            f"Expected 1 INVESTIGATIVE finding, "
            f"got {len(investigative_finding_ids)}"
        )
        assert policy_finding_count >= 1, (
            "No policy-reference finding found"
        )

        # --- 7d: Evidence integrity ---
        has_deviation_input = False
        with app_role_engine.connect() as conn:
            for f_row in finding_rows:
                f_ev_ids = f_row[1]
                assert len(f_ev_ids) > 0, (
                    f"Finding {f_row[0]} has empty evidence_ids"
                )
                for eid in f_ev_ids:
                    assert eid in ev_by_id, (
                        f"Evidence {eid} not in run"
                    )
                    ev = ev_by_id[eid]
                    assert (
                        ev["investigation_run_id"] == run_id
                    )
                    _verify_referenced_row(
                        conn,
                        ev["reference_table"],
                        ev["reference_id"],
                    )
                    if (
                        ev["evidence_type"]
                        == EVIDENCE_TYPE_ALERTED_TRANSACTION
                    ):
                        assert (
                            ev["reference_id"]
                            == transaction_id
                        )
                    if (
                        ev["evidence_type"]
                        == EVIDENCE_TYPE_AMOUNT_DEVIATION_INPUT
                    ):
                        has_deviation_input = True

        assert has_deviation_input, (
            "No amount_deviation_input evidence found"
        )

        # --- 7e: No autonomous disposition ---
        with app_role_engine.connect() as conn:
            case_row = conn.execute(
                text(
                    "SELECT status, closed_at "
                    "FROM cases WHERE case_id = :cid"
                ),
                {"cid": case_id},
            ).first()
            assert case_row is not None
            assert case_row[0] == "OPEN"
            assert case_row[1] is None

            audit_count_raw = conn.execute(
                text(
                    "SELECT count(*) FROM audit_events "
                    "WHERE case_id = :cid"
                ),
                {"cid": case_id},
            ).scalar()
            assert audit_count_raw == 0

            acct_rows = conn.execute(
                text(
                    "SELECT status FROM accounts "
                    "WHERE customer_id = :cid"
                ),
                {"cid": customer_id},
            ).fetchall()
            for ar in acct_rows:
                assert ar[0] == "active"

        # --- 7f: Report ---
        report = assemble_report(app_role_engine, run_id)

        assert report.investigation_run_id == run_id
        assert report.case_id == case_id
        assert report.human_review_required is True
        assert report.is_synthetic is True
        assert (
            report.evidence_completeness_status == "COMPLETE"
        )
        report_finding_ids = [
            f.finding_id for f in report.findings
        ]
        assert report_finding_ids == db_finding_ids

        # --- 7g: Policy classification (the integration
        #         defect) ---
        assert len(report.applicable_policies) > 0, (
            "applicable_policies is empty — policy "
            "classification bug not fixed"
        )
        for p in report.applicable_policies:
            assert (
                p.evidence_type == EVIDENCE_TYPE_POLICY_CHUNK
            )
            assert p.reference_table == "document_chunks"

        # Every referenced chunk belongs to a synthetic doc
        with app_role_engine.connect() as conn:
            for p in report.applicable_policies:
                is_syn = conn.execute(
                    text(
                        "SELECT d.is_synthetic "
                        "FROM document_chunks dc "
                        "JOIN documents d "
                        "  ON dc.document_id = d.document_id "
                        "WHERE dc.chunk_id = :cid"
                    ),
                    {"cid": p.reference_id},
                ).scalar()
                assert is_syn is True, (
                    f"Chunk {p.reference_id} not from "
                    "synthetic document"
                )

        assert len(report.evidence) > 0
        for e in report.evidence:
            assert (
                e.evidence_type != EVIDENCE_TYPE_POLICY_CHUNK
            ), "Policy evidence leaked into report.evidence"

        # Union / disjoint check
        report_ev_ids = {
            e.evidence_id for e in report.evidence
        }
        policy_ev_ids = {
            p.evidence_id for p in report.applicable_policies
        }
        all_finding_ev_ids: set[uuid.UUID] = set()
        for f in finding_rows:
            all_finding_ev_ids.update(f[1])

        assert report_ev_ids | policy_ev_ids == (
            all_finding_ev_ids
        ), "Union mismatch"
        assert (
            len(report_ev_ids & policy_ev_ids) == 0
        ), "Overlap between evidence and policies"

        # --- 7h: Recommendation (F7 Slice 2) ---
        with app_role_engine.connect() as conn:
            rec_rows = conn.execute(
                text(
                    "SELECT recommendation_id, "
                    "investigation_run_id, "
                    "based_on_finding_ids "
                    "FROM recommendations "
                    "WHERE investigation_run_id = :rid"
                ),
                {"rid": run_id},
            ).fetchall()

        assert len(rec_rows) == 1, (
            f"Expected 1 recommendation, got {len(rec_rows)}"
        )
        assert len(report.recommendations) == 1
        assert rec_rows[0][1] == run_id
        assert rec_rows[0][2] == [
            investigative_finding_ids[0]
        ]

        # --- 7i: Synthetic labeling ---
        with app_role_engine.connect() as conn:
            is_syn = conn.execute(
                text(
                    "SELECT is_synthetic FROM customers "
                    "WHERE customer_id = :cid"
                ),
                {"cid": customer_id},
            ).scalar()
        assert is_syn is True

        # ============= 8: HUMAN DECISION =============
        decision = record_human_decision(
            app_role_engine,
            case_id,
            analyst_id,
            "APPROVE",
            None,
        )
        assert decision.previous_status == "OPEN"
        assert decision.new_status == "CLOSED_APPROVED"

        with app_role_engine.connect() as conn:
            acct_rows = conn.execute(
                text(
                    "SELECT status FROM accounts "
                    "WHERE customer_id = :cid"
                ),
                {"cid": customer_id},
            ).fetchall()
            for ar in acct_rows:
                assert ar[0] == "active"

        # ============= 9: AUDIT TRAIL =============
        trail = get_case_audit_trail(
            app_role_engine, case_id
        )
        assert trail.case_status == "CLOSED_APPROVED"
        assert len(trail.investigation_runs) == 1
        ir = trail.investigation_runs[0]
        assert ir.status == "COMPLETE"

        trail_agent_names = {
            ar.agent_name for ar in ir.agent_runs
        }
        assert "TransactionAgent" in trail_agent_names
        assert "PolicyAgent" in trail_agent_names

        trail_ev_ids = {e.evidence_id for e in ir.evidence}
        assert trail_ev_ids == db_evidence_ids

        trail_finding_ids = {
            f.finding_id for f in ir.findings
        }
        assert trail_finding_ids == set(db_finding_ids)

        for f_entry in ir.findings:
            assert set(f_entry.evidence_ids).issubset(
                trail_ev_ids
            )

        assert len(trail.audit_events) == 1
        evt = trail.audit_events[0]
        assert evt.actor_type == "human"
        assert evt.actor_id == str(analyst_id)
        assert evt.action == "CASE_APPROVED"
        assert (
            evt.output_summary is not None
        )
        assert (
            evt.output_summary["to_status"]
            == "CLOSED_APPROVED"
        )
        assert (
            evt.output_summary["from_status"] == "OPEN"
        )

    finally:
        # ============= 10: CLEANUP =============
        with superuser_engine.begin() as conn:
            if case_id is not None:
                conn.execute(
                    text(
                        "DELETE FROM audit_events "
                        "WHERE case_id = :cid"
                    ),
                    {"cid": case_id},
                )
            if run_id is not None:
                conn.execute(
                    text(
                        "DELETE FROM risk_signals "
                        "WHERE investigation_run_id = :rid"
                    ),
                    {"rid": run_id},
                )
                conn.execute(
                    text(
                        "DELETE FROM recommendations "
                        "WHERE investigation_run_id = :rid"
                    ),
                    {"rid": run_id},
                )
                conn.execute(
                    text(
                        "DELETE FROM findings "
                        "WHERE investigation_run_id = :rid"
                    ),
                    {"rid": run_id},
                )
                conn.execute(
                    text(
                        "DELETE FROM evidence "
                        "WHERE investigation_run_id = :rid"
                    ),
                    {"rid": run_id},
                )
                conn.execute(
                    text(
                        "DELETE FROM agent_runs "
                        "WHERE investigation_run_id = :rid"
                    ),
                    {"rid": run_id},
                )
                conn.execute(
                    text(
                        "DELETE FROM investigation_runs "
                        "WHERE investigation_run_id = :rid"
                    ),
                    {"rid": run_id},
                )
            if case_id is not None:
                conn.execute(
                    text(
                        "DELETE FROM cases "
                        "WHERE case_id = :cid"
                    ),
                    {"cid": case_id},
                )
            if alert_id is not None:
                conn.execute(
                    text(
                        "DELETE FROM alerts "
                        "WHERE alert_id = :aid"
                    ),
                    {"aid": alert_id},
                )
            conn.execute(
                text(
                    "DELETE FROM users "
                    "WHERE user_id = :uid"
                ),
                {"uid": analyst_id},
            )
