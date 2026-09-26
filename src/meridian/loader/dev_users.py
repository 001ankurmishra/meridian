import uuid
from typing import Any

from sqlalchemy import Engine, text


def generate_dev_users() -> list[dict[str, Any]]:
    return [
        {
            "user_id": uuid.uuid5(uuid.NAMESPACE_OID, "dev_analyst_1"),
            "email": "dev.analyst.1@meridian.local",
            "role": "analyst",
        },
        {
            "user_id": uuid.uuid5(uuid.NAMESPACE_OID, "dev_senior_analyst_1"),
            "email": "dev.senior.analyst.1@meridian.local",
            "role": "senior_analyst",
        },
    ]


def seed_dev_users(engine: Engine) -> None:
    expected_users = generate_dev_users()

    with engine.begin() as conn:
        for expected in expected_users:
            row = conn.execute(
                text("SELECT email, role FROM users WHERE user_id = :uid"),
                {"uid": expected["user_id"]},
            ).fetchone()

            if row is None:
                conn.execute(
                    text(
                        "INSERT INTO users (user_id, email, role, created_at) "
                        "VALUES (:uid, :email, :role, CURRENT_TIMESTAMP)"
                    ),
                    {
                        "uid": expected["user_id"],
                        "email": expected["email"],
                        "role": expected["role"],
                    },
                )
            else:
                actual_email = row[0]
                actual_role = row[1]
                if actual_email != expected["email"] or actual_role != expected["role"]:
                    raise RuntimeError(
                        f"Dev user seed mismatch! "
                        f"User ID: {expected['user_id']} | "
                        f"Expected Email: {expected['email']} | "
                        f"Expected Role: {expected['role']} | "
                        f"Actual Email: {actual_email} | "
                        f"Actual Role: {actual_role}"
                    )
