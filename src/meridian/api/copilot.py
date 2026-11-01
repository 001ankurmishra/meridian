"""Authenticated read-only copilot draft endpoint."""

import json
import logging
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, text

from meridian.api.cases import get_engine
from meridian.copilot.drafts import (
    Draft,
    MockProvider,
    generate_draft,
    load_package,
)
from meridian.identity.access import (
    VIEW_REPORT_ROLES,
    enforce_case_visibility,
    enforce_route_role,
)
from meridian.identity.authentication import bearer_scheme, get_current_user
from meridian.identity.tokens import TokenInfo

logger = logging.getLogger("meridian")

router = APIRouter()


class CopilotDraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: uuid.UUID
    run_id: uuid.UUID
    status: Literal["DRAFT", "ABSTAIN", "UNAVAILABLE"]
    reason: str
    authoritative: bool
    package_hash: str
    prompt_version: str
    model_identifier: str
    limitations: List[str]
    draft: Optional[Draft] = None
    policy_provenance: Optional[Dict[str, Any]] = None


@router.get(
    "/{case_id}/investigations/{run_id}/copilot-draft",
    response_model=CopilotDraftResponse,
)
async def get_copilot_draft(
    case_id: uuid.UUID,
    run_id: uuid.UUID,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    engine: Engine = Depends(get_engine),
    current_user: TokenInfo = Depends(get_current_user),
) -> Any:
    enforce_case_visibility(engine, current_user, case_id)
    enforce_route_role(current_user, VIEW_REPORT_ROLES)

    with engine.connect() as conn:
        run_row = (
            conn.execute(
                text(
                    "SELECT case_id, status FROM investigation_runs "
                    "WHERE investigation_run_id = :run_id"
                ),
                {"run_id": run_id},
            )
            .mappings()
            .fetchone()
        )

    if not run_row or run_row["case_id"] != case_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation run {run_id} not found.",
        )

    if run_row["status"] not in {"COMPLETE", "INCOMPLETE_INSUFFICIENT_EVIDENCE"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Investigation run {run_id} is not in a final state.",
        )

    token_str = credentials.credentials if credentials else ""
    try:
        package = load_package(engine, token_str, case_id, run_id)
    except Exception:
        logger.error(
            json.dumps(
                {
                    "event": "copilot_draft_unavailable",
                    "case_id": str(case_id),
                    "run_id": str(run_id),
                }
            )
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Copilot draft is unavailable.",
        )

    result = await generate_draft(package, MockProvider())

    return CopilotDraftResponse(
        case_id=case_id,
        run_id=run_id,
        status=result.status,
        reason=result.reason,
        authoritative=result.authoritative,
        package_hash=result.package_hash,
        prompt_version=result.prompt_version,
        model_identifier=result.model_identifier,
        limitations=list(result.limitations),
        draft=result.draft,
        policy_provenance=package.policy_provenance,
    )
