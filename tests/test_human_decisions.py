import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import Engine, text

from meridian.audit.audit_events import record_audit_event
from meridian.review.decisions import record_human_decision
from meridian.review.errors import (
    DecisionValidationError,
    InvalidCaseTransitionError,
    UnauthorizedDecisionError,
)


def _seed_user(superuser_engine: Engine, role: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (user_id, email, role, created_at) "
                "VALUES (:user_id, :email, :role, :now)"
            ),
            {
                "user_id": user_id,
                "email": f"test_{user_id}@example.com",
                "role": role,
                "now": datetime.now(timezone.utc),
            },
        )
    return user_id


def _seed_case(
    superuser_engine: Engine,
    status: str,
    assigned_analyst_id: uuid.UUID | None = None,
    closed_at: datetime | None = None,
) -> uuid.UUID:
    cid = uuid.uuid4()
    aid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers (customer_id, full_name, "
                "is_synthetic, kyc_risk_rating, created_at) "
                "VALUES (:cid, 'Test Customer', true, 'HIGH', :now)"
            ),
            {"cid": cid, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, created_at) "
                "VALUES (:aid, :cid, :now)"
            ),
            {"aid": aid, "cid": cid, "now": now},
        )
        case_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status, assigned_analyst_id, "
                "closed_at, opened_at, created_at) "
                "VALUES (:case_id, :aid, :status, :assigned, :closed_at, :now, :now)"
            ),
            {
                "case_id": case_id,
                "aid": aid,
                "status": status,
                "assigned": assigned_analyst_id,
                "closed_at": closed_at,
                "now": now,
            },
        )
    return case_id


def _cleanup(superuser_engine: Engine) -> None:
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events"))


# 1. Every valid transition
@pytest.mark.parametrize(
    "start_status,action,role,assigned,expected_status,closed_at_action,needs_reason",
    [
        ("OPEN", "APPROVE", "senior_analyst", False, "CLOSED_APPROVED", "set", False),
        ("OPEN", "REJECT", "analyst", True, "CLOSED_REJECTED", "set", True),
        ("OPEN", "ESCALATE", "senior_analyst", False, "ESCALATED", "unchanged", False),
        ("OPEN", "REQUEST_MORE_INFO", "analyst", True, "CLOSED_MORE_INFO", "set", True),
        ("IN_REVIEW", "APPROVE", "analyst", True, "CLOSED_APPROVED", "set", False),
        (
            "IN_REVIEW",
            "REJECT",
            "senior_analyst",
            False,
            "CLOSED_REJECTED",
            "set",
            True,
        ),
        ("IN_REVIEW", "ESCALATE", "analyst", True, "ESCALATED", "unchanged", False),
        (
            "IN_REVIEW",
            "REQUEST_MORE_INFO",
            "analyst",
            True,
            "CLOSED_MORE_INFO",
            "set",
            True,
        ),
        (
            "ESCALATED",
            "APPROVE",
            "compliance_manager",
            False,
            "CLOSED_APPROVED",
            "set",
            False,
        ),
        (
            "ESCALATED",
            "REJECT",
            "senior_analyst",
            False,
            "CLOSED_REJECTED",
            "set",
            True,
        ),
        (
            "CLOSED_MORE_INFO",
            "APPROVE",
            "senior_analyst",
            False,
            "CLOSED_APPROVED",
            "overwritten",
            False,
        ),
        (
            "CLOSED_MORE_INFO",
            "REJECT",
            "analyst",
            True,
            "CLOSED_REJECTED",
            "overwritten",
            True,
        ),
        (
            "CLOSED_MORE_INFO",
            "ESCALATE",
            "senior_analyst",
            False,
            "ESCALATED",
            "cleared",
            False,
        ),
    ],
)
def test_valid_transitions(
    app_role_engine: Engine,
    superuser_engine: Engine,
    start_status: str,
    action: str,
    role: str,
    assigned: bool,
    expected_status: str,
    closed_at_action: str,
    needs_reason: bool,
) -> None:
    try:
        actor_id = _seed_user(superuser_engine, role)
        case_id = _seed_case(
            superuser_engine,
            start_status,
            assigned_analyst_id=actor_id if assigned else None,
        )

        reason = "A valid reason" if needs_reason else None

        result = record_human_decision(
            engine=app_role_engine,
            case_id=case_id,
            actor_user_id=actor_id,
            action=action,
            reason=reason,
        )

        assert result.previous_status == start_status
        assert result.new_status == expected_status

        # Verify case state
        with superuser_engine.connect() as conn:
            case_row = (
                conn.execute(
                    text("SELECT status, closed_at FROM cases WHERE case_id = :cid"),
                    {"cid": case_id},
                )
                .mappings()
                .fetchone()
            )
            assert case_row is not None
            assert case_row["status"] == expected_status
            if expected_status == "ESCALATED" and start_status != "CLOSED_MORE_INFO":
                assert case_row["closed_at"] is None
            elif expected_status == "ESCALATED" and start_status == "CLOSED_MORE_INFO":
                assert case_row["closed_at"] is None
            else:
                assert case_row["closed_at"] is not None

            # Check audit event
            audit_rows = (
                conn.execute(
                    text("SELECT * FROM audit_events WHERE case_id = :cid"),
                    {"cid": case_id},
                )
                .mappings()
                .fetchall()
            )
            assert len(audit_rows) == 1
            audit_row = audit_rows[0]
            assert audit_row["actor_type"] == "human"
            assert audit_row["actor_id"] == str(actor_id)

            audit_action_map = {
                "APPROVE": "CASE_APPROVED",
                "REJECT": "CASE_REJECTED",
                "ESCALATE": "CASE_ESCALATED",
                "REQUEST_MORE_INFO": "CASE_MORE_INFO_REQUESTED",
            }
            assert audit_row["action"] == audit_action_map[action]
            assert audit_row["input_summary"]["requested_action"] == action
            assert audit_row["input_summary"]["reason"] == reason
            assert audit_row["output_summary"]["from_status"] == start_status
            assert audit_row["output_summary"]["to_status"] == expected_status
            assert audit_row["output_summary"]["closed_at_action"] == closed_at_action

            assert audit_row["occurred_at"] == result.decided_at
            assert result.audit_event_id == audit_row["audit_event_id"]

    finally:
        _cleanup(superuser_engine)


