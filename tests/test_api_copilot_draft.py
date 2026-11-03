"""Focused tests for the authenticated offline Copilot draft API endpoint.

Tests the endpoint:
    GET /cases/{case_id}/investigations/{run_id}/copilot-draft
"""

import json
import logging
import os
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from meridian.api import copilot
from meridian.api.cases import get_engine
from meridian.copilot.drafts import (
    PROMPT_VERSION,
    DraftResult,
    EvidencePackage,
    load_package,
)
from meridian.identity.authentication import get_auth_engine, get_current_user
from meridian.identity.tokens import TokenInfo, issue_token
from meridian.main import app
from tests.test_identity_tokens import _cleanup_user, _seed_user

pytest_plugins = ("tests.test_copilot_evidence_policy",)


@pytest.fixture
def client(app_role_engine: Engine) -> Generator[TestClient, None, None]:
    """TestClient fixture with database engine dependencies properly overridden."""
    app.dependency_overrides[get_engine] = lambda: app_role_engine
    app.dependency_overrides[get_auth_engine] = lambda: app_role_engine
    yield TestClient(app)
    app.dependency_overrides.clear()


# ==============================================================================
# 1. Authentication and Authorization Precedence Checks
# ==============================================================================


def test_unauthenticated_request_returns_401(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
) -> None:
    """Unauthenticated calls must return 401 Unauthorized."""
    case_id, run_id, _, _ = policy_db_seeded
    resp = client.get(f"/cases/{case_id}/investigations/{run_id}/copilot-draft")
    assert resp.status_code == 401


