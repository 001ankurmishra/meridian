import os
import socket
import subprocess
import time
import uuid
from typing import Any, Generator

import pytest
import requests
from sqlalchemy import Engine, text
from streamlit.testing.v1 import AppTest

from meridian.loader.dev_users import seed_dev_users
from meridian.loader.main import get_migrator_engine
from tests.test_api_endpoints import _cleanup_case_data


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        # Ensure we return int and not Any by casting
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def live_server_url() -> Generator[str, None, None]:
    port = get_free_port()

    import unittest.mock

    from meridian.loader.main import main as loader_main
    env_vars = {
        "DATABASE_URL": "postgresql+psycopg://meridian_user:meridian_pass@localhost:5432/meridian_db",
        "LOADER_DATABASE_URL": "postgresql+psycopg://meridian_loader:meridian_loader_pass@localhost:5432/meridian_db",
    }
    with unittest.mock.patch.dict(os.environ, env_vars):
        loader_main()

    env = os.environ.copy()
    env.update(env_vars)
    env["PYTHONPATH"] = os.path.join(os.getcwd(), "src")

    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "meridian.main:app",
            "--app-dir",
            "src",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )

    url = f"http://127.0.0.1:{port}"

    # Wait for the server to be ready
    for _ in range(1000):
        try:
            resp = requests.get(f"{url}/openapi.json")
            if resp.status_code == 200:
                break
        except requests.ConnectionError:
            time.sleep(0.1)
    else:
        proc.terminate()
        out, _ = proc.communicate(timeout=5)
        raise RuntimeError(
            "FastAPI server did not start in time. Output: "
            f"{out.decode('utf-8', errors='replace')}"
        )

    os.environ["MERIDIAN_API_BASE_URL"] = url

    yield url

    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture(scope="session")
def ui_smoke_engine() -> Generator[Engine, None, None]:
    import unittest.mock
    with unittest.mock.patch.dict(os.environ, {"DATABASE_URL": "postgresql+psycopg://meridian_user:meridian_pass@localhost:5432/meridian_db"}):
        eng = get_migrator_engine()
    yield eng
    eng.dispose()


def test_ui_smoke_startup(live_server_url: str) -> None:
    at = AppTest.from_file("../ui/streamlit_app.py")
    at.run(timeout=10)
    assert not at.exception


def test_ui_smoke_happy_path(live_server_url: str, ui_smoke_engine: Engine) -> None:
    from meridian.identity.tokens import issue_token
    # seed a user and get token
    uid = uuid.uuid4()
    with ui_smoke_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (user_id, email, role) "
                "VALUES (:u, :e, 'senior_analyst')"
            ),
            {"u": uid, "e": f"{uid}@test.com"}
        )
    token = issue_token(ui_smoke_engine, uid, label="smoke_test")
    headers = {"Authorization": f"Bearer {token.plaintext_token}"}

    case_id = None
    try:
        payload: dict[str, Any] = {
            "customer_id": str(uuid.uuid5(uuid.NAMESPACE_OID, "rahul_sharma")),
            "alert_type": "suspicious_transfer",
            "alert_reasons": {"reason": "Test happy path"},
        }

        create_resp = requests.post(
            f"{live_server_url}/cases", json=payload, headers=headers
        )
        assert create_resp.status_code == 201, create_resp.text
        case_id = create_resp.json()["case_id"]

        with ui_smoke_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE cases SET assigned_analyst_id = :uid "
                    "WHERE case_id = :cid"
                ),
                {"uid": uid, "cid": case_id},
            )

        inv_resp = requests.post(
            f"{live_server_url}/cases/{case_id}/investigate", headers=headers
        )
        assert inv_resp.status_code == 200

        at = AppTest.from_file("../ui/streamlit_app.py")
        at.run(timeout=10)

        at.text_input(key="api_token_input").input(token.plaintext_token).run()
        at.text_input(key="active_case_id").input(str(case_id)).run()

        # Fetch report to render the risk signals section
        for b in at.button:
            if b.label == "Fetch Report":
                b.click().run()
                break

        assert any(
            "No computed risk signals for this investigation run" in m.value
            for m in at.markdown
        )

        at.selectbox(key="action").select("APPROVE").run()

        at.button(key="submit_decision_btn").click().run()

        assert not at.exception
        success_msgs = [s.value for s in at.success]
        assert any("Decision submitted successfully" in m for m in success_msgs)

        with ui_smoke_engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM cases WHERE case_id = :cid"), {"cid": case_id}
            ).scalar()
            assert status == "CLOSED_APPROVED"
    finally:
        _cleanup_case_data(ui_smoke_engine, case_id, None, uid)


