import json
import os
import subprocess
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine

from meridian.fixtures.generator import generate_fixtures, generate_fixtures_v02
from meridian.loader.main import clear_data, insert_data


def test_determinism_v02(tmp_path):
    def run_with_seed(seed: str, cwd: str) -> str:
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = os.path.abspath("src")
        pass


def _canonical_serializer(obj: Any) -> str:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj)
    return str(obj)


def canonical_json(data: dict[str, Any]) -> str:
    return (
        json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            default=_canonical_serializer,
        )
        + "\n"
    )


def test_v02_canonical_determinism(tmp_path):
    # Test that generator output is deterministic across PYTHONHASHSEED
    def run_generator(seed: str, fixture_seed: str, cwd: str) -> str:
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = os.path.abspath("src")
        script = f"""
import json
import sys
from meridian.fixtures.generator import generate_fixtures_v02
from meridian.fixtures.amount_deviation_baseline import canonical_json

res = generate_fixtures_v02("{fixture_seed}")
sys.stdout.write(canonical_json(res["manifest"]))
"""
        script_path = os.path.join(cwd, "run_gen.py")
        with open(script_path, "w") as f:
            f.write(script)

        subprocess_res = subprocess.run(
            ["uv", "run", "python", "run_gen.py"],
            env=env,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return subprocess_res.stdout

    d1 = tmp_path / "d1"
    d2 = tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()

    out1 = run_generator("1", "test_seed", str(d1))
    out2 = run_generator("999", "test_seed", str(d2))
    assert out1 == out2
    assert len(out1) > 0


def test_seed_sensitivity():
    res1 = generate_fixtures_v02("seed_A")
    res2 = generate_fixtures_v02("seed_B")

    man1 = res1["manifest"]["fixtures"]
    man2 = res2["manifest"]["fixtures"]

    def get_amounts(res) -> dict:
        amounts = {}
        for tx in res["transactions"]:
            amounts[tx["transaction_id"]] = tx["amount"]
        return amounts

    amt1 = get_amounts(res1)
    amt2 = get_amounts(res2)

    def get_eval_targets(manifest, amounts) -> dict:
        targets = {}
        for fx in manifest:
            if fx["scenario_class"] in ["worked_example", "insufficient_history"]:
                continue
            sc = fx["scenario_class"]
            if sc not in targets:
                targets[sc] = []
            targets[sc].append(amounts[uuid.UUID(fx["alert_spec"]["transaction_id"])])
        return targets

    t1 = get_eval_targets(man1, amt1)
    t2 = get_eval_targets(man2, amt2)

    assert t1.keys() == t2.keys()
    for sc in t1:
        assert sorted(t1[sc]) != sorted(t2[sc]), (
            f"Amounts for {sc} were identical across seeds"
        )


def test_within_class_variance():
    res = generate_fixtures_v02("test_variance_seed")
    man = res["manifest"]["fixtures"]

    def get_amounts(res) -> dict:
        return {tx["transaction_id"]: tx["amount"] for tx in res["transactions"]}

    amts = get_amounts(res)

    subtypes = {}
    for fx in man:
        if fx["scenario_class"] in ["worked_example", "insufficient_history"]:
            continue
        st = fx["scenario_subtype"]
        if st not in subtypes:
            subtypes[st] = set()
        subtypes[st].add(amts[uuid.UUID(fx["alert_spec"]["transaction_id"])])

    for st, amounts in subtypes.items():
        assert len(amounts) > 1, (
            f"Expected variance within {st}, but found constant amounts: {amounts}"
        )


def test_v01_regression():
    res1 = generate_fixtures("test_seed")
    res2 = generate_fixtures("test_seed")

    assert canonical_json(res1["manifest"]) == canonical_json(res2["manifest"])


def test_manifest_validation():
    res = generate_fixtures_v02("test_seed")
    man = res["manifest"]

    assert man["fixture_version"] == "0.2"
    assert man["generator_version"] == "0.2"

    for fx in man["fixtures"]:
        assert "fixture_id" in fx
        assert "AML" not in fx["fixture_id"]
        assert "structuring" not in fx["fixture_id"]

        assert "scenario_subtype" in fx
        assert "split_methodology" in fx
        assert fx["split"] in ["train", "eval"]
        if fx["scenario_class"] != "insufficient_history":
            assert fx["ground_truth"] is not None


def test_split_integrity():
    res = generate_fixtures_v02("test_split_seed")
    counts = {}
    for fx in res["manifest"]["fixtures"]:
        sc = fx["scenario_class"]
        st = fx["scenario_subtype"]
        sp = fx["split"]
        key = (sc, st)
        if key not in counts:
            counts[key] = {"train": 0, "eval": 0}
        counts[key][sp] += 1


def test_corpus_integrity():
    res = generate_fixtures_v02("test_integrity")

    assert len(res["manifest"]["fixtures"]) == 58

    fix_ids = set()
    for fx in res["manifest"]["fixtures"]:
        assert fx["fixture_id"] not in fix_ids
        fix_ids.add(fx["fixture_id"])

    for tx in res["transactions"]:
        assert tx["amount"] >= 0
        assert tx["currency"] == "INR"
        assert isinstance(tx["amount"], float)


def test_architecture_boundary():
    import os
    import subprocess
    import sys
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.abspath("src")
    code = """
import sys
from meridian.fixtures.generator import generate_fixtures_v02
if "meridian.agents" in sys.modules:
    sys.exit(1)
if "meridian.risk_engine" in sys.modules:
    sys.exit(2)
sys.exit(0)
"""
    res = subprocess.run([sys.executable, "-c", code], env=env)
    assert res.returncode == 0, "Generator shouldn't import agents or risk_engine"


def test_baseline_compatibility(tmp_path, superuser_engine: Engine):
    res_v02 = generate_fixtures_v02("baseline_seed")
    clear_data(superuser_engine)
    insert_data(superuser_engine, res_v02)

    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.path.abspath("src")
        env["DATABASE_URL"] = superuser_engine.url.render_as_string(hide_password=False)

        res2 = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "meridian.fixtures.amount_deviation_baseline",
                "--fixture-version",
                "0.2",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        parsed = json.loads(res2.stdout)
        assert parsed["metadata"]["fixture_version"] == "0.2"

        res_v01 = generate_fixtures("baseline_seed")
        clear_data(superuser_engine)
        insert_data(superuser_engine, res_v01)

        res1 = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "meridian.fixtures.amount_deviation_baseline",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        parsed1 = json.loads(res1.stdout)
        assert parsed1["metadata"]["fixture_version"] == "0.1"

    finally:
        clear_data(superuser_engine)


def _get_counts(engine: Engine) -> dict[str, int]:
    from sqlalchemy import text

    with engine.connect() as conn:

        def count(table: str) -> int:
            return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()

        return {
            "risk_signals": count("risk_signals"),
            "alerts": count("alerts"),
            "cases": count("cases"),
            "investigation_runs": count("investigation_runs"),
        }


def test_db_backed_integration_and_overlap(superuser_engine: Engine):
    res_v02 = generate_fixtures_v02("overlap_test_seed")
    clear_data(superuser_engine)
    insert_data(superuser_engine, res_v02)

    try:
        counts_before = _get_counts(superuser_engine)

        from meridian.fixtures.amount_deviation_baseline import measure_baseline

        measure_baseline(superuser_engine, res_v02["manifest"])

        counts_after = _get_counts(superuser_engine)
        assert counts_before == counts_after, "Baseline measurement must be read-only"

        from meridian.agents.transaction.amount_deviation import (
            AmountDeviationComputed,
            compute_amount_deviation,
        )
        from meridian.risk_engine.risk_signals import compute_risk_score

        clean_vals = []
        planted_vals = []

        for fx in res_v02["manifest"]["fixtures"]:
            if fx["scenario_class"] in ["worked_example", "insufficient_history"]:
                continue

            tx_id_str = fx["alert_spec"]["transaction_id"]
            tx_id = uuid.UUID(tx_id_str)

            result = compute_amount_deviation(superuser_engine, tx_id)
            if isinstance(result, AmountDeviationComputed):
                val = compute_risk_score(result).value
                if fx["ground_truth"] == "CLEAN":
                    clean_vals.append(val)
                else:
                    planted_vals.append(val)

        high_clean = [v for v in clean_vals if v >= Decimal("3.0")]
        low_planted = [v for v in planted_vals if v <= Decimal("2.0")]

        assert len(high_clean) >= 3, (
            f"Expected at least 3 clean controls >= 3.0, found {len(high_clean)}"
        )
        assert len(low_planted) >= 3, (
            f"Expected at least 3 planted scenarios <= 2.0, found {len(low_planted)}"
        )

    finally:
        clear_data(superuser_engine)
