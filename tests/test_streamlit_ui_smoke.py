import os
import socket
import subprocess
import time
import uuid
from typing import Generator

import pytest
import requests
from sqlalchemy import Engine, text
from streamlit.testing.v1 import AppTest

from meridian.loader.dev_users import seed_dev_users
from meridian.loader.main import get_migrator_engine


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        # Ensure we return int and not Any by casting
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def live_server_url() -> Generator[str, None, None]:
    port = get_free_port()

    from meridian.loader.main import main as loader_main

    loader_main()

    env = os.environ.copy()
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
    eng = get_migrator_engine()
    yield eng
    eng.dispose()


def test_ui_smoke_startup(live_server_url: str) -> None:
    at = AppTest.from_file("../ui/streamlit_app.py")
    at.run(timeout=10)
    assert not at.exception


def test_ui_smoke_happy_path(live_server_url: str, ui_smoke_engine: Engine) -> None:
    payload = {
        "customer_id": str(uuid.uuid5(uuid.NAMESPACE_OID, "rahul_sharma")),
        "alert_type": "suspicious_transfer",
        "alert_reasons": {"reason": "Test happy path"},
    }

    create_resp = requests.post(f"{live_server_url}/cases", json=payload)  # type: ignore
    assert create_resp.status_code == 201, create_resp.text
    case_id = create_resp.json()["case_id"]

    inv_resp = requests.post(f"{live_server_url}/cases/{case_id}/investigate")
    assert inv_resp.status_code == 200

    at = AppTest.from_file("../ui/streamlit_app.py")
    at.run(timeout=10)

    at.text_input(key="active_case_id").input(str(case_id)).run()
    at.selectbox(key="acting_identity").select(
        "Dev Senior Analyst 1 (senior_analyst)"
    ).run()
    at.selectbox(key="action").select("APPROVE").run()

    # We must click the "Submit Decision" button which is a form submit button.
    # AppTest exposes it as a normal button typically,
    # but if it has a label we can find it by label?
    # No, AppTest doesn't support select by label easily if it's a form submit button.
    # Wait, the button won't exist if the case_id isn't populated!
    # Ah! In the first run, case_id is empty, so it STOPS!
    # After we input case_id and run, it re-renders and the rest of the UI appears!
    # Then we can find the submit button. It will be the last button.
    at.button(key="submit_decision_btn").click().run()

    assert not at.exception
    success_msgs = [s.value for s in at.success]
    assert any("Decision submitted successfully" in m for m in success_msgs)

    with ui_smoke_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM cases WHERE case_id = :cid"), {"cid": case_id}
        ).scalar()
        assert status == "CLOSED_APPROVED"


def test_ui_smoke_auth_boundary(live_server_url: str, ui_smoke_engine: Engine) -> None:
    payload = {
        "customer_id": str(uuid.uuid5(uuid.NAMESPACE_OID, "rahul_sharma")),
        "alert_type": "suspicious_transfer",
        "alert_reasons": {"reason": "Test auth boundary"},
    }
    create_resp = requests.post(f"{live_server_url}/cases", json=payload)  # type: ignore
    assert create_resp.status_code == 201, create_resp.text
    case_id = create_resp.json()["case_id"]

    at = AppTest.from_file("../ui/streamlit_app.py")
    at.run(timeout=10)

    at.text_input(key="active_case_id").input(str(case_id)).run()
    at.selectbox(key="acting_identity").select("Dev Analyst 1 (analyst)").run()
    at.selectbox(key="action").select("APPROVE").run()
    at.button(key="submit_decision_btn").click().run()

    assert not at.exception
    error_msgs = [e.value for e in at.error]
    assert any("not authorized" in m for m in error_msgs)

    with ui_smoke_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM cases WHERE case_id = :cid"), {"cid": case_id}
        ).scalar()
        assert status == "OPEN"


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
