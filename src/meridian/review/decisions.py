import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine, text

from meridian.audit.audit_events import record_audit_event
from meridian.review.errors import (
    DecisionValidationError,
    InvalidCaseTransitionError,
    UnauthorizedDecisionError,
)


@dataclass(frozen=True)
class HumanDecisionResult:
    case_id: uuid.UUID
    previous_status: str
    new_status: str
    audit_event_id: uuid.UUID
    decided_at: datetime


def record_human_decision(
    engine: Engine,
    case_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    action: str,
    reason: str | None = None,
) -> HumanDecisionResult:
    # A. Lock and load the case
    with engine.begin() as conn:
        case_row = (
            conn.execute(
                text(
                    """
                SELECT case_id, status, assigned_analyst_id, closed_at
                FROM cases
                WHERE case_id = :case_id
                FOR UPDATE
                """
                ),
                {"case_id": case_id},
            )
            .mappings()
            .fetchone()
        )

        if not case_row:
            raise DecisionValidationError(f"Case {case_id} does not exist.")

        # B. Load actor
        actor_row = (
            conn.execute(
                text(
                    """
                SELECT role
                FROM users
                WHERE user_id = :actor_user_id
                """
                ),
                {"actor_user_id": actor_user_id},
            )
            .mappings()
            .fetchone()
        )

        if not actor_row:
            raise DecisionValidationError(f"User {actor_user_id} does not exist.")

        current_status = case_row["status"]
        assigned_analyst_id = case_row["assigned_analyst_id"]
        role = actor_row["role"]

        # C. Validate the requested transition BEFORE authorization
        valid_transitions = {
            "OPEN": ["APPROVE", "REJECT", "ESCALATE", "REQUEST_MORE_INFO"],
            "IN_REVIEW": ["APPROVE", "REJECT", "ESCALATE", "REQUEST_MORE_INFO"],
            "CLOSED_MORE_INFO": ["APPROVE", "REJECT", "ESCALATE"],
            "ESCALATED": ["APPROVE", "REJECT"],
        }

        allowed_actions_for_status = valid_transitions.get(current_status, [])
        if action not in allowed_actions_for_status:
            raise InvalidCaseTransitionError(
                f"Action {action} is invalid from status {current_status}"
            )

        # D. Validate authorization
        is_authorized = False
        if current_status in ("OPEN", "IN_REVIEW", "CLOSED_MORE_INFO"):
            if action in ("APPROVE", "REJECT", "ESCALATE"):
                if role == "senior_analyst":
                    is_authorized = True
                elif (
                    role == "analyst"
                    and assigned_analyst_id is not None
                    and str(actor_user_id) == str(assigned_analyst_id)
                ):
                    is_authorized = True
            elif action == "REQUEST_MORE_INFO":
                if (
                    role == "analyst"
                    and assigned_analyst_id is not None
                    and str(actor_user_id) == str(assigned_analyst_id)
                ):
                    is_authorized = True

        elif current_status == "ESCALATED":
            if action in ("APPROVE", "REJECT"):
                if role in ("senior_analyst", "compliance_manager"):
                    is_authorized = True

        if not is_authorized:
            raise UnauthorizedDecisionError(
                f"Actor {actor_user_id} ({role}) is not authorized for "
                f"{action} on case {case_id} with status {current_status}"
            )

        # E. Validate required reason
        if action in ("REJECT", "REQUEST_MORE_INFO"):
            if reason is None or not reason.strip():
                raise DecisionValidationError(f"Reason is required for action {action}")

        # F. Capture decided_at
        decided_at = datetime.now(timezone.utc)

        # G. Update the case
        new_status = ""
        closed_at_action = "unchanged"
        new_closed_at = case_row["closed_at"]

        if action == "APPROVE":
            new_status = "CLOSED_APPROVED"
            new_closed_at = decided_at
            if current_status == "CLOSED_MORE_INFO":
                closed_at_action = "overwritten"
            else:
                closed_at_action = "set"
        elif action == "REJECT":
            new_status = "CLOSED_REJECTED"
            new_closed_at = decided_at
            if current_status == "CLOSED_MORE_INFO":
                closed_at_action = "overwritten"
            else:
                closed_at_action = "set"
        elif action == "REQUEST_MORE_INFO":
            new_status = "CLOSED_MORE_INFO"
            new_closed_at = decided_at
            closed_at_action = "set"
        elif action == "ESCALATE":
            new_status = "ESCALATED"
            if current_status == "CLOSED_MORE_INFO":
                new_closed_at = None
                closed_at_action = "cleared"
            else:
                new_closed_at = case_row["closed_at"]
                closed_at_action = "unchanged"

        conn.execute(
            text(
                """
                UPDATE cases
                SET status = :new_status, closed_at = :new_closed_at
                WHERE case_id = :case_id
                """
            ),
            {
                "new_status": new_status,
                "new_closed_at": new_closed_at,
                "case_id": case_id,
            },
        )

        # H. Insert the audit event using the SAME conn
        audit_action_map = {
            "APPROVE": "CASE_APPROVED",
            "REJECT": "CASE_REJECTED",
            "ESCALATE": "CASE_ESCALATED",
            "REQUEST_MORE_INFO": "CASE_MORE_INFO_REQUESTED",
        }

        input_summary = {"requested_action": action, "reason": reason}

        output_summary = {
            "from_status": current_status,
            "to_status": new_status,
            "closed_at_action": closed_at_action,
        }

        audit_event_id = record_audit_event(
            conn=conn,
            case_id=case_id,
            actor_type="human",
            actor_id=str(actor_user_id),
            action=audit_action_map[action],
            input_summary=input_summary,
            output_summary=output_summary,
            occurred_at=decided_at,
            investigation_run_id=None,
        )

        return HumanDecisionResult(
            case_id=case_id,
            previous_status=current_status,
            new_status=new_status,
            audit_event_id=audit_event_id,
            decided_at=decided_at,
        )
