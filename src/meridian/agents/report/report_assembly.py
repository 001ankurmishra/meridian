"""Report assembly primitive."""

import uuid
from dataclasses import dataclass
from typing import List

from sqlalchemy import Engine, text

from meridian.evidence.evidence import EvidenceRecord
from meridian.findings.findings import FindingRecord, evaluate_evidence_sufficiency
from meridian.recommendations.recommendations import RecommendationRecord


class InsufficientEvidenceError(Exception):
    """Raised when report generation is gated by insufficient evidence."""

    pass


@dataclass(frozen=True)
class InvestigationReport:
    """Deterministic report structure mirroring docs/DESIGN.md §6."""

    investigation_run_id: uuid.UUID
    case_id: uuid.UUID
    customer_name: str
    is_synthetic: bool
    risk_level: str
    evidence_completeness_status: str

    summary: str
    findings: List[FindingRecord]
    evidence: List[EvidenceRecord]
    applicable_policies: List[EvidenceRecord]
    recommendations: List[RecommendationRecord]
    confidence_text: str
    human_review_required: bool = True


def assemble_report(
    engine: Engine, investigation_run_id: uuid.UUID
) -> InvestigationReport:
    """Assemble a deterministic investigation report from persisted records.

    Args:
        engine: Application-role SQLAlchemy Engine.
        investigation_run_id: The UUID of the investigation run.

    Returns:
        An InvestigationReport containing structured data from findings, evidence,
        and recommendations.

    Raises:
        ValueError: If the investigation run or linked customer data is not found.
        InsufficientEvidenceError: If any retrieved finding fails the evidence
            sufficiency gate.
    """
    with engine.begin() as conn:
        # 1. Fetch investigation run details
        run_row = conn.execute(
            text(
                "SELECT case_id, status FROM investigation_runs "
                "WHERE investigation_run_id = :run_id"
            ),
            {"run_id": investigation_run_id},
        ).first()
        if not run_row:
            raise ValueError(f"Investigation run {investigation_run_id} not found.")

        case_id = run_row.case_id
        run_status = run_row.status

        # 2. Fetch case and customer details
        customer_row = conn.execute(
            text(
                """
                SELECT c.full_name, c.is_synthetic, c.kyc_risk_rating
                FROM cases cs
                JOIN alerts a ON cs.alert_id = a.alert_id
                JOIN customers c ON a.customer_id = c.customer_id
                WHERE cs.case_id = :case_id
                """
            ),
            {"case_id": case_id},
        ).first()
        if not customer_row:
            raise ValueError(f"Customer data not found for case {case_id}.")

        # 3. Fetch Findings
        findings_rows = conn.execute(
            text(
                """
                SELECT finding_id, investigation_run_id, observed_fact,
                       derived_signal, interpretation, evidence_ids, confidence,
                       created_at
                FROM findings
                WHERE investigation_run_id = :run_id
                ORDER BY created_at ASC
                """
            ),
            {"run_id": investigation_run_id},
        ).fetchall()

        findings = [
            FindingRecord(
                finding_id=row.finding_id,
                investigation_run_id=row.investigation_run_id,
                observed_fact=row.observed_fact,
                derived_signal=row.derived_signal,
                interpretation=row.interpretation,
                evidence_ids=row.evidence_ids,
                confidence=row.confidence,
                created_at=row.created_at,
            )
            for row in findings_rows
        ]

        # Check evidence sufficiency BEFORE proceeding
        for finding in findings:
            if not evaluate_evidence_sufficiency(finding.evidence_ids):
                raise InsufficientEvidenceError(
                    f"Finding {finding.finding_id} fails evidence sufficiency gate."
                )

        # 4. Fetch Recommendations
        rec_rows = conn.execute(
            text(
                """
                SELECT recommendation_id, investigation_run_id, text,
                       based_on_finding_ids, created_at
                FROM recommendations
                WHERE investigation_run_id = :run_id
                ORDER BY created_at ASC
                """
            ),
            {"run_id": investigation_run_id},
        ).fetchall()

        recommendations = [
            RecommendationRecord(
                recommendation_id=row.recommendation_id,
                investigation_run_id=row.investigation_run_id,
                text=row.text,
                based_on_finding_ids=row.based_on_finding_ids,
                created_at=row.created_at,
            )
            for row in rec_rows
        ]

        # 5. Fetch Referenced Evidence
        referenced_evidence_ids = set()
        for f in findings:
            referenced_evidence_ids.update(f.evidence_ids)

        all_evidence = []
        if referenced_evidence_ids:
            evidence_rows = conn.execute(
                text(
                    """
                    SELECT evidence_id, investigation_run_id, evidence_type,
                           reference_table, reference_id, produced_by_agent_run_id,
                           created_at
                    FROM evidence
                    WHERE evidence_id = ANY(:ev_ids)
                    ORDER BY created_at ASC
                    """
                ),
                {"ev_ids": list(referenced_evidence_ids)},
            ).fetchall()

            all_evidence = [
                EvidenceRecord(
                    evidence_id=row.evidence_id,
                    investigation_run_id=row.investigation_run_id,
                    evidence_type=row.evidence_type,
                    reference_table=row.reference_table,
                    reference_id=row.reference_id,
                    produced_by_agent_run_id=row.produced_by_agent_run_id,
                    created_at=row.created_at,
                )
                for row in evidence_rows
            ]

        evidence = [e for e in all_evidence if e.evidence_type != "policy_chunk"]
        policies = [e for e in all_evidence if e.evidence_type == "policy_chunk"]

        # Deterministic summary and confidence
        summary = (
            f"Deterministic report assembled from {len(findings)} findings and "
            f"{len(recommendations)} recommendations."
        )
        if not findings:
            confidence_text = "No findings to evaluate."
        else:
            confidence_levels = [f.confidence for f in findings]
            if "LOW" in confidence_levels:
                confidence_text = (
                    "Overall confidence constrained by LOW confidence findings."
                )
            elif "MEDIUM" in confidence_levels:
                confidence_text = "Overall confidence is MEDIUM."
            else:
                confidence_text = "Overall confidence is HIGH."

        return InvestigationReport(
            investigation_run_id=investigation_run_id,
            case_id=case_id,
            customer_name=customer_row.full_name,
            is_synthetic=customer_row.is_synthetic,
            risk_level=customer_row.kyc_risk_rating,
            evidence_completeness_status=run_status,
            summary=summary,
            findings=findings,
            evidence=evidence,
            applicable_policies=policies,
            recommendations=recommendations,
            confidence_text=confidence_text,
            human_review_required=True,
        )
