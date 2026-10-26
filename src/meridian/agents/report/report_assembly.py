"""Report assembly primitive."""

import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from typing import List

from sqlalchemy import Connection, Engine, text

from meridian.agents.report.screening_classification import (
    SanctionsAgentRunInfo,
    ScreeningResultRow,
    WatchlistScreeningSection,
    WatchlistScreeningState,
    classify_screening_state,
)
from meridian.evidence.evidence import (
    EVIDENCE_TYPE_POLICY_CHUNK,
    EvidenceRecord,
    validate_evidence_reference,
)
from meridian.findings.findings import FindingRecord, evaluate_evidence_sufficiency
from meridian.recommendations.recommendations import RecommendationRecord
from meridian.risk_engine.risk_signals import RiskSignalRecord


class InsufficientEvidenceError(Exception):
    """Raised when report generation is gated by insufficient evidence."""

    pass


__all__ = [
    "InsufficientEvidenceError",
    "InvestigationReport",
    "WatchlistScreeningSection",
    "WatchlistScreeningState",
    "assemble_report",
]


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
    risk_signals: List[RiskSignalRecord]
    confidence_text: str
    watchlist_screening: WatchlistScreeningSection
    human_review_required: bool = True


def assemble_report(
    engine: Engine | Connection, investigation_run_id: uuid.UUID
) -> InvestigationReport:
    """Assemble a deterministic investigation report from persisted records.

    Args:
        engine: Application-role Engine or an existing transaction Connection.
        investigation_run_id: The UUID of the investigation run.

    Returns:
        An InvestigationReport containing structured data from findings, evidence,
        and recommendations.

    Raises:
        ValueError: If the investigation run or linked customer data is not found.
        InsufficientEvidenceError: If any retrieved finding fails the evidence
            sufficiency gate.
    """
    # A human decision supplies its existing transaction so validation and
    # case/audit persistence share one commit boundary.
    context = engine.begin() if isinstance(engine, Engine) else nullcontext(engine)
    with context as conn:
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

        if run_status == "COMPLETE" and not findings:
            raise InsufficientEvidenceError("Complete run has no supported findings.")

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

        finding_ids = {f.finding_id for f in findings}
        for rec in recommendations:
            if not rec.based_on_finding_ids or not set(
                rec.based_on_finding_ids
            ).issubset(finding_ids):
                raise InsufficientEvidenceError(
                    "Recommendation has missing or cross-investigation findings."
                )

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

        if {e.evidence_id for e in all_evidence} != referenced_evidence_ids:
            raise InsufficientEvidenceError("Finding references missing evidence.")
        for item in all_evidence:
            if item.investigation_run_id != investigation_run_id:
                raise InsufficientEvidenceError("Evidence belongs to another run.")
            try:
                validate_evidence_reference(
                    conn, investigation_run_id, item.reference_table,
                    item.reference_id, item.produced_by_agent_run_id,
                )
            except ValueError as exc:
                raise InsufficientEvidenceError(str(exc)) from None

        evidence = [
            e for e in all_evidence if e.evidence_type != EVIDENCE_TYPE_POLICY_CHUNK
        ]
        policies = [
            e for e in all_evidence if e.evidence_type == EVIDENCE_TYPE_POLICY_CHUNK
        ]

        # 6. Fetch Risk Signals
        risk_signals_rows = conn.execute(
            text(
                """
                SELECT risk_signal_id, investigation_run_id, customer_id,
                       transaction_id, signal_type, value, model_version,
                       methodology, created_at
                FROM risk_signals
                WHERE investigation_run_id = :run_id
                ORDER BY created_at ASC
                """
            ),
            {"run_id": investigation_run_id},
        ).fetchall()

        risk_signals = [
            RiskSignalRecord(
                risk_signal_id=row.risk_signal_id,
                investigation_run_id=row.investigation_run_id,
                customer_id=row.customer_id,
                transaction_id=row.transaction_id,
                signal_type=row.signal_type,
                value=row.value,
                model_version=row.model_version,
                methodology=row.methodology,
                created_at=row.created_at,
            )
            for row in risk_signals_rows
        ]

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

        # 7. Fetch Watchlist Screening Data and Classify (ADR-0008 D10)
        screening_res_row = conn.execute(
            text(
                """
                SELECT screening_result_id, investigation_run_id, agent_run_id,
                       outcome, reason_code, candidate_count, watchlist_name,
                       watchlist_version, matching_rule_id, normalization_version
                FROM screening_results
                WHERE investigation_run_id = :run_id
                """
            ),
            {"run_id": investigation_run_id},
        ).first()

        screening_result: ScreeningResultRow | None = None
        referenced_agent_run: SanctionsAgentRunInfo | None = None

        if screening_res_row is not None:
            screening_result = ScreeningResultRow(
                screening_result_id=screening_res_row.screening_result_id,
                investigation_run_id=screening_res_row.investigation_run_id,
                agent_run_id=screening_res_row.agent_run_id,
                outcome=screening_res_row.outcome,
                reason_code=screening_res_row.reason_code,
                candidate_count=screening_res_row.candidate_count,
                watchlist_name=screening_res_row.watchlist_name,
                watchlist_version=screening_res_row.watchlist_version,
                matching_rule_id=screening_res_row.matching_rule_id,
                normalization_version=screening_res_row.normalization_version,
            )

            ref_ar_row = conn.execute(
                text(
                    """
                    SELECT agent_run_id, agent_name, status,
                           investigation_run_id
                    FROM agent_runs
                    WHERE agent_run_id = :ar_id
                    """
                ),
                {"ar_id": screening_res_row.agent_run_id},
            ).first()

            if ref_ar_row is not None:
                referenced_agent_run = SanctionsAgentRunInfo(
                    agent_run_id=ref_ar_row.agent_run_id,
                    agent_name=ref_ar_row.agent_name,
                    status=ref_ar_row.status,
                    investigation_run_id=ref_ar_row.investigation_run_id,
                )

        all_sanctions_ar_rows = conn.execute(
            text(
                """
                SELECT agent_run_id, agent_name, status,
                       investigation_run_id
                FROM agent_runs
                WHERE investigation_run_id = :run_id
                  AND agent_name = 'SanctionsAgent'
                ORDER BY started_at ASC
                """
            ),
            {"run_id": investigation_run_id},
        ).fetchall()

        all_sanctions_agent_runs = tuple(
            SanctionsAgentRunInfo(
                agent_run_id=r.agent_run_id,
                agent_name=r.agent_name,
                status=r.status,
                investigation_run_id=r.investigation_run_id,
            )
            for r in all_sanctions_ar_rows
        )

        candidate_finding_count = conn.execute(
            text(
                """
                SELECT count(DISTINCT f.finding_id)
                FROM findings f
                JOIN evidence e ON e.evidence_id = ANY(f.evidence_ids)
                WHERE f.investigation_run_id = :run_id
                  AND e.evidence_type = 'watchlist_entry'
                """
            ),
            {"run_id": investigation_run_id},
        ).scalar_one()

        watchlist_screening = classify_screening_state(
            screening_result=screening_result,
            referenced_agent_run=referenced_agent_run,
            all_sanctions_agent_runs=all_sanctions_agent_runs,
            candidate_finding_count=int(candidate_finding_count or 0),
        )

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
            risk_signals=risk_signals,
            confidence_text=confidence_text,
            watchlist_screening=watchlist_screening,
            human_review_required=True,
        )
