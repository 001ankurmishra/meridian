import uuid
from functools import lru_cache
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Engine

from meridian.agents.report.report_assembly import (
    InsufficientEvidenceError,
    assemble_report,
)
from meridian.audit.audit_trail import get_case_audit_trail
from meridian.audit.errors import CaseNotFoundError
from meridian.case_management.alert_intake import (
    create_alert_and_case,
)
from meridian.case_management.errors import AlertValidationError
from meridian.orchestration.errors import InvestigationError
from meridian.orchestration.investigation_orchestrator import orchestrate_investigation
from meridian.review.decisions import record_human_decision
from meridian.review.errors import (
    DecisionValidationError,
    InvalidCaseTransitionError,
    UnauthorizedDecisionError,
)

router = APIRouter()


# We will use the existing get_app_engine function.


@lru_cache()
def get_engine() -> Engine:
    # We must use get_app_engine from alert_intake or config, wait,
    # `alert_intake.py` has `get_app_engine()`. Let's import it from there.
    # Actually, we can just use the engine from session.py, but wait:
        # alert_intake.py defines `get_app_engine()` using settings.app_database_url.
    # "endpoints must use the APP-ROLE engine/session, never superuser".
    # Therefore, we MUST use get_app_engine from alert_intake or redefine it here.
    from meridian.case_management.alert_intake import (
        get_app_engine as intake_get_app_engine,
    )
    return intake_get_app_engine()


class CaseCreateRequest(BaseModel):
    customer_id: uuid.UUID
    alert_type: str
    alert_reasons: Dict[str, Any] | List[Any]
    transaction_id: Optional[uuid.UUID] = None
    source_system: Optional[str] = None


class CaseCreateResponse(BaseModel):
    alert_id: uuid.UUID
    case_id: uuid.UUID


class InvestigateResponse(BaseModel):
    status: str


class DecisionRequest(BaseModel):
    actor_user_id: uuid.UUID
    action: str
    reason: Optional[str] = None


@router.post("", response_model=CaseCreateResponse, status_code=status.HTTP_201_CREATED)
def create_case(
    request: CaseCreateRequest, engine: Engine = Depends(get_engine)
) -> Any:
    try:
        result = create_alert_and_case(
            engine=engine,
            customer_id=request.customer_id,
            alert_type=request.alert_type,
            alert_reasons=request.alert_reasons,
            transaction_id=request.transaction_id,
            source_system=request.source_system,
        )
        return {"alert_id": result.alert_id, "case_id": result.case_id}
    except AlertValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )


@router.post("/{case_id}/investigate", response_model=InvestigateResponse)
def investigate_case(case_id: uuid.UUID, engine: Engine = Depends(get_engine)) -> Any:
    try:
        result_status = orchestrate_investigation(engine=engine, case_id=case_id)
        return {"status": result_status}
    except InvestigationError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=msg
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg
        )


@router.get("/{case_id}/report")
def get_report(case_id: uuid.UUID, engine: Engine = Depends(get_engine)) -> Any:
    try:
        trail = get_case_audit_trail(engine=engine, case_id=case_id)
    except CaseNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    if not trail.investigation_runs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No investigation run found for case.",
        )

    # Sort ASC so [-1] is the most recent
    sorted_runs = sorted(trail.investigation_runs, key=lambda r: r.started_at)
    most_recent_run_id = sorted_runs[-1].investigation_run_id

    try:
        report = assemble_report(engine=engine, investigation_run_id=most_recent_run_id)
        return report
    except InsufficientEvidenceError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=msg
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg
        )


@router.post("/{case_id}/decision")
def record_decision(
    case_id: uuid.UUID,
    request: DecisionRequest,
    engine: Engine = Depends(get_engine),
) -> Any:
    try:
        result = record_human_decision(
            engine=engine,
            case_id=case_id,
            actor_user_id=request.actor_user_id,
            action=request.action,
            reason=request.reason,
        )
        return result
    except DecisionValidationError as e:
        msg = str(e)
        if "does not exist" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=msg
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg
        )
    except InvalidCaseTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    except UnauthorizedDecisionError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )


@router.get("/{case_id}/audit-trail")
def get_audit_trail(case_id: uuid.UUID, engine: Engine = Depends(get_engine)) -> Any:
    try:
        trail = get_case_audit_trail(engine=engine, case_id=case_id)
        return trail
    except CaseNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