# 2. Invalid transitions take precedence over authorization (4)
@pytest.mark.parametrize(
    "start_status,action,role",
    [
        (
            "CLOSED_APPROVED",
            "APPROVE",
            "admin",
        ),  # Unauthorized actor on invalid transition
        ("CLOSED_REJECTED", "ESCALATE", "senior_analyst"),
        ("CLOSED_MORE_INFO", "REQUEST_MORE_INFO", "senior_analyst"),
        ("ESCALATED", "REQUEST_MORE_INFO", "analyst"),
        ("ESCALATED", "ESCALATE", "compliance_manager"),
    ],
)
def test_invalid_transitions(
    app_role_engine: Engine,
    superuser_engine: Engine,
    start_status: str,
    action: str,
    role: str,
) -> None:
    try:
        actor_id = _seed_user(superuser_engine, role)
        case_id = _seed_case(superuser_engine, start_status)

        with pytest.raises(InvalidCaseTransitionError):
            record_human_decision(
                engine=app_role_engine,
                case_id=case_id,
                actor_user_id=actor_id,
                action=action,
                reason="test",
            )

        with superuser_engine.connect() as conn:
            case_row = (
                conn.execute(
                    text("SELECT status FROM cases WHERE case_id = :cid"),
                    {"cid": case_id},
                )
                .mappings()
                .fetchone()
            )
            assert case_row is not None
            assert case_row["status"] == start_status

            count = conn.execute(
                text("SELECT COUNT(*) FROM audit_events WHERE case_id = :cid"),
                {"cid": case_id},
            ).scalar()
            assert count == 0

    finally:
        _cleanup(superuser_engine)


