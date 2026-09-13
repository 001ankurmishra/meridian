"""Recommendations recording module."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine, text


@dataclass(frozen=True)
class RecommendationRecord:
    """A frozen record of a recommendation."""

    recommendation_id: uuid.UUID
    investigation_run_id: uuid.UUID
    text: str
    based_on_finding_ids: list[uuid.UUID]
    created_at: datetime


def record_recommendation(
    engine: Engine,
    investigation_run_id: uuid.UUID,
    recommendation_text: str,
    based_on_finding_ids: list[uuid.UUID],
) -> RecommendationRecord:
    """Record a recommendation.

    Note: The persistence layer intentionally does not impose a restriction
    that the recommendation's investigation_run_id must match the
    investigation_run_id of the findings it references.

    Args:
        engine: Application-role SQLAlchemy Engine.
        investigation_run_id: The UUID of the investigation run.
        recommendation_text: The text of the recommendation.
        based_on_finding_ids: A list of finding UUIDs this recommendation is based on.
            Can be empty if the layer does not enforce report-time sufficiency.

    Returns:
        A RecommendationRecord object containing the persisted recommendation details.

    Raises:
        ValueError: If any provided finding IDs do not exist in the findings table.
    """
    recommendation_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        if based_on_finding_ids:
            result = conn.execute(
                text(
                    "SELECT count(finding_id) FROM findings "
                    "WHERE finding_id = ANY(:finding_ids)"
                ),
                {"finding_ids": based_on_finding_ids},
            ).scalar()

            unique_finding_ids = set(based_on_finding_ids)
            if result != len(unique_finding_ids):
                raise ValueError(
                    "One or more provided finding IDs do not exist in the "
                    "findings table."
                )

        conn.execute(
            text(
                """
                INSERT INTO recommendations (
                    recommendation_id,
                    investigation_run_id,
                    text,
                    based_on_finding_ids,
                    created_at
                ) VALUES (
                    :recommendation_id,
                    :investigation_run_id,
                    :recommendation_text,
                    :based_on_finding_ids,
                    :now
                )
                """
            ),
            {
                "recommendation_id": recommendation_id,
                "investigation_run_id": investigation_run_id,
                "recommendation_text": recommendation_text,
                "based_on_finding_ids": based_on_finding_ids,
                "now": now,
            },
        )

    return RecommendationRecord(
        recommendation_id=recommendation_id,
        investigation_run_id=investigation_run_id,
        text=recommendation_text,
        based_on_finding_ids=based_on_finding_ids,
        created_at=now,
    )
