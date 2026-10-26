import json
import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from meridian.api import api_router
from meridian.audit.safety import error_code
from meridian.db.session import get_db

app = FastAPI(title="Meridian AML Copilot")
app.include_router(api_router)


@app.middleware("http")
async def bounded_errors(
    request: Request, call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Never expose or log raw unexpected exceptions or request content."""
    request_id = str(uuid.uuid4())
    try:
        response = await call_next(request)
    except Exception as exc:
        code = error_code(exc)
        logging.getLogger("meridian").error(json.dumps({
            "event": "request_failed", "request_id": request_id, "code": code,
        }))
        response = JSONResponse(
            status_code=503 if code == "DATABASE_ERROR" else 500,
            content={"detail": "Request could not be completed.",
                     "code": code, "request_id": request_id},
        )
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
def health_check(response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        # Trivial DB reachable check
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except OperationalError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "database": "unavailable"}