# 3. Authorization Boundaries
@pytest.mark.parametrize(
    "status,action,role,assigned,should_pass",
    [
        # Analyst assignment boundaries
        ("OPEN", "APPROVE", "analyst", False, False),  # Unassigned analyst
        ("OPEN", "APPROVE", "analyst", True, True),  # Assigned analyst
        # Senior analyst bounds
        (
            "OPEN",
            "REQUEST_MORE_INFO",
            "senior_analyst",
            False,
            False,
        ),  # Senior can't request info
        (
            "OPEN",
            "APPROVE",
            "senior_analyst",
            False,
            True,
        ),  # Unassigned senior can approve
        # Escalated bounds
        (
            "ESCALATED",
            "APPROVE",
            "analyst",
            True,
            False,
        ),  # Assigned analyst can't approve escalated
        (
            "ESCALATED",
            "APPROVE",
            "compliance_manager",
            False,
            True,
        ),  # CM can approve escalated
        # Admin bounds
        ("OPEN", "APPROVE", "admin", False, False),  # Admin denied
        ("ESCALATED", "APPROVE", "admin", False, False),  # Admin denied
    ],
)
def test_authorization_boundaries(
    app_role_engine: Engine,
    superuser_engine: Engine,
    status: str,
    action: str,
    role: str,
    assigned: bool,
    should_pass: bool,
) -> None:
    try:
        actor_id = _seed_user(superuser_engine, role)

        assigned_id = actor_id if assigned else None
        if role == "analyst" and not assigned:
            assigned_id = _seed_user(superuser_engine, "analyst")  # Different analyst

        case_id = _seed_case(superuser_engine, status, assigned_analyst_id=assigned_id)

        if should_pass:
            record_human_decision(app_role_engine, case_id, actor_id, action, "test")
        else:
            with pytest.raises(UnauthorizedDecisionError):
                record_human_decision(
                    app_role_engine, case_id, actor_id, action, "test"
                )

            with superuser_engine.connect() as conn:
                count = conn.execute(
                    text("SELECT COUNT(*) FROM audit_events WHERE case_id = :cid"),
                    {"cid": case_id},
                ).scalar()
                assert count == 0
    finally:
        _cleanup(superuser_engine)


# 5 & 6. Missing reasons
@pytest.mark.parametrize(
    "action,reason",
    [
        ("REJECT", None),
        ("REJECT", ""),
        ("REJECT", "   "),
        ("REQUEST_MORE_INFO", None),
        ("REQUEST_MORE_INFO", ""),
        ("REQUEST_MORE_INFO", "   \n "),
    ],
)
def test_missing_reason(
    app_role_engine: Engine, superuser_engine: Engine, action: str, reason: str | None
) -> None:
    try:
        actor_id = _seed_user(superuser_engine, "senior_analyst")
        # seed with analyst so RMI works if the reason was valid
        if action == "REQUEST_MORE_INFO":
            actor_id = _seed_user(superuser_engine, "analyst")

        case_id = _seed_case(superuser_engine, "OPEN", assigned_analyst_id=actor_id)

        with pytest.raises(DecisionValidationError, match="Reason is required"):
            record_human_decision(app_role_engine, case_id, actor_id, action, reason)

        with superuser_engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM audit_events WHERE case_id = :cid"),
                {"cid": case_id},
            ).scalar()
            assert count == 0
    finally:
        _cleanup(superuser_engine)


