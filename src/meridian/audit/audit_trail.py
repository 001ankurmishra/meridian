"""F9 -- Audit Trail: read-side reconstruction of a case's investigation
history.

This module answers "what happened on this case?" by assembling data
already written by existing code paths (F1-F8) into one ordered
structure, per docs/OBSERVABILITY_AND_AUDIT.md #5's reconstruction
requirement. It performs no writes.

Known, documented limitation (not fixed by this module): GraphAgent
(F4) and ReportAgent (F7) are not currently wrapped by
orchestration.agent_run_tracking.record_agent_run(), so their
executions produce no `agent_runs` row and will not appear in the
`investigation_runs[].agent_runs` list returned here, even when they
ran as part of the investigation. See docs/OBSERVABILITY_AND_AUDIT.md
#5 and docs/ARCHITECTURE.md #4 for the current agent-dispatch
coverage; closing this gap is out of scope for F9 (treated as a
follow-up F4/F7 completeness item).

This function performs no authorization check and must not be exposed
as an unauthenticated API boundary (same framing as
review.decisions.record_human_decision) -- a future API layer is
responsible for verifying the caller may view the case before calling
this function.

This is a best-effort, point-in-time snapshot assembled from several
independent SELECT statements, not a single transactional read -- it
is not guaranteed atomic with respect to concurrent writes (e.g. a
human decision recorded between two of this function's queries). This
is acceptable for a reconstruction/display capability but must not be
relied upon as an input to any decision-making logic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, text

from meridian.audit.errors import CaseNotFoundError


@dataclass(frozen=True)
class AgentRunEntry:
    """One row from `agent_runs`."""

    agent_run_id: uuid.UUID
    agent_name: str
    status: str
    tool_calls: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None
    error: str | None


@dataclass(frozen=True)
class EvidenceEntry:
    """One row from `evidence`, summarized (not the full source record)."""

    evidence_id: uuid.UUID
    evidence_type: str
    reference_table: str
    reference_id: uuid.UUID
    produced_by_agent_run_id: uuid.UUID | None


@dataclass(frozen=True)
class FindingEntry:
    """One row from `findings`, summarized (not the full narrative text)."""

    finding_id: uuid.UUID
    confidence: str
    evidence_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class AuditEventEntry:
    """One row from `audit_events` (currently: human decisions, F8)."""

    audit_event_id: uuid.UUID
    actor_type: str
    actor_id: str | None
    action: str | None
    input_summary: dict[str, Any] | None
    output_summary: dict[str, Any] | None
    occurred_at: datetime | None


@dataclass(frozen=True)
class InvestigationRunEntry:
    """One row from `investigation_runs`, with its nested agent runs,
    evidence, and findings."""

    investigation_run_id: uuid.UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    agent_runs: tuple[AgentRunEntry, ...]
    evidence: tuple[EvidenceEntry, ...]
    findings: tuple[FindingEntry, ...]


@dataclass(frozen=True)
class CaseAuditTrail:
    """Full reconstruction of a case's investigation history."""

    case_id: uuid.UUID
    case_status: str
    investigation_runs: tuple[InvestigationRunEntry, ...]
    audit_events: tuple[AuditEventEntry, ...]


def get_case_audit_trail(engine: Engine, case_id: uuid.UUID) -> CaseAuditTrail:
    """Reconstruct a case's full investigation history for display/audit.

    Args:
        engine: Application-role SQLAlchemy Engine (read-only access).
        case_id: UUID of the case to reconstruct.

    Returns:
        A CaseAuditTrail with investigation_runs (each carrying its
        agent_runs, evidence, and findings, all ordered chronologically)
        and the case's audit_events (human decisions), also ordered
        chronologically. A case with no investigation runs yet returns
        an empty investigation_runs tuple, not an error.

    Raises:
        CaseNotFoundError: If case_id does not resolve to a row in
            `cases`.

    Side effects:
        None. This function performs only SELECT statements.
    """
    with engine.connect() as conn:
        case_row = conn.execute(
            text("SELECT case_id, status FROM cases WHERE case_id = :cid"),
            {"cid": case_id},
        ).fetchone()

        if case_row is None:
            raise CaseNotFoundError(f"Case {case_id} does not exist.")

        case_status = case_row[1]

        inv_run_rows = conn.execute(
            text(
                "SELECT investigation_run_id, status, started_at, completed_at "
                "FROM investigation_runs WHERE case_id = :cid "
                "ORDER BY started_at ASC"
            ),
            {"cid": case_id},
        ).fetchall()

        investigation_runs: list[InvestigationRunEntry] = []
        for inv_row in inv_run_rows:
            inv_run_id = inv_row[0]

            agent_run_rows = conn.execute(
                text(
                    "SELECT agent_run_id, agent_name, status, tool_calls, "
                    "started_at, completed_at, error "
                    "FROM agent_runs WHERE investigation_run_id = :inv_id "
                    "ORDER BY started_at ASC"
                ),
                {"inv_id": inv_run_id},
            ).fetchall()
            agent_runs = tuple(
                AgentRunEntry(
                    agent_run_id=r[0],
                    agent_name=r[1],
                    status=r[2],
                    tool_calls=r[3] if r[3] is not None else {},
                    started_at=r[4],
                    completed_at=r[5],
                    error=r[6],
                )
                for r in agent_run_rows
            )

            evidence_rows = conn.execute(
                text(
                    "SELECT evidence_id, evidence_type, reference_table, "
                    "reference_id, produced_by_agent_run_id "
                    "FROM evidence WHERE investigation_run_id = :inv_id "
                    "ORDER BY created_at ASC"
                ),
                {"inv_id": inv_run_id},
            ).fetchall()
            evidence = tuple(
                EvidenceEntry(
                    evidence_id=r[0],
                    evidence_type=r[1],
                    reference_table=r[2],
                    reference_id=r[3],
                    produced_by_agent_run_id=r[4],
                )
                for r in evidence_rows
            )

            finding_rows = conn.execute(
                text(
                    "SELECT finding_id, confidence, evidence_ids "
                    "FROM findings WHERE investigation_run_id = :inv_id "
                    "ORDER BY created_at ASC"
                ),
                {"inv_id": inv_run_id},
            ).fetchall()
            findings = tuple(
                FindingEntry(
                    finding_id=r[0],
                    confidence=r[1],
                    evidence_ids=tuple(r[2]) if r[2] is not None else (),
                )
                for r in finding_rows
            )

            investigation_runs.append(
                InvestigationRunEntry(
                    investigation_run_id=inv_run_id,
                    status=inv_row[1],
                    started_at=inv_row[2],
                    completed_at=inv_row[3],
                    agent_runs=agent_runs,
                    evidence=evidence,
                    findings=findings,
                )
            )

        audit_event_rows = conn.execute(
            text(
                "SELECT audit_event_id, actor_type, actor_id, action, "
                "input_summary, output_summary, occurred_at "
                "FROM audit_events WHERE case_id = :cid "
                "ORDER BY occurred_at ASC"
            ),
            {"cid": case_id},
        ).fetchall()
        audit_events = tuple(
            AuditEventEntry(
                audit_event_id=r[0],
                actor_type=r[1],
                actor_id=r[2],
                action=r[3],
                input_summary=r[4],
                output_summary=r[5],
                occurred_at=r[6],
            )
            for r in audit_event_rows
        )

        return CaseAuditTrail(
            case_id=case_id,
            case_status=case_status,
            investigation_runs=tuple(investigation_runs),
            audit_events=audit_events,
        )
