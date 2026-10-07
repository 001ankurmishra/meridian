import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, text

from meridian.identity.tokens import (
    hash_token,
    issue_token,
    revoke_all_tokens_for_user,
    revoke_token,
    verify_token,
)


def _seed_user(engine: Engine, role: str) -> uuid.UUID:
    uid = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (user_id, email, role, created_at) "
                "VALUES (:uid, :email, :role, :now)"
            ),
            {
                "uid": uid,
                "email": f"test_{uid}@example.com",
                "role": role,
                "now": datetime.now(timezone.utc)
            }
        )
    return uid


def _cleanup_user(engine: Engine, uid: uuid.UUID) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM api_tokens WHERE user_id = :uid"),
            {"uid": uid}
        )
        conn.execute(
            text("DELETE FROM users WHERE user_id = :uid"),
            {"uid": uid}
        )


def test_issue_and_verify_token(superuser_engine: Engine) -> None:
    uid = _seed_user(superuser_engine, "analyst")
    try:
        # Issue
        token = issue_token(superuser_engine, uid, ttl_hours=2, label="test")
        assert token.plaintext_token
        assert token.user_id == uid

        # Verify db
        with superuser_engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT token_hash, expires_at, label "
                    "FROM api_tokens WHERE token_id = :tid"
                ),
                {"tid": token.token_id}
            ).mappings().fetchone()

            assert row is not None
            assert row["token_hash"] == hash_token(token.plaintext_token)
            assert row["label"] == "test"

        # Verify function
        info = verify_token(superuser_engine, token.plaintext_token)
        assert info is not None
        assert info.user_id == uid
        assert info.role == "analyst"

    finally:
        _cleanup_user(superuser_engine, uid)


def test_verify_invalid_token(superuser_engine: Engine) -> None:
    info = verify_token(superuser_engine, "invalid_token_string")
    assert info is None


def test_verify_revoked_token(superuser_engine: Engine) -> None:
    uid = _seed_user(superuser_engine, "senior_analyst")
    try:
        token = issue_token(superuser_engine, uid)
        assert verify_token(superuser_engine, token.plaintext_token) is not None

        revoke_token(superuser_engine, token.token_id)

        assert verify_token(superuser_engine, token.plaintext_token) is None
    finally:
        _cleanup_user(superuser_engine, uid)


def test_verify_expired_token(superuser_engine: Engine) -> None:
    uid = _seed_user(superuser_engine, "admin")
    try:
        token = issue_token(superuser_engine, uid)

        # hack expiry to past
        with superuser_engine.begin() as conn:
            past = datetime.now(timezone.utc) - timedelta(hours=1)
            conn.execute(
                text(
                    "UPDATE api_tokens SET created_at = :older, "
                    "expires_at = :past WHERE token_id = :tid"
                ),
                {
                    "past": past,
                    "older": past - timedelta(hours=1),
                    "tid": token.token_id,
                }
            )

        assert verify_token(superuser_engine, token.plaintext_token) is None
    finally:
        _cleanup_user(superuser_engine, uid)


def test_revoke_all_tokens(superuser_engine: Engine) -> None:
    uid = _seed_user(superuser_engine, "analyst")
    try:
        token1 = issue_token(superuser_engine, uid)
        token2 = issue_token(superuser_engine, uid)

        count = revoke_all_tokens_for_user(superuser_engine, uid)
        assert count == 2

        assert verify_token(superuser_engine, token1.plaintext_token) is None
        assert verify_token(superuser_engine, token2.plaintext_token) is None
    finally:
        _cleanup_user(superuser_engine, uid)
