"""Investigation run tracking."""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine, text


@dataclass(frozen=True)
class InvestigationRunResult:
    """Result of creating an investigation run."""

    investigation_run_id: uuid.UUID
    case_id: uuid.UUID
    status: str
    started_at: datetime


def create_investigation_run(
    engine: Engine,
    case_id: uuid.UUID,
) -> InvestigationRunResult:
    """Create a new investigation run.

    Args:
        engine: Application-role SQLAlchemy Engine.
        case_id: The UUID of the case to investigate.

    Returns:
        A frozen dataclass containing the new investigation run's core details.
    """
    run_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO investigation_runs (
                    investigation_run_id,
                    case_id,
                    status,
                    started_at,
                    created_at,
                    completed_at
                ) VALUES (
                    :run_id,
                    :case_id,
                    'IN_PROGRESS',
                    :now,
                    :now,
                    NULL
                )
                """
            ),
            {
                "run_id": run_id,
                "case_id": case_id,
                "now": now,
            }
        )

    return InvestigationRunResult(
        investigation_run_id=run_id,
        case_id=case_id,
        status="IN_PROGRESS",
        started_at=now,
    )
