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
EVIDENCE_TYPE_VELOCITY_INPUT_TRANSACTION: Final[str] = "velocity_input_transaction"
EVIDENCE_TYPE_BENEFICIARY_AGE_INPUT_BENEFICIARY: Final[str] = (
    "beneficiary_age_input_beneficiary"
)
EVIDENCE_TYPE_POLICY_CHUNK: Final[str] = "DOCUMENT_REFERENCE"
EVIDENCE_TYPE_GRAPH_CYCLE_RELATIONSHIP: Final[str] = "graph_cycle_relationship"
EVIDENCE_TYPE_GRAPH_CHAIN_RELATIONSHIP: Final[str] = "graph_chain_relationship"
# Neutral customer-reference pointer to the screened customer record.
# This reference pointer does not indicate whether screening occurred,
# does not represent a screening outcome, and is not evidence of clearance.
EVIDENCE_TYPE_SCREENED_CUSTOMER: Final[str] = "screened_customer"
EVIDENCE_TYPE_WATCHLIST_ENTRY: Final[str] = "watchlist_entry"

REFERENCE_TABLE_TRANSACTIONS: Final[str] = "transactions"
REFERENCE_TABLE_DOCUMENT_CHUNKS: Final[str] = "document_chunks"
REFERENCE_TABLE_BENEFICIARIES: Final[str] = "beneficiaries"
REFERENCE_TABLE_GRAPH_RELATIONSHIPS: Final[str] = "graph_relationships"
REFERENCE_TABLE_CUSTOMERS: Final[str] = "customers"
REFERENCE_TABLE_WATCHLIST_ENTRIES: Final[str] = "watchlist_entries"


# Fixed SQL only: a caller cannot turn a source-table name into executable SQL.
_SOURCE_QUERIES: Final[dict[str, str]] = {
    "transactions": "SELECT 1 FROM transactions WHERE transaction_id = :id",
    "document_chunks": "SELECT 1 FROM document_chunks WHERE chunk_id = :id",
    "beneficiaries": "SELECT 1 FROM beneficiaries WHERE beneficiary_id = :id",
    "graph_relationships":
        "SELECT 1 FROM graph_relationships WHERE relationship_id = :id",
    "customers": "SELECT 1 FROM customers WHERE customer_id = :id",
    "watchlist_entries": "SELECT 1 FROM watchlist_entries WHERE entry_id = :id",
    "risk_signals": "SELECT 1 FROM risk_signals WHERE risk_signal_id = :id "
        "AND investigation_run_id = :run_id",
}


def validate_evidence_reference(
    conn: Connection,
    investigation_run_id: uuid.UUID,
    reference_table: str,
    reference_id: uuid.UUID,
    produced_by_agent_run_id: uuid.UUID,
) -> None:
    """Resolve a source pointer and its producing run using fixed read-only SQL.

    Called before persistence and again at report assembly. Raises ValueError
    with a bounded message on unknown sources, missing rows or wrong ownership.
    """
    query = _SOURCE_QUERIES.get(reference_table)
    if query is None:
        raise ValueError("Unsupported evidence source table.")
    if conn.execute(text(query), {
        "id": reference_id, "run_id": investigation_run_id,
    }).first() is None:
        raise ValueError("Evidence source record does not exist in its scope.")
    producer = conn.execute(text(
        "SELECT 1 FROM agent_runs WHERE agent_run_id = :agent_id "
        "AND investigation_run_id = :run_id"
    ), {"agent_id": produced_by_agent_run_id,
        "run_id": investigation_run_id}).first()
    if producer is None:
        raise ValueError("Evidence producer is not an agent in this run.")


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
    validate_evidence_reference(
        conn, investigation_run_id, reference_table, reference_id,
        produced_by_agent_run_id,
    )
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
