"""Maintainer-approved action/state/role matrix with real evidence and PostgreSQL."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import text

from meridian.audit.audit_trail import get_case_audit_trail
from meridian.orchestration.errors import InvestigationError
from meridian.orchestration.investigation_run import create_investigation_run
from meridian.review.decisions import record_human_decision
from meridian.review.errors import DecisionValidationError, ReviewError
from tests.db_cleanup import clean_investigation_run_dependencies
from tests.decision_helpers import seed_supported_report
from tests.test_human_decisions import _seed_case, _seed_user


@pytest.fixture
def decision_case(superuser_engine, request):
    role = request.param
    actor = _seed_user(superuser_engine, "analyst" if role == "unassigned" else role)
    status = "ESCALATED" if role == "compliance_manager" else "OPEN"
    case = _seed_case(superuser_engine, status, actor if role == "analyst" else None)
    try:
        yield case, actor, role, status
    finally:
        with superuser_engine.begin() as conn:
            alert = conn.execute(
                text("SELECT alert_id FROM cases WHERE case_id=:c"), {"c": case}
            ).scalar_one()
            conn.execute(text("DELETE FROM audit_events WHERE case_id=:c"), {"c": case})
            runs = (
                conn.execute(
                    text(
                        "SELECT investigation_run_id FROM investigation_runs "
                        "WHERE case_id=:c"
                    ),
                    {"c": case},
                )
                .scalars()
                .all()
            )
            for run in runs:
                clean_investigation_run_dependencies(conn, run)
            conn.execute(text("DELETE FROM cases WHERE case_id=:c"), {"c": case})
            conn.execute(text("DELETE FROM alerts WHERE alert_id=:a"), {"a": alert})


@pytest.mark.parametrize(
    "decision_case",
    ["analyst", "senior_analyst", "compliance_manager", "admin", "unassigned"],
    indirect=True,
)
@pytest.mark.parametrize(
    "state",
    [None, "IN_PROGRESS", "FAILED", "INCOMPLETE_INSUFFICIENT_EVIDENCE", "COMPLETE"],
)
@pytest.mark.parametrize(
    "action", ["APPROVE", "REJECT", "ESCALATE", "REQUEST_MORE_INFO"]
)
def test_decision_state_role_matrix(
    decision_case, superuser_engine, app_role_engine, state, action
):
    case, actor, role, initial = decision_case
    run = None
    if state == "COMPLETE":
        run = seed_supported_report(superuser_engine, case)
    elif state:
        run = uuid.uuid4()
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO investigation_runs "
                    "(investigation_run_id,case_id,status,started_at) "
                    "VALUES (:r,:c,:s,now())"
                ),
                {"r": run, "c": case, "s": state},
            )
    authorized = (
        role == "analyst"
        or (role == "senior_analyst" and action != "REQUEST_MORE_INFO")
        or (role == "compliance_manager" and action in {"APPROVE", "REJECT"})
    )
    eligible = state != "IN_PROGRESS" and (
        action not in {"APPROVE", "REJECT"} or state == "COMPLETE"
    )
    if authorized and eligible:
        result = record_human_decision(
            app_role_engine, case, actor, action, "Synthetic review"
        )
        trail = get_case_audit_trail(app_role_engine, case)
        assert trail.case_status == result.new_status
        assert len(trail.audit_events) == 1
        assert trail.audit_events[0].investigation_run_id == run
    else:
        with pytest.raises(ReviewError):
            record_human_decision(
                app_role_engine, case, actor, action, "Synthetic review"
            )
        trail = get_case_audit_trail(app_role_engine, case)
        assert trail.case_status == initial
        assert not trail.audit_events


@pytest.mark.parametrize("decision_case", ["senior_analyst"], indirect=True)
@pytest.mark.parametrize(
    "damage", ["missing_source", "missing_recommendation", "missing_findings"]
)
def test_complete_status_does_not_bypass_report_integrity(
    decision_case, superuser_engine, app_role_engine, damage
):
    case, actor, _, _ = decision_case
    run = seed_supported_report(superuser_engine, case)
    with superuser_engine.begin() as conn:
        if damage == "missing_source":
            conn.execute(
                text(
                    "UPDATE evidence SET reference_id=gen_random_uuid() "
                    "WHERE investigation_run_id=:r"
                ),
                {"r": run},
            )
        elif damage == "missing_recommendation":
            conn.execute(
                text("DELETE FROM recommendations WHERE investigation_run_id=:r"),
                {"r": run},
            )
        else:
            conn.execute(
                text("DELETE FROM findings WHERE investigation_run_id=:r"), {"r": run}
            )
    with pytest.raises(DecisionValidationError):
        record_human_decision(app_role_engine, case, actor, "APPROVE")
    trail = get_case_audit_trail(app_role_engine, case)
    assert trail.case_status == "OPEN"
    assert not trail.audit_events


@pytest.mark.parametrize("decision_case", ["senior_analyst"], indirect=True)
def test_decision_and_start_share_case_lock(
    decision_case, superuser_engine, app_role_engine, monkeypatch
):
    from meridian.review import decisions

    case, actor, _, _ = decision_case
    entered, release, attempted = Event(), Event(), Event()
    original = decisions.record_audit_event

    def blocking_audit(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    def start():
        attempted.set()
        return create_investigation_run(app_role_engine, case)

    monkeypatch.setattr(decisions, "record_audit_event", blocking_audit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        decision = pool.submit(
            record_human_decision, app_role_engine, case, actor, "ESCALATE"
        )
        assert entered.wait(10)
        investigation = pool.submit(start)
        assert attempted.wait(10)
        # The case is still OPEN in committed state while the action owns its lock.
        with superuser_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT status FROM cases WHERE case_id=:c"), {"c": case}
                ).scalar_one()
                == "OPEN"
            )
        release.set()
        assert decision.result(10).new_status == "ESCALATED"
        with pytest.raises(InvestigationError, match="not OPEN"):
            investigation.result(10)
