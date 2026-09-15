import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Connection, text


def record_audit_event(
    conn: Connection,
    *,
    case_id: uuid.UUID,
    actor_type: str,
    actor_id: str,
    action: str,
    input_summary: dict[str, Any],
    output_summary: dict[str, Any],
    occurred_at: datetime,
    investigation_run_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Records an audit event using an existing database connection.

    This function does NOT manage transaction state (commit/rollback) and
    relies entirely on the caller's transaction context.
    """
    audit_event_id = uuid.uuid4()

    # Ensure occurred_at is timezone-aware UTC
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)

    conn.execute(
        text(
            """
            INSERT INTO audit_events (
                audit_event_id,
                case_id,
                investigation_run_id,
                actor_type,
                actor_id,
                action,
                input_summary,
                output_summary,
                occurred_at
            ) VALUES (
                :audit_event_id,
                :case_id,
                :investigation_run_id,
                :actor_type,
                :actor_id,
                :action,
                :input_summary,
                :output_summary,
                :occurred_at
            )
            """
        ),
        {
            "audit_event_id": audit_event_id,
            "case_id": case_id,
            "investigation_run_id": investigation_run_id,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "action": action,
            "input_summary": json.dumps(input_summary),
            "output_summary": json.dumps(output_summary),
            "occurred_at": occurred_at,
        },
    )
    return audit_event_id
