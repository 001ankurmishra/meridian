from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine

from meridian.identity.tokens import TokenInfo, verify_token

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache()
def get_auth_engine() -> Engine:
    from meridian.case_management.alert_intake import (
        get_app_engine as intake_get_app_engine,
    )
    return intake_get_app_engine()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    engine: Engine = Depends(get_auth_engine),
) -> TokenInfo:
    """
    Authenticate the request and return the current server-derived user.
    Uses FastAPI's HTTPBearer to extract the token from the Authorization header.
    """
    auth_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing, invalid, or expired credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not credentials:
        raise auth_exception

    token = credentials.credentials
    if not token:
        raise auth_exception

    token_info = verify_token(engine=engine, plaintext_token=token)
    if not token_info:
        raise auth_exception

    return token_info
