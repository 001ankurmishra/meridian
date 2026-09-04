from fastapi import Depends, FastAPI, Response, status
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from meridian.db.session import get_db

app = FastAPI(title="Meridian AML Copilot")

@app.get("/health")
def health_check(response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        # Trivial DB reachable check
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except OperationalError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "database": "unavailable"}
