"""Tests for deterministic synthetic fixture generation."""

import json
import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import Engine, text

from meridian.case_management.alert_intake import create_alert_and_case
from meridian.fixtures.generator import generate_fixtures
from meridian.loader.main import insert_data
from meridian.orchestration.investigation_orchestrator import orchestrate_investigation
from tests.db_cleanup import clean_investigation_run_dependencies


def test_determinism_same_seed():
    """Same seed produces identical output."""
    res1 = generate_fixtures("seed1")
    res2 = generate_fixtures("seed1")
    assert json.dumps(res1, sort_keys=True, default=str) == json.dumps(
        res2, sort_keys=True, default=str
    )


def test_determinism_different_seed():
    """Different seed produces materially different output."""
    res1 = generate_fixtures("seed1")
    res2 = generate_fixtures("seed2")
    assert len(res1["manifest"]["fixtures"]) == len(res2["manifest"]["fixtures"])

    fx1_gen = [
        f for f in res1["manifest"]["fixtures"]
        if f["scenario_class"] != "worked_example"
    ]
    fx2_gen = [
        f for f in res2["manifest"]["fixtures"]
        if f["scenario_class"] != "worked_example"
    ]

    assert json.dumps(fx1_gen, sort_keys=True, default=str) != json.dumps(
        fx2_gen, sort_keys=True, default=str
    )