# 7. Nonexistent actor and case
def test_nonexistent_entities(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    try:
        actor_id = _seed_user(superuser_engine, "senior_analyst")
        case_id = _seed_case(superuser_engine, "OPEN")

        # Nonexistent case
        with pytest.raises(DecisionValidationError, match="Case .* does not exist"):
            record_human_decision(app_role_engine, uuid.uuid4(), actor_id, "APPROVE")

        # Nonexistent user
        with pytest.raises(DecisionValidationError, match="User .* does not exist"):
            record_human_decision(app_role_engine, case_id, uuid.uuid4(), "APPROVE")

    finally:
        _cleanup(superuser_engine)


# 8 & 9. CLOSED_MORE_INFO overwrites/clears closed_at
def test_closed_more_info_closed_at_behavior(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    try:
        actor_id = _seed_user(superuser_engine, "senior_analyst")

        # Test CLEAR to NULL on ESCALATE
        c1 = _seed_case(
            superuser_engine, "CLOSED_MORE_INFO", closed_at=datetime.now(timezone.utc)
        )
        record_human_decision(app_role_engine, c1, actor_id, "ESCALATE")

        # Test OVERWRITE on APPROVE
        c2 = _seed_case(
            superuser_engine,
            "CLOSED_MORE_INFO",
            closed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        res2 = record_human_decision(app_role_engine, c2, actor_id, "APPROVE")

        with superuser_engine.connect() as conn:
            row1 = (
                conn.execute(
                    text("SELECT closed_at FROM cases WHERE case_id = :c"), {"c": c1}
                )
                .mappings()
                .fetchone()
            )
            assert row1 is not None
            assert row1["closed_at"] is None

            row2 = (
                conn.execute(
                    text("SELECT closed_at FROM cases WHERE case_id = :c"), {"c": c2}
                )
                .mappings()
                .fetchone()
            )
            assert row2 is not None
            assert row2["closed_at"] == res2.decided_at

    finally:
        _cleanup(superuser_engine)


# 10 & 11. Transaction rollback & Audit Transaction Participation
def test_audit_event_transaction_participation(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    try:
        actor_id = _seed_user(superuser_engine, "senior_analyst")
        case_id = _seed_case(superuser_engine, "OPEN")

        # Behavioral test: record an audit event inside a transaction,
        # then explicitly raise an exception to roll back the transaction.
        # This proves the audit event relies on the caller's transaction
        # and doesn't auto-commit or use its own internal transaction.
        class IntentionalRollbackError(Exception):
            pass

        with pytest.raises(IntentionalRollbackError):
            with app_role_engine.begin() as conn:
                record_audit_event(
                    conn=conn,
                    case_id=case_id,
                    actor_type="human",
                    actor_id=str(actor_id),
                    action="CASE_APPROVED",
                    input_summary={},
                    output_summary={},
                    occurred_at=datetime.now(timezone.utc),
                )
                raise IntentionalRollbackError("Rollback transaction")

        with superuser_engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM audit_events WHERE case_id = :cid"),
                {"cid": case_id},
            ).scalar()
            # If it participated in the transaction, it should be rolled back (0)
            assert count == 0

    finally:
        _cleanup(superuser_engine)


# 12. Genuine concurrency
def test_genuine_concurrency(app_role_engine: Engine, superuser_engine: Engine) -> None:
    import threading
    import time

    try:
        actor_id = _seed_user(superuser_engine, "senior_analyst")
        case_id = _seed_case(superuser_engine, "OPEN")

        exception_in_b = None
        thread_started = threading.Event()

        # We will intercept the update by monkeypatching record_audit_event
        # to sleep for a second, holding the FOR UPDATE lock on the case.
        # Meanwhile, Thread B will try to execute and block, and when A completes,
        # B will get the lock, find the status is CLOSED_APPROVED,
        # and throw InvalidCaseTransitionError.

        def run_thread_b() -> None:
            nonlocal exception_in_b
            thread_started.set()
            try:
                # This should block until A is done,
                # then fail because A changed it to CLOSED_APPROVED
                record_human_decision(app_role_engine, case_id, actor_id, "ESCALATE")
            except Exception as e:
                exception_in_b = e

        b = threading.Thread(target=run_thread_b)

        # Run A manually with the same engine but we'll add a sleep in the transaction
        with app_role_engine.begin() as conn:
            # A gets the lock
            conn.execute(
                text("SELECT * FROM cases WHERE case_id = :c FOR UPDATE"),
                {"c": case_id},
            ).mappings().fetchone()

            # Start B
            b.start()
            thread_started.wait()
            # B is now blocked waiting for the FOR UPDATE lock
            time.sleep(0.5)

            # A commits (simulate the rest of A manually)
            conn.execute(
                text(
                    "UPDATE cases SET status = 'CLOSED_APPROVED', "
                    "closed_at = NOW() WHERE case_id = :c"
                ),
                {"c": case_id},
            )
            audit_id = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO audit_events (audit_event_id, case_id, actor_type, "
                    "actor_id, action, input_summary, output_summary, occurred_at) "
                    "VALUES (:a, :c, 'human', :actor, "
                    "'CASE_APPROVED', '{}', '{}', NOW())"
                ),
                {"a": audit_id, "c": case_id, "actor": str(actor_id)},
            )

        b.join(timeout=2)

        assert isinstance(exception_in_b, InvalidCaseTransitionError)

        with superuser_engine.connect() as conn:
            row = (
                conn.execute(
                    text("SELECT status FROM cases WHERE case_id = :c"), {"c": case_id}
                )
                .mappings()
                .fetchone()
            )
            assert row is not None
            assert row["status"] == "CLOSED_APPROVED"
            count = conn.execute(
                text("SELECT COUNT(*) FROM audit_events WHERE case_id = :cid"),
                {"cid": case_id},
            ).scalar()
            assert count == 1  # Only A's audit event

    finally:
        _cleanup(superuser_engine)