def test_ui_smoke_auth_boundary(live_server_url: str, ui_smoke_engine: Engine) -> None:
    from meridian.identity.tokens import issue_token
    # analyst cannot approve
    uid = uuid.uuid4()
    with ui_smoke_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (user_id, email, role) VALUES (:u, :e, 'analyst')"),
            {"u": uid, "e": f"{uid}@test.com"}
        )
    token = issue_token(ui_smoke_engine, uid, label="smoke_test_analyst")
    # we need a senior analyst to create
    uid2 = uuid.uuid4()
    with ui_smoke_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (user_id, email, role) "
                "VALUES (:u, :e, 'senior_analyst')"
            ),
            {"u": uid2, "e": f"{uid2}@test.com"}
        )
    token2 = issue_token(ui_smoke_engine, uid2, label="smoke_test_senior")

    headers = {"Authorization": f"Bearer {token2.plaintext_token}"}
    case_id = None
    try:
        payload: dict[str, Any] = {
            "customer_id": str(uuid.uuid5(uuid.NAMESPACE_OID, "rahul_sharma")),
            "alert_type": "suspicious_transfer",
            "alert_reasons": {"reason": "Test auth boundary"},
        }
        create_resp = requests.post(
            f"{live_server_url}/cases", json=payload, headers=headers
        )
        assert create_resp.status_code == 201, create_resp.text
        case_id = create_resp.json()["case_id"]

        # Do NOT assign to analyst so they cannot see it (visibility failure = 404)
        # with ui_smoke_engine.begin() as conn:
        #     conn.execute(
        #         text(
        #             "UPDATE cases SET assigned_analyst_id = :uid "
        #             "WHERE case_id = :cid"
        #         ),
        #         {"uid": uid, "cid": case_id},
        #     )

        at = AppTest.from_file("../ui/streamlit_app.py")
        at.run(timeout=10)

        at.text_input(key="api_token_input").input(token.plaintext_token).run()
        at.text_input(key="active_case_id").input(str(case_id)).run()
        at.selectbox(key="action").select("APPROVE").run()
        at.button(key="submit_decision_btn").click().run()

        assert not at.exception
        error_msgs = [e.value for e in at.error]
        assert any("not found" in m.lower() for m in error_msgs), error_msgs

        with ui_smoke_engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM cases WHERE case_id = :cid"), {"cid": case_id}
            ).scalar()
            assert status == "OPEN"
    finally:
        _cleanup_case_data(ui_smoke_engine, case_id, None, uid)
        _cleanup_case_data(ui_smoke_engine, None, None, uid2)


def test_seed_integrity(ui_smoke_engine: Engine) -> None:
    seed_dev_users(ui_smoke_engine)
    seed_dev_users(ui_smoke_engine)

    uid1 = uuid.uuid5(uuid.NAMESPACE_OID, "dev_analyst_1")
    uid2 = uuid.uuid5(uuid.NAMESPACE_OID, "dev_senior_analyst_1")

    with ui_smoke_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT user_id, email, role FROM users WHERE user_id IN (:u1, :u2)"),
            {"u1": uid1, "u2": uid2},
        ).fetchall()

        assert len(rows) == 2
        for r in rows:
            if str(r.user_id) == str(uid1):
                assert r.email == "dev.analyst.1@meridian.local"
                assert r.role == "analyst"
            else:
                assert r.email == "dev.senior.analyst.1@meridian.local"
                assert r.role == "senior_analyst"

    uid_conflict = uuid.uuid5(uuid.NAMESPACE_OID, "dev_analyst_1")
    with ui_smoke_engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET role = 'compliance_manager' WHERE user_id = :uid"),
            {"uid": uid_conflict},
        )

    with pytest.raises(RuntimeError) as exc_info:
        seed_dev_users(ui_smoke_engine)

    assert "Dev user seed mismatch" in str(exc_info.value)

    with ui_smoke_engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET role = 'analyst' WHERE user_id = :uid"),
            {"uid": uid_conflict},
        )
