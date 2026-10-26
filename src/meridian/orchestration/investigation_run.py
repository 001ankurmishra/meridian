"""Investigation run tracking."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine, text

from meridian.orchestration.errors import InvestigationError


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
    """Atomically start an OPEN case with no non-failed run.

    Explicit retries after FAILED runs preserve all historical records.
    Raises InvestigationError for missing/closed cases or duplicate starts.

    Args:
        engine: Application-role SQLAlchemy Engine.
        case_id: The UUID of the case to investigate.

    Returns:
        A frozen dataclass containing the new investigation run's core details.
    """
    run_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        # Serialize with other starts AND human decisions on the same case.
        # The lock must remain held until the run INSERT commits.
        case = conn.execute(
            text("SELECT status FROM cases WHERE case_id = :cid FOR UPDATE"),
            {"cid": case_id},
        ).first()
        if case is None:
            raise InvestigationError(f"Case {case_id} not found.")
        if case.status != "OPEN":
            raise InvestigationError(f"Case {case_id} is not OPEN.")
        existing = conn.execute(
            text("SELECT 1 FROM investigation_runs "
                 "WHERE case_id = :cid AND status <> 'FAILED' LIMIT 1"),
            {"cid": case_id},
        ).first()
        if existing is not None:
            raise InvestigationError("Case already has a non-failed investigation run.")
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
            },
        )

    return InvestigationRunResult(
        investigation_run_id=run_id,
        case_id=case_id,
        status="IN_PROGRESS",
        started_at=now,
    )