def test_unauthorized_role_on_existing_case_returns_403(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
) -> None:
    """Users with unauthorized role accessing an existing case receive 403."""
    case_id, run_id, _, _ = policy_db_seeded
    app.dependency_overrides[get_current_user] = lambda: TokenInfo(
        token_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role="unauthorized_role",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    resp = client.get(
        f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
        headers={"Authorization": "Bearer auditor-token"},
    )
    assert resp.status_code == 403


def test_visibility_precedes_role_authorization_precedence(
    client: TestClient,
) -> None:
    """Case visibility check must precede role check (nonexistent case -> 404)."""
    random_case = uuid.uuid4()
    random_run = uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: TokenInfo(
        token_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role="unauthorized_role",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    resp = client.get(
        f"/cases/{random_case}/investigations/{random_run}/copilot-draft",
        headers={"Authorization": "Bearer auditor-token"},
    )
    # Must be 404 (visibility), NOT 403 (role)
    assert resp.status_code == 404
    assert resp.json() == {"detail": f"Case {random_case} not found"}


def test_authorization_matrix_roles(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
    superuser_engine: Engine,
) -> None:
    """Test full role matrix: assigned, unassigned analyst, admin, and compliance."""
    case_id, run_id, _, assigned_token = policy_db_seeded

    # 1. Assigned analyst succeeds (200)
    resp_assigned = client.get(
        f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
        headers={"Authorization": f"Bearer {assigned_token}"},
    )
    assert resp_assigned.status_code == 200

    # 2. Unassigned analyst gets 404 Case Not Found (visibility restriction)
    other_analyst = _seed_user(superuser_engine, "analyst")
    try:
        other_token = issue_token(superuser_engine, other_analyst)
        resp_unassigned = client.get(
            f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
            headers={"Authorization": f"Bearer {other_token.plaintext_token}"},
        )
        assert resp_unassigned.status_code == 404
        assert resp_unassigned.json() == {"detail": f"Case {case_id} not found"}
    finally:
        _cleanup_user(superuser_engine, other_analyst)

    # 3. Administrator succeeds (200)
    admin_user = _seed_user(superuser_engine, "admin")
    try:
        admin_token = issue_token(superuser_engine, admin_user)
        resp_admin = client.get(
            f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
            headers={"Authorization": f"Bearer {admin_token.plaintext_token}"},
        )
        assert resp_admin.status_code == 200
    finally:
        _cleanup_user(superuser_engine, admin_user)

    # 4. Compliance manager succeeds (200)
    cm_user = _seed_user(superuser_engine, "compliance_manager")
    try:
        cm_token = issue_token(superuser_engine, cm_user)
        resp_cm = client.get(
            f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
            headers={"Authorization": f"Bearer {cm_token.plaintext_token}"},
        )
        assert resp_cm.status_code == 200
    finally:
        _cleanup_user(superuser_engine, cm_user)

    # 5. Unauthorized role on existing case fails (403)
    app.dependency_overrides[get_current_user] = lambda: TokenInfo(
        token_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role="unauthorized_role",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    try:
        resp_unauth = client.get(
            f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
            headers={"Authorization": "Bearer unauthorized-token"},
        )
        assert resp_unauth.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ==============================================================================
# 2. Case and Investigation Run State Validation Checks
# ==============================================================================


def test_nonexistent_case_or_run_returns_404(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
) -> None:
    """Non-existent case or run must return 404 Not Found."""
    case_id, run_id, _, token = policy_db_seeded
    headers = {"Authorization": f"Bearer {token}"}
    random_id = uuid.uuid4()

    # Bad case ID
    resp1 = client.get(
        f"/cases/{random_id}/investigations/{run_id}/copilot-draft",
        headers=headers,
    )
    assert resp1.status_code == 404

    # Bad run ID
    resp2 = client.get(
        f"/cases/{case_id}/investigations/{random_id}/copilot-draft",
        headers=headers,
    )
    assert resp2.status_code == 404


def test_mismatched_run_and_case_returns_404(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
    superuser_engine: Engine,
) -> None:
    """If run exists but belongs to a different case, return 404 Not Found."""
    case_id, run_id, _, token = policy_db_seeded
    headers = {"Authorization": f"Bearer {token}"}
    other_alert_id = uuid.uuid4()
    other_case_id = uuid.uuid4()

    with superuser_engine.begin() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT a.customer_id, a.transaction_id, c.assigned_analyst_id "
                    "FROM alerts a "
                    "JOIN cases c ON c.alert_id = a.alert_id "
                    "WHERE c.case_id = :cid"
                ),
                {"cid": case_id},
            )
            .mappings()
            .fetchone()
        )
        assert row is not None

        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, transaction_id, "
                "alert_type, created_at) "
                "VALUES (:aid, :cid, :tid, 'RAPID_MOVEMENT', NOW())"
            ),
            {
                "aid": other_alert_id,
                "cid": row["customer_id"],
                "tid": row["transaction_id"],
            },
        )
        conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status, "
                "assigned_analyst_id, created_at) "
                "VALUES (:cid, :aid, 'OPEN', :uid, NOW())"
            ),
            {
                "cid": other_case_id,
                "aid": other_alert_id,
                "uid": row["assigned_analyst_id"],
            },
        )

    try:
        resp = client.get(
            f"/cases/{other_case_id}/investigations/{run_id}/copilot-draft",
            headers=headers,
        )
        assert resp.status_code == 404
    finally:
        with superuser_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM cases WHERE case_id = :c"),
                {"c": other_case_id},
            )
            conn.execute(
                text("DELETE FROM alerts WHERE alert_id = :a"),
                {"a": other_alert_id},
            )


def test_run_not_in_final_state_returns_422(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
    superuser_engine: Engine,
) -> None:
    """Non-final runs return 422; accepted final states return 200."""
    case_id, run_id, _, token = policy_db_seeded
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # 1. IN_PROGRESS returns 422
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE investigation_runs SET status = 'IN_PROGRESS' "
                    "WHERE investigation_run_id = :r"
                ),
                {"r": run_id},
            )
        resp_progress = client.get(
            f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
            headers=headers,
        )
        assert resp_progress.status_code == 422

        # 2. FAILED returns 422 (not an accepted final evidence state for drafting)
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE investigation_runs SET status = 'FAILED' "
                    "WHERE investigation_run_id = :r"
                ),
                {"r": run_id},
            )
        resp_failed = client.get(
            f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
            headers=headers,
        )
        assert resp_failed.status_code == 422

        # 3. INCOMPLETE_INSUFFICIENT_EVIDENCE is an accepted terminal state (200)
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE investigation_runs "
                    "SET status = 'INCOMPLETE_INSUFFICIENT_EVIDENCE' "
                    "WHERE investigation_run_id = :r"
                ),
                {"r": run_id},
            )
        resp_insufficient = client.get(
            f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
            headers=headers,
        )
        assert resp_insufficient.status_code == 200
    finally:
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE investigation_runs SET status = 'COMPLETE' "
                    "WHERE investigation_run_id = :r"
                ),
                {"r": run_id},
            )


