"""Findings recording module."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Connection, Engine, text


@dataclass(frozen=True)
class FindingRecord:
    """A frozen record of a finding."""

    finding_id: uuid.UUID
    investigation_run_id: uuid.UUID
    observed_fact: str
    derived_signal: str | None
    interpretation: str | None
    evidence_ids: list[uuid.UUID]
    confidence: str
    created_at: datetime


def evaluate_evidence_sufficiency(evidence_ids: list[uuid.UUID]) -> bool:
    """Evaluate whether the provided evidence is sufficient for a finding.

    This is a PARTIAL implementation of the evidence-sufficiency concept.

    1. This implements ONLY the "non-empty evidence" criterion from
       AI_SAFETY_AND_GUARDRAILS.md §3.
    2. Confidence-methodology-based sufficiency is NOT yet implemented.
    3. This is an intentional documented limitation, not an accidental omission.

    Args:
        evidence_ids: List of evidence UUIDs.

    Returns:
        True if the evidence is sufficient (currently simply non-empty),
        False otherwise.
    """
    return bool(evidence_ids)


def record_finding_with_connection(
    conn: Connection,
    investigation_run_id: uuid.UUID,
    observed_fact: str,
    derived_signal: str | None,
    interpretation: str | None,
    evidence_ids: list[uuid.UUID],
    confidence: str,
) -> FindingRecord:
    """Record a finding using an existing database connection.

    Args:
        conn: The caller-owned SQLAlchemy Connection.
        investigation_run_id: The UUID of the investigation run.
        observed_fact: The observed fact.
        derived_signal: The derived signal.
        interpretation: The interpretation of the signal.
        evidence_ids: A list of evidence UUIDs.
        confidence: The confidence level ('LOW', 'MEDIUM', 'HIGH').

    Returns:
        A FindingRecord object containing the persisted finding details.

    Raises:
        ValueError: If any provided evidence_ids do not exist in the database.
    """
    finding_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    if evidence_ids:
        # Validate that all evidence_ids exist in the database
        result = conn.execute(
            text(
                "SELECT count(evidence_id) FROM evidence "
                "WHERE evidence_id = ANY(:evidence_ids)"
            ),
            {"evidence_ids": evidence_ids},
        ).scalar()

        unique_evidence_ids = set(evidence_ids)
        if result != len(unique_evidence_ids):
            raise ValueError(
                "One or more provided evidence_ids do not exist in the evidence table."
            )

    conn.execute(
        text(
            """
            INSERT INTO findings (
                finding_id,
                investigation_run_id,
                observed_fact,
                derived_signal,
                interpretation,
                evidence_ids,
                confidence,
                created_at
            ) VALUES (
                :finding_id,
                :investigation_run_id,
                :observed_fact,
                :derived_signal,
                :interpretation,
                :evidence_ids,
                :confidence,
                :now
            )
            """
        ),
        {
            "finding_id": finding_id,
            "investigation_run_id": investigation_run_id,
            "observed_fact": observed_fact,
            "derived_signal": derived_signal,
            "interpretation": interpretation,
            "evidence_ids": evidence_ids,
            "confidence": confidence,
            "now": now,
        },
    )

    return FindingRecord(
        finding_id=finding_id,
        investigation_run_id=investigation_run_id,
        observed_fact=observed_fact,
        derived_signal=derived_signal,
        interpretation=interpretation,
        evidence_ids=evidence_ids,
        confidence=confidence,
        created_at=now,
    )


def record_finding(
    engine: Engine,
    investigation_run_id: uuid.UUID,
    observed_fact: str,
    derived_signal: str | None,
    interpretation: str | None,
    evidence_ids: list[uuid.UUID],
    confidence: str,
) -> FindingRecord:
    """Record a finding.

    Args:
        engine: Application-role SQLAlchemy Engine.
        investigation_run_id: The UUID of the investigation run.
        observed_fact: The observed fact.
        derived_signal: The derived signal.
        interpretation: The interpretation of the signal.
        evidence_ids: A list of evidence UUIDs.
        confidence: The confidence level ('LOW', 'MEDIUM', 'HIGH').

    Returns:
        A FindingRecord object containing the persisted finding details.

    Raises:
        ValueError: If any provided evidence_ids do not exist in the database.
    """
    with engine.begin() as conn:
        return record_finding_with_connection(
            conn,
            investigation_run_id,
            observed_fact,
            derived_signal,
            interpretation,
            evidence_ids,
            confidence,
        )
