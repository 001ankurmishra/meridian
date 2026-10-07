import uuid
from typing import Set

from fastapi import HTTPException, status
from sqlalchemy import Engine, text

from meridian.identity.tokens import TokenInfo

CREATE_CASE_ROLES: Set[str] = {"senior_analyst"}
INVESTIGATE_CASE_ROLES: Set[str] = {"senior_analyst", "analyst"}
VIEW_REPORT_ROLES: Set[str] = {
    "analyst",
    "senior_analyst",
    "compliance_manager",
    "admin",
}
VIEW_AUDIT_ROLES: Set[str] = {
    "analyst",
    "senior_analyst",
    "compliance_manager",
    "admin",
}


def enforce_case_visibility(
    engine: Engine, user: TokenInfo, case_id: uuid.UUID
) -> None:
    """
    Enforce case visibility rules.
    If the case does not exist or the user cannot see it, raises 404 Not Found.
    """
    with engine.begin() as conn:
        case_row = conn.execute(
            text(
                "SELECT status, assigned_analyst_id FROM cases "
                "WHERE case_id = :case_id"
            ),
            {"case_id": case_id}
        ).mappings().fetchone()

    if not case_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case {case_id} not found"
        )

    role = user.role
    assigned_analyst_id = case_row["assigned_analyst_id"]

    if role == "analyst":
        if not assigned_analyst_id or str(assigned_analyst_id) != str(user.user_id):
            # Same error as not found to avoid leaking existence
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Case {case_id} not found"
            )

    # senior_analyst, compliance_manager, admin can see all cases

    return


def enforce_route_role(user: TokenInfo, allowed_roles: Set[str]) -> None:
    """
    Enforce that the current user has one of the allowed roles.
    Raises 403 Forbidden if not.
    """
    if user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User role {user.role} is not authorized for this action"
        )
