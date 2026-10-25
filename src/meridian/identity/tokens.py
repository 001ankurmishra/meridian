import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Connection, Engine, text

from meridian.audit.audit_events import record_audit_event

MAX_TTL_HOURS = 168


@dataclass(frozen=True)
class TokenInfo:
    token_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    expires_at: datetime


@dataclass(frozen=True)
class IssuedToken:
    token_id: uuid.UUID
    plaintext_token: str
    user_id: uuid.UUID
    expires_at: datetime
    label: Optional[str]


def hash_token(plaintext_token: str) -> bytes:
    """Hash the plaintext token using SHA-256 for secure storage."""
    return hashlib.sha256(plaintext_token.encode("utf-8")).digest()



def _audit_identity(
    conn: Connection, action: str, user_id: uuid.UUID,
    token_ids: list[uuid.UUID], now: datetime,
) -> None:
    # Maintenance is authenticated by the database principal, not a supplied actor.
    principal = conn.scalar(text("SELECT session_user"))
    record_audit_event(
        conn, case_id=None, actor_type="system", actor_id=f"database:{principal}",
        action=action, input_summary={"user_id": str(user_id)},
        output_summary={"token_ids": [str(tid) for tid in token_ids]},
        occurred_at=now,
    )


def issue_token(
    engine: Engine,
    user_id: uuid.UUID,
    ttl_hours: int = MAX_TTL_HOURS,
    label: Optional[str] = None
) -> IssuedToken:
    """Issue a new opaque bearer token for the specified user."""
    if ttl_hours <= 0 or ttl_hours > MAX_TTL_HOURS:
        raise ValueError(f"TTL must be between 1 and {MAX_TTL_HOURS} hours.")

    plaintext_token = secrets.token_urlsafe(32)
    token_hash = hash_token(plaintext_token)

    token_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=ttl_hours)

    with engine.begin() as conn:
        # Verify user exists
        user_exists = conn.execute(
            text("SELECT is_active FROM users WHERE user_id = :user_id FOR UPDATE"),
            {"user_id": user_id}
        ).scalar()

        if not user_exists:
            raise ValueError("User does not exist or is inactive.")

        conn.execute(
            text(
                """
                INSERT INTO api_tokens (
                    token_id, user_id, token_hash, created_at, expires_at, label
                ) VALUES (
                    :token_id, :user_id, :token_hash, :created_at, :expires_at, :label
                )
                """
            ),
            {
                "token_id": token_id,
                "user_id": user_id,
                "token_hash": token_hash,
                "created_at": now,
                "expires_at": expires_at,
                "label": label
            }
        )

        _audit_identity(conn, "TOKEN_ISSUED", user_id, [token_id], now)

    return IssuedToken(
        token_id=token_id,
        plaintext_token=plaintext_token,
        user_id=user_id,
        expires_at=expires_at,
        label=label
    )


def verify_token(engine: Engine, plaintext_token: str) -> Optional[TokenInfo]:
    """Verify a token and return user info if valid."""
    token_hash = hash_token(plaintext_token)
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                SELECT t.token_id, t.user_id, t.expires_at, u.role
                FROM api_tokens t
                JOIN users u ON t.user_id = u.user_id
                WHERE t.token_hash = :token_hash
                  AND t.revoked_at IS NULL
                  AND t.expires_at > :now
                  AND u.is_active
                """
            ),
            {"token_hash": token_hash, "now": now}
        ).mappings().fetchone()

        if not result:
            return None

        return TokenInfo(
            token_id=result["token_id"],
            user_id=result["user_id"],
            role=result["role"],
            expires_at=result["expires_at"]
        )


def revoke_token(engine: Engine, token_id: uuid.UUID) -> bool:
    """Revoke a single token by its ID."""
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE api_tokens
                SET revoked_at = :now
                WHERE token_id = :token_id AND revoked_at IS NULL
                RETURNING user_id
                """
            ),
            {"now": now, "token_id": token_id}
        )
        user_id = result.scalar()
        if user_id is None:
            return False
        _audit_identity(conn, "TOKEN_REVOKED", user_id, [token_id], now)
        return True


def revoke_all_tokens_for_user(engine: Engine, user_id: uuid.UUID) -> int:
    """Revoke all active tokens for a given user."""
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE api_tokens
                SET revoked_at = :now
                WHERE user_id = :user_id AND revoked_at IS NULL
                RETURNING token_id
                """
            ),
            {"now": now, "user_id": user_id}
        )
        token_ids = list(result.scalars())
        if token_ids:
            _audit_identity(conn, "TOKENS_REVOKED", user_id, token_ids, now)
        return len(token_ids)


def deactivate_user(engine: Engine, user_id: uuid.UUID) -> bool:
    """Disable issuance and verification and revoke credentials atomically."""
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        changed = conn.execute(text(
            "UPDATE users SET is_active = false "
            "WHERE user_id = :uid AND is_active RETURNING user_id"
        ), {"uid": user_id}).scalar()
        if changed is None:
            return False
        token_ids = list(conn.execute(text(
            "UPDATE api_tokens SET revoked_at = :now "
            "WHERE user_id = :uid AND revoked_at IS NULL RETURNING token_id"
        ), {"uid": user_id, "now": now}).scalars())
        _audit_identity(conn, "USER_DEACTIVATED", user_id, token_ids, now)
        return True