def _get_hash_from_subprocess(seed: str, env: dict[str, str], cwd: str) -> str:
    import os
    src_path = os.path.abspath("src")
    script = f"""
import json
import sys
sys.path.insert(0, {repr(src_path)})
from meridian.fixtures.generator import generate_fixtures

res = generate_fixtures("{seed}")
dump = json.dumps(res, sort_keys=True, default=str)
import hashlib
print(hashlib.sha256(dump.encode()).hexdigest())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout.strip()


def test_determinism_pythonhashseed_and_process():
    """Output is identical across different processes and PYTHONHASHSEED."""
    env = os.environ.copy()

    # Needs to be tested with seed
    seed = "process_seed"

    env["PYTHONHASHSEED"] = "1"
    hash1 = _get_hash_from_subprocess(seed, env, os.getcwd())

    env["PYTHONHASHSEED"] = "999"
    hash2 = _get_hash_from_subprocess(seed, env, os.getcwd())

    assert hash1 == hash2


def test_determinism_working_directory(tmp_path):
    """Output is identical across different working directories."""
    env = os.environ.copy()
    seed = "dir_seed"
    hash1 = _get_hash_from_subprocess(seed, env, os.getcwd())
    hash2 = _get_hash_from_subprocess(seed, env, str(tmp_path))
    assert hash1 == hash2


def test_manifest_validation():
    """Manifest follows required schema."""
    res = generate_fixtures("seed_z")
    man = res["manifest"]

    assert "manifest_schema_version" in man
    assert "fixture_version" in man
    assert "generator_version" in man
    assert "seed" in man
    assert "anchor_timestamp" in man

    fixtures = man["fixtures"]
    assert len(fixtures) == 20  # 20 scenarios

    scenario_counts = {}
    for f in fixtures:
        sc = f["scenario_class"]
        scenario_counts[sc] = scenario_counts.get(sc, 0) + 1
        assert "fixture_id" in f
        assert "taxonomy" in f
        assert "split" in f
        assert "customer_id" in f
        assert "evaluation_target" in f
        assert "ground_truth" in f
        assert "planted_pattern" in f
        assert "pattern_members" in f
        assert "runtime_expectation" in f
        assert "alert_spec" in f

    assert scenario_counts["structuring"] == 3
    assert scenario_counts["rapid_movement"] == 3
    assert scenario_counts["circular_transfer"] == 3
    assert scenario_counts["mule_account_chain"] == 3
    assert scenario_counts["clean_control"] == 6
    assert scenario_counts["insufficient_history"] == 1
    assert scenario_counts["worked_example"] == 1


def test_fixture_smoke_test(
    superuser_engine: Engine,
    app_role_engine: Engine,
    loader_role_engine: Engine,
):
    """Integration smoke test for fixture ingestion, orchestration and cleanup."""
    loader_url = os.environ.get("LOADER_DATABASE_URL")
    db_url = os.environ.get("DATABASE_URL")
    if not loader_url or not db_url:
        pytest.skip("Database URLs not set")

    res = generate_fixtures("smoke_seed")
    fixtures = res["manifest"]["fixtures"]

    # Pick one of each scenario
    scenarios_to_test = {}
    for f in fixtures:
        if f["scenario_class"] not in scenarios_to_test:
            scenarios_to_test[f["scenario_class"]] = f

    # Load all data
    from meridian.loader.main import clear_data
    clear_data(superuser_engine)
    insert_data(superuser_engine, res)

    # Load policy documents so PolicyAgent doesn't fail
    from meridian.loader.policy_ingest import ingest_policy_corpus
    ingest_policy_corpus(loader_role_engine)

    created_case_ids = []
    created_alert_ids = []

    try:
        for sc_name, fx in scenarios_to_test.items():
            customer_id = uuid.UUID(fx["alert_spec"]["customer_id"])
            tx_id_str = fx["alert_spec"]["transaction_id"]
            tx_id = uuid.UUID(tx_id_str) if tx_id_str else None

            # Intake
            intake_res = create_alert_and_case(
                app_role_engine,
                customer_id,
                fx["alert_spec"]["alert_type"],
                fx["alert_spec"]["alert_reasons"],
                transaction_id=tx_id,
                source_system=f"fixture_test_{fx['fixture_id']}"
            )
            created_alert_ids.append(intake_res.alert_id)
            created_case_ids.append(intake_res.case_id)

            # Orchestrate
            status = orchestrate_investigation(app_role_engine, intake_res.case_id)

            # Verify status matches expectation
            expected_status = fx["runtime_expectation"]
            assert status == expected_status

            # Verify persisted status
            with app_role_engine.connect() as conn:
                db_status = conn.execute(
                    text("SELECT status FROM investigation_runs WHERE case_id = :cid"),
                    {"cid": intake_res.case_id}
                ).scalar()
                assert db_status == expected_status

    finally:
        # Cleanup
        with superuser_engine.begin() as conn:
            for case_id in created_case_ids:
                run_ids = conn.execute(
                    text(
                        "SELECT investigation_run_id FROM "
                        "investigation_runs WHERE case_id = :cid"
                    ),
                    {"cid": case_id}
                ).scalars().all()
                for rid in run_ids:
                    clean_investigation_run_dependencies(conn, investigation_run_id=rid)
                conn.execute(
                    text("DELETE FROM cases WHERE case_id = :cid"), {"cid": case_id}
                )

            for alert_id in created_alert_ids:
                conn.execute(
                    text("DELETE FROM alerts WHERE alert_id = :aid"), {"aid": alert_id}
                )

            # FK-safe removal of fixture data
            if res["graph_relationships"]:
                ids = [r["relationship_id"] for r in res["graph_relationships"]]
                res_del = conn.execute(
                    text("DELETE FROM graph_relationships "
                         "WHERE relationship_id = ANY(:ids)"),
                    {"ids": ids}
                )
                assert res_del.rowcount == len(ids)

            if res["entities"]:
                ids = [e["entity_id"] for e in res["entities"]]
                res_del = conn.execute(
                    text("DELETE FROM entities WHERE entity_id = ANY(:ids)"),
                    {"ids": ids}
                )
                assert res_del.rowcount == len(ids)

            if res["beneficiaries"]:
                ids = [b["beneficiary_id"] for b in res["beneficiaries"]]
                res_del = conn.execute(
                    text("DELETE FROM beneficiaries WHERE beneficiary_id = ANY(:ids)"),
                    {"ids": ids}
                )
                assert res_del.rowcount == len(ids)

            if res["transactions"]:
                ids = [t["transaction_id"] for t in res["transactions"]]
                res_del = conn.execute(
                    text("DELETE FROM transactions WHERE transaction_id = ANY(:ids)"),
                    {"ids": ids}
                )
                assert res_del.rowcount == len(ids)

            if res["accounts"]:
                ids = [a["account_id"] for a in res["accounts"]]
                res_del = conn.execute(
                    text("DELETE FROM accounts WHERE account_id = ANY(:ids)"),
                    {"ids": ids}
                )
                assert res_del.rowcount == len(ids)

            if res["customers"]:
                ids = [c["customer_id"] for c in res["customers"]]
                res_del = conn.execute(
                    text("DELETE FROM customers WHERE customer_id = ANY(:ids)"),
                    {"ids": ids}
                )
                assert res_del.rowcount == len(ids)