# ==============================================================================
# 3. Successful Draft Contract and Hash/Provenance Verification
# ==============================================================================


def test_successful_draft_contract_and_keys(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
) -> None:
    """Verify exact JSON response keys, offline extraction, and policy provenance."""
    case_id, run_id, _, token = policy_db_seeded
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get(
        f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    # Exact key set
    expected_keys = {
        "case_id",
        "run_id",
        "status",
        "reason",
        "authoritative",
        "package_hash",
        "prompt_version",
        "model_identifier",
        "limitations",
        "draft",
        "policy_provenance",
    }
    assert set(data.keys()) == expected_keys
    assert "elapsed_seconds" not in data

    # Field assertions
    assert data["case_id"] == str(case_id)
    assert data["run_id"] == str(run_id)
    assert data["status"] == "DRAFT"
    assert data["authoritative"] is False
    assert data["model_identifier"] == "deterministic-mock-v1"
    assert data["prompt_version"] == PROMPT_VERSION
    assert data["draft"] is not None
    assert len(data["package_hash"]) == 64
    assert len(data["draft"]["summary"]) >= 1

    # Policy provenance
    prov = data["policy_provenance"]
    assert prov is not None
    assert "chunks" in prov
    assert "registry_hash" in prov
    assert "registry_version" in prov
    assert len(prov["chunks"]) >= 1
    assert any("rapid" in c["document_title"].lower() for c in prov["chunks"])


def test_exact_package_hash_matches_loaded_package(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
    app_role_engine: Engine,
) -> None:
    """Assert response package_hash equals package_hash from load_package."""
    case_id, run_id, _, token = policy_db_seeded
    headers = {"Authorization": f"Bearer {token}"}

    package = load_package(app_role_engine, token, case_id, run_id)
    resp = client.get(
        f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["package_hash"] == package.package_hash


def test_policy_provenance_preservation(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
    app_role_engine: Engine,
) -> None:
    """Verify response policy_provenance equals loaded package provenance."""
    case_id, run_id, _, token = policy_db_seeded
    headers = {"Authorization": f"Bearer {token}"}

    package = load_package(app_role_engine, token, case_id, run_id)
    assert package.policy_provenance is not None

    resp = client.get(
        f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    # JSON round-trip package provenance to match serialized representation
    expected_provenance = json.loads(json.dumps(package.policy_provenance))
    assert data["policy_provenance"] == expected_provenance


def test_deterministic_http_response(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
) -> None:
    """Two equivalent successful requests return byte-identical bodies."""
    case_id, run_id, _, token = policy_db_seeded
    headers = {"Authorization": f"Bearer {token}"}

    resp1 = client.get(
        f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
        headers=headers,
    )
    resp2 = client.get(
        f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
        headers=headers,
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.content == resp2.content


def test_database_non_mutation_across_request(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
    superuser_engine: Engine,
) -> None:
    """GET request must not mutate application, audit, or evidence data."""
    case_id, run_id, _, token = policy_db_seeded
    headers = {"Authorization": f"Bearer {token}"}

    monitored_tables: dict[str, str] = {
        # Application, entity, and identity tables
        "cases": "case_id",
        "alerts": "alert_id",
        "customers": "customer_id",
        "accounts": "account_id",
        "transactions": "transaction_id",
        "beneficiaries": "beneficiary_id",
        "entities": "entity_id",
        "graph_relationships": "relationship_id",
        "watchlist_entries": "entry_id",
        "users": "user_id",
        "api_tokens": "token_id",
        # Investigation tables
        "investigation_runs": "investigation_run_id",
        "agent_runs": "agent_run_id",
        "screening_results": "screening_result_id",
        "risk_signals": "risk_signal_id",
        # Audit tables
        "audit_events": "audit_event_id",
        # Evidence and policy tables
        "evidence": "evidence_id",
        "findings": "finding_id",
        "recommendations": "recommendation_id",
        "documents": "document_id",
        "document_chunks": "chunk_id",
    }

    def capture_db_state() -> dict[str, list[dict[str, Any]]]:
        state: dict[str, list[dict[str, Any]]] = {}
        with superuser_engine.connect() as conn:
            for table, pk in monitored_tables.items():
                query = text(f"SELECT * FROM {table} ORDER BY {pk}")
                state[table] = [
                    dict(row) for row in conn.execute(query).mappings().all()
                ]
        return state

    before = capture_db_state()

    # Verify relevant seeded tables are actively populated before request
    assert len(before["cases"]) >= 1
    assert len(before["investigation_runs"]) >= 1
    assert len(before["evidence"]) >= 1
    assert len(before["findings"]) >= 1
    assert len(before["documents"]) >= 1
    assert len(before["document_chunks"]) >= 1
    assert len(before["api_tokens"]) >= 1

    resp = client.get(
        f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
        headers=headers,
    )
    assert resp.status_code == 200
    after = capture_db_state()

    # Exact full-content row and column comparison across all monitored tables
    assert before == after


# ==============================================================================
# 4. Draft Outcomes and Failure Handling
# ==============================================================================


def test_abstain_draft_returns_200(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When copilot generates ABSTAIN result, return 200 OK with ABSTAIN status."""
    case_id, run_id, _, token = policy_db_seeded
    headers = {"Authorization": f"Bearer {token}"}

    async def mock_draft(
        package: EvidencePackage, *args: object, **kwargs: object
    ) -> DraftResult:
        return DraftResult(
            "ABSTAIN",
            "INSUFFICIENT_SUPPORT",
            None,
            package.limitations,
            0.01,
            "deterministic-mock-v1",
            package.package_hash,
        )

    monkeypatch.setattr("meridian.api.copilot.generate_draft", mock_draft)

    resp = client.get(
        f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ABSTAIN"
    assert data["draft"] is None
    assert data["reason"] == "INSUFFICIENT_SUPPORT"


def test_unavailable_draft_result_returns_200(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When copilot generates UNAVAILABLE result, return 200 OK."""
    case_id, run_id, _, token = policy_db_seeded
    headers = {"Authorization": f"Bearer {token}"}

    async def mock_draft(
        package: EvidencePackage, *args: object, **kwargs: object
    ) -> DraftResult:
        return DraftResult(
            "UNAVAILABLE",
            "SERVICE_DEGRADED",
            None,
            package.limitations,
            0.01,
            "deterministic-mock-v1",
            package.package_hash,
        )

    monkeypatch.setattr("meridian.api.copilot.generate_draft", mock_draft)

    resp = client.get(
        f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "UNAVAILABLE"
    assert data["draft"] is None


def test_package_load_failure_returns_503_and_logs_event(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When package loading fails unexpectedly, return 503 and log structured event."""
    case_id, run_id, _, token = policy_db_seeded
    headers = {"Authorization": f"Bearer {token}"}

    def fail_load(*args: object, **kwargs: object) -> EvidencePackage:
        raise RuntimeError("Database connection timed out or corrupted evidence.")

    monkeypatch.setattr("meridian.api.copilot.load_package", fail_load)

    logged_errors: list[str] = []
    original_error = copilot.logger.error

    def spy_error(msg: str, *args: Any, **kwargs: Any) -> None:
        logged_errors.append(msg)
        original_error(msg, *args, **kwargs)

    monkeypatch.setattr(copilot.logger, "error", spy_error)

    with caplog.at_level(logging.ERROR):
        resp = client.get(
            f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
            headers=headers,
        )

    assert resp.status_code == 503
    assert resp.json() == {"detail": "Copilot draft is unavailable."}

    # Verify structured log event was emitted
    matching = [msg for msg in logged_errors if "copilot_draft_unavailable" in msg]
    assert matching, "Expected structured log event 'copilot_draft_unavailable'"

    event_data = json.loads(matching[0])
    assert event_data == {
        "event": "copilot_draft_unavailable",
        "case_id": str(case_id),
        "run_id": str(run_id),
    }

    # Ensure no exception traceback or SQL leaked into log
    assert "Database connection timed out" not in matching[0]


# ==============================================================================
# 5. M2 Fail-Closed Policy Omission and Database Isolation
# ==============================================================================


def test_tampered_policy_fails_closed_omission_returns_200(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
    superuser_engine: Engine,
) -> None:
    """M2 fail-closed: Tampered chunk is omitted, restoring data safely."""
    case_id, run_id, ev_policy_id, token = policy_db_seeded
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Identify and query ONLY the cited chunk via its seeded evidence record
    with superuser_engine.begin() as conn:
        target_chunk_id = conn.execute(
            text("SELECT reference_id FROM evidence WHERE evidence_id = :eid"),
            {"eid": ev_policy_id},
        ).scalar_one()
        original_chunk_text = conn.execute(
            text("SELECT chunk_text FROM document_chunks WHERE chunk_id = :cid"),
            {"cid": target_chunk_id},
        ).scalar_one()

    # 2. Modify only this target chunk, ensuring reliable restoration in finally
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE document_chunks "
                "SET chunk_text = 'Tampered unauthorized policy text!' "
                "WHERE chunk_id = :cid"
            ),
            {"cid": target_chunk_id},
        )

    try:
        resp = client.get(
            f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()

        # Tampered passage must NOT appear in the draft
        assert "Tampered unauthorized policy text!" not in str(data.get("draft") or "")
        # Limitations must contain the omission note
        assert any("Some passages were omitted" in lim for lim in data["limitations"])
    finally:
        # 3. Always restore original chunk text reliably
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE document_chunks SET chunk_text = :orig "
                    "WHERE chunk_id = :cid"
                ),
                {"orig": original_chunk_text, "cid": target_chunk_id},
            )


# ==============================================================================
# 6. Offline Boundary and Fresh-Process Import Isolation
# ==============================================================================


def test_offline_boundary_no_external_network_calls(
    client: TestClient,
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify endpoint runs in offline mode without making external network calls."""
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: tuple[str, int] | str) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host in ("127.0.0.1", "localhost", "::1"):
            real_connect(self, address)
            return
        raise AssertionError(
            f"Illegal external network connection attempted to: {address}"
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

    case_id, run_id, _, token = policy_db_seeded
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get(
        f"/cases/{case_id}/investigations/{run_id}/copilot-draft",
        headers=headers,
    )
    assert resp.status_code == 200


def test_fresh_process_live_provider_import_isolation(
    policy_db_seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID, str],
) -> None:
    """Subprocess verifying offline route request never imports live pilot or budget."""
    case_id, run_id, _, token = policy_db_seeded
    repo_root = Path(__file__).resolve().parent.parent
    src_dir = str(repo_root / "src")
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        f"{src_dir}:{env['PYTHONPATH']}" if "PYTHONPATH" in env else src_dir
    )

    code = (
        "import sys\n"
        "from fastapi.testclient import TestClient\n"
        "from meridian.main import app\n"
        "client = TestClient(app)\n"
        f"resp = client.get(\n"
        f"    '/cases/{case_id}/investigations/{run_id}/copilot-draft',\n"
        f"    headers={{'Authorization': 'Bearer {token}'}},\n"
        f")\n"
        "assert resp.status_code == 200, (\n"
        "    f'Expected 200, got {resp.status_code}: {resp.text}'\n"
        ")\n"
        "assert 'meridian.copilot.openai_pilot' not in sys.modules\n"
        "assert 'meridian.copilot.budget' not in sys.modules\n"
    )

    cmd = [sys.executable, "-c", code]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert res.returncode == 0, (
        f"Import isolation check failed:\n{res.stderr}\n{res.stdout}"
    )
