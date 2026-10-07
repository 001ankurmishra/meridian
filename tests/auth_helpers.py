import uuid

from sqlalchemy import Engine

from meridian.identity.tokens import issue_token


def get_auth_headers(engine: Engine, user_id: uuid.UUID) -> dict[str, str]:
    """
    Issue a new token for the specified user and return the Authorization headers.
    """
    token = issue_token(engine, user_id, label="test-token")
    return {"Authorization": f"Bearer {token.plaintext_token}"}
