"""Evidence recording module."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from sqlalchemy import Connection, Engine, text


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: uuid.UUID
    investigation_run_id: uuid.UUID
    evidence_type: str
    reference_table: str
    reference_id: uuid.UUID
    produced_by_agent_run_id: uuid.UUID
    created_at: datetime


EVIDENCE_TYPE_ALERTED_TRANSACTION: Final[str] = "alerted_transaction"
EVIDENCE_TYPE_AMOUNT_DEVIATION_INPUT: Final[str] = "amount_deviation_input_transaction"
EVIDENCE_TYPE_POLICY_CHUNK: Final[str] = "DOCUMENT_REFERENCE"

REFERENCE_TABLE_TRANSACTIONS: Final[str] = "transactions"
REFERENCE_TABLE_DOCUMENT_CHUNKS: Final[str] = "document_chunks"


def record_evidence_with_connection(
    conn: Connection,
    investigation_run_id: uuid.UUID,
    evidence_type: str,
    reference_table: str,
    reference_id: uuid.UUID,
    produced_by_agent_run_id: uuid.UUID,
) -> EvidenceRecord:
    """Record a piece of evidence using an existing database connection.

    Args:
        conn: The caller-owned SQLAlchemy Connection.
        investigation_run_id: The UUID of the investigation run.
        evidence_type: Type of evidence.
        reference_table: The source table for this evidence.
        reference_id: The polymorphic UUID of the referenced record.
        produced_by_agent_run_id: The UUID of the agent run that produced this evidence.

    Returns:
        An EvidenceRecord object containing the persisted evidence details.
    """
    evidence_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    conn.execute(
        text(
            """
            INSERT INTO evidence (
                evidence_id,
                investigation_run_id,
                evidence_type,
                reference_table,
                reference_id,
                produced_by_agent_run_id,
                created_at
            ) VALUES (
                :evidence_id,
                :investigation_run_id,
                :evidence_type,
                :reference_table,
                :reference_id,
                :produced_by_agent_run_id,
                :now
            )
            """
        ),
        {
            "evidence_id": evidence_id,
            "investigation_run_id": investigation_run_id,
            "evidence_type": evidence_type,
            "reference_table": reference_table,
            "reference_id": reference_id,
            "produced_by_agent_run_id": produced_by_agent_run_id,
            "now": now,
        },
    )

    return EvidenceRecord(
        evidence_id=evidence_id,
        investigation_run_id=investigation_run_id,
        evidence_type=evidence_type,
        reference_table=reference_table,
        reference_id=reference_id,
        produced_by_agent_run_id=produced_by_agent_run_id,
        created_at=now,
    )


def record_evidence(
    engine: Engine,
    investigation_run_id: uuid.UUID,
    evidence_type: str,
    reference_table: str,
    reference_id: uuid.UUID,
    produced_by_agent_run_id: uuid.UUID,
) -> EvidenceRecord:
    """Record a piece of evidence discovered by an agent.

    Args:
        engine: Application-role SQLAlchemy Engine.
        investigation_run_id: The UUID of the investigation run.
        evidence_type: Type of evidence (e.g., 'transaction', 'beneficiary').
        reference_table: The source table for this evidence.
        reference_id: The polymorphic UUID of the referenced record.
        produced_by_agent_run_id: The UUID of the agent run that produced this evidence.

    Returns:
        An EvidenceRecord object containing the persisted evidence details.
    """
    with engine.begin() as conn:
        return record_evidence_with_connection(
            conn,
            investigation_run_id,
            evidence_type,
            reference_table,
            reference_id,
            produced_by_agent_run_id,
        )
