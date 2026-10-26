"""Human actions retain their relevant investigation identity atomically."""

import uuid

import pytest
from sqlalchemy import text

from meridian.audit.audit_trail import get_case_audit_trail
from meridian.review.decisions import record_human_decision
from meridian.review.errors import DecisionValidationError
from tests.test_human_decisions import _seed_case, _seed_user


@pytest.mark.parametrize(
    "state", [None, "FAILED", "COMPLETE", "INCOMPLETE_INSUFFICIENT_EVIDENCE"]
)
def test_triage_audit_identifies_run(superuser_engine, app_role_engine, state):
    actor = _seed_user(superuser_engine, "senior_analyst")
    case = _seed_case(superuser_engine, "OPEN")
    run = uuid.uuid4() if state else None
    if run:
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO investigation_runs "
                    "(investigation_run_id,case_id,status,started_at) "
                    "VALUES (:r,:c,:s,now())"
                ),
                {"r": run, "c": case, "s": state},
            )
    result = record_human_decision(app_role_engine, case, actor, "ESCALATE")
    trail = get_case_audit_trail(app_role_engine, case)
    assert trail.case_status == "ESCALATED"
    event = next(
        e for e in trail.audit_events if e.audit_event_id == result.audit_event_id
    )
    assert event.investigation_run_id == run
    assert event.input_summary["investigation_status"] == state


def test_ambiguous_run_decision_changes_nothing(superuser_engine, app_role_engine):
    actor = _seed_user(superuser_engine, "senior_analyst")
    case = _seed_case(superuser_engine, "OPEN")
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO investigation_runs "
                "(investigation_run_id,case_id,status,started_at) "
                "SELECT gen_random_uuid(),:c,'COMPLETE',now() FROM generate_series(1,2)"
            ),
            {"c": case},
        )
    with pytest.raises(DecisionValidationError, match="Ambiguous"):
        record_human_decision(app_role_engine, case, actor, "ESCALATE")
    trail = get_case_audit_trail(app_role_engine, case)
    assert trail.case_status == "OPEN"
    assert not trail.audit_events
