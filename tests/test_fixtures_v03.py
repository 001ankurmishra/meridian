import hashlib
import json
import os
import subprocess
import sys
import typing
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine

from meridian.fixtures.generator import generate_fixtures, generate_fixtures_v02
from meridian.fixtures.generator_v03 import generate_fixtures_v03
from meridian.loader.main import clear_data, insert_data


def _canonical_serializer(obj: Any) -> str:
    if isinstance(obj, Decimal):
        return f"{obj:.2f}"
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
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


def compute_hash(data: dict[str, Any]) -> str:
    s = canonical_json(data)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def test_determinism_v03(tmp_path: typing.Any) -> None:
    def run_generator(hash_seed: str, fixture_seed: str, cwd: str) -> str:
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = hash_seed
        env["PYTHONPATH"] = os.path.abspath("src")
        script = f"""
import json
import sys
import uuid
from decimal import Decimal
from datetime import datetime, date
from meridian.fixtures.generator_v03 import generate_fixtures_v03

def default_serializer(obj):
    if isinstance(obj, Decimal): return f"{{obj:.2f}}"
    if isinstance(obj, (datetime, date)): return obj.isoformat()
    if isinstance(obj, uuid.UUID): return str(obj)
    raise TypeError()

res = generate_fixtures_v03("{fixture_seed}")
t = (
    res["manifest"]["generator_version"],
    res["manifest"]["fixture_version"],
    res["manifest"]["seed"]
)
out = json.dumps(
    t, sort_keys=True, separators=(',', ':'), default=default_serializer
) + "\\n"
import hashlib
h = hashlib.sha256(out.encode('utf-8')).hexdigest()
sys.stdout.write(h)
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


def test_seed_sensitivity() -> None:
    seeds = ["seed_A", "seed_B", "seed_C"]
    results = [generate_fixtures_v03(s) for s in seeds]

    def extract_tuples(res: dict[str, Any]) -> list[Any]:
        tups: list[Any] = []
        amts = {tx["transaction_id"]: tx["amount"] for tx in res["transactions"]}
        for fix in res["manifest"]["fixtures"]:
            if fix["scenario_class"] in ("worked_example", "insufficient_history"):
                continue
            amt = amts[uuid.UUID(fix["alert_spec"]["transaction_id"])]
            extra = fix["generation_params"]["extra_recent_outgoing"]
            bene = fix["generation_params"]["bene_state"]
            at = fix["alert_spec"]["alert_type"]
            tups.append((amt, extra, bene, at))
        return tups

    tups_list = [extract_tuples(r) for r in results]

    for i in range(len(seeds)):
        for j in range(i + 1, len(seeds)):
            assert tups_list[i] != tups_list[j], (
                f"Seed sensitivity failed for {seeds[i]} and {seeds[j]}"
            )

            diff_amt = sum(
                1 for a, b in zip(tups_list[i], tups_list[j]) if a[0] != b[0]
            )
            diff_extra = sum(
                1 for a, b in zip(tups_list[i], tups_list[j]) if a[1] != b[1]
            )
            diff_bene = sum(
                1 for a, b in zip(tups_list[i], tups_list[j]) if a[2] != b[2]
            )
            diff_alert = sum(
                1 for a, b in zip(tups_list[i], tups_list[j]) if a[3] != b[3]
            )

            print(
                f"Diffs between {seeds[i]} and {seeds[j]}: "
                f"amt={diff_amt}, extra={diff_extra}, "
                f"bene={diff_bene}, alert={diff_alert}"
            )


def test_v01_v02_reproducibility() -> None:
    # They guard reproducibility of the immutable corpora.
    v01_hash = "8565c9e8c79a5116170cd9b79be7d4d5148cfe9e8d7a147714b0c4e8b6331b49"
    v02_hash = "25a2ff475dc6514c6f4e9f1ae23b6565be69468f5dd9158931995ec4dc741caf"

    res1 = generate_fixtures("seed1")
    assert compute_hash(res1) == v01_hash

    res2 = generate_fixtures_v02("baseline_seed")
    assert compute_hash(res2) == v02_hash


def test_manifest_validation() -> None:
    res = generate_fixtures_v03("test_seed")
    man = res["manifest"]

    assert man["fixture_version"] == "0.3"
    assert man["generator_version"] == "0.3"

    for fx in man["fixtures"]:
        assert "fixture_id" in fx
        assert "split_methodology" in fx
        assert fx["split"] in ["train", "eval"]
        assert (
            fx.get("ground_truth") is not None
            or fx["scenario_class"] == "insufficient_history"
        )

        # generation_params consistent
        if fx["scenario_class"] not in ("worked_example", "insufficient_history"):
            assert "generation_params" in fx
            extra = fx["generation_params"]["extra_recent_outgoing"]

            from datetime import timedelta

            txs = [
                t
                for t in res["transactions"]
                if t["source_account_id"] == uuid.UUID(fx["account_ids"][0])
            ]
            target_tx = next(
                t
                for t in res["transactions"]
                if str(t["transaction_id"]) == fx["alert_spec"]["transaction_id"]
            )
            recent = [
                t
                for t in txs
                if t["occurred_at"] >= target_tx["occurred_at"] - timedelta(hours=24)
                and t["occurred_at"] <= target_tx["occurred_at"]
            ]
            assert len(recent) == 1 + extra


def test_full_integrity() -> None:
    res = generate_fixtures_v03("test_integrity")

    assert len(res["manifest"]["fixtures"]) == 58

    fix_ids = set()
    for fx in res["manifest"]["fixtures"]:
        assert fx["fixture_id"] not in fix_ids
        fix_ids.add(fx["fixture_id"])

    for tx in res["transactions"]:
        assert tx["amount"] >= 0
        assert tx["currency"] == "INR"
        assert "fixture:" in tx["source"] or "worked_example" in tx["source"]

    for cust in res["customers"]:
        assert cust["is_synthetic"]

    # F3 history rows check, etc.
    from datetime import timedelta

    for fx in res["manifest"]["fixtures"]:
        if fx["scenario_class"] not in ("worked_example", "insufficient_history"):
            txs = [
                t
                for t in res["transactions"]
                if t["source_account_id"] == uuid.UUID(fx["account_ids"][0])
            ]
            target_tx = next(
                t
                for t in res["transactions"]
                if str(t["transaction_id"]) == fx["alert_spec"]["transaction_id"]
            )
            hist_txs = [
                t
                for t in txs
                if t["occurred_at"] <= target_tx["occurred_at"] - timedelta(hours=24)
            ]
            assert len(hist_txs) >= 3


def test_beneficiary_fixture_design_guards() -> None:
    res = generate_fixtures_v03("bene_test")
    man = res["manifest"]

    from collections import defaultdict

    groups = defaultdict(list)
    for fix in man["fixtures"]:
        if fix["scenario_class"] not in ("worked_example", "insufficient_history"):
            groups[(fix["scenario_class"], fix.get("scenario_subtype", "none"))].append(
                fix
            )

    has_fresh = False
    has_est = False

    for (sc, st), group in groups.items():
        states = [fx["generation_params"]["bene_state"] for fx in group]
        if len(group) >= 4:
            assert "absent" in states
            assert "fresh" in states
            assert "established" in states

        for fx in group:
            if (
                fx["scenario_class"] == "clean_control"
                and fx["generation_params"]["bene_state"] == "fresh"
            ):
                has_fresh = True
            if (
                fx["scenario_class"] != "clean_control"
                and fx["generation_params"]["bene_state"] == "established"
            ):
                has_est = True

    assert has_fresh, "controls contain fresh"
    assert has_est, "planted fixtures contain established"


def test_alert_type_guards() -> None:
    res = generate_fixtures_v03("alert_test")
    man = res["manifest"]

    from collections import defaultdict

    groups = defaultdict(list)
    for fix in man["fixtures"]:
        if fix["scenario_class"] not in ("worked_example", "insufficient_history"):
            groups[(fix["scenario_class"], fix.get("scenario_subtype", "none"))].append(
                fix
            )

    CONFIRMED = ["large_transaction", "new_beneficiary", "rapid_movement"]

    planted_ats = set()
    control_ats = set()

    for (sc, st), group in groups.items():
        ats = [fx["alert_spec"]["alert_type"] for fx in group]
        for at in ats:
            assert at in CONFIRMED
            assert at not in ["AML_STRUCTURING", "AML_RAPID_MOVEMENT"]
            assert at != group[0]["ground_truth"]

            if group[0]["ground_truth"] == "CLEAN":
                control_ats.add(at)
            else:
                planted_ats.add(at)

        if len(group) >= 3:
            for c in CONFIRMED:
                assert c in ats

        for fx in group:
            assert (
                fx["alert_spec"]["alert_reasons"]["reason"] == "System generated alert"
            )

    assert planted_ats == set(CONFIRMED)
    assert control_ats == set(CONFIRMED)


def test_import_guard() -> None:
    import os
    import subprocess

    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.abspath("src")
    code = """
import sys
from meridian.fixtures.generator_v03 import generate_fixtures_v03
if "meridian.agents" in sys.modules:
    sys.exit(1)
if "meridian.risk_engine" in sys.modules:
    sys.exit(2)
if "meridian.orchestration" in sys.modules:
    sys.exit(3)
sys.exit(0)
"""
    res = subprocess.run([sys.executable, "-c", code], env=env)
    assert res.returncode == 0, (
        "Generator shouldn't import agents or risk_engine or orchestration"
    )


def _get_counts(engine: Engine) -> dict[str, int]:
    from sqlalchemy import text

    with engine.connect() as conn:

        def count(table: str) -> int:
            val = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            return int(val) if val is not None else 0

        return {
            "risk_signals": count("risk_signals"),
            "alerts": count("alerts"),
            "cases": count("cases"),
            "investigation_runs": count("investigation_runs"),
        }


def test_db_backed_integration_and_overlap(superuser_engine: Engine) -> None:
    res_v03 = generate_fixtures_v03("overlap_test_seed")
    clear_data(superuser_engine)
    insert_data(superuser_engine, res_v03)

    try:
        counts_before = _get_counts(superuser_engine)

        from meridian.agents.transaction.amount_deviation import (
            AmountDeviationComputed,
            compute_amount_deviation,
        )
        from meridian.agents.transaction.beneficiary_age import compute_beneficiary_age
        from meridian.agents.transaction.transaction_velocity import (
            compute_transaction_velocity,
        )

        clean_vels = []
        planted_struct_vels = []
        clean_ages = []
        planted_ages = []

        for fx in res_v03["manifest"]["fixtures"]:
            if fx["scenario_class"] in ["worked_example", "insufficient_history"]:
                continue

            tx_id_str = fx["alert_spec"]["transaction_id"]
            tx_id = uuid.UUID(tx_id_str)

            result_amt = compute_amount_deviation(superuser_engine, tx_id)
            assert isinstance(result_amt, AmountDeviationComputed)

            result_vel = compute_transaction_velocity(superuser_engine, tx_id)
            if fx["ground_truth"] == "CLEAN":
                clean_vels.append(result_vel.transaction_count)
            elif fx["scenario_class"] == "structuring":
                planted_struct_vels.append(result_vel.transaction_count)

            result_age = compute_beneficiary_age(superuser_engine, tx_id)
            from meridian.agents.transaction.beneficiary_age import (
                BeneficiaryAgeComputed,
            )

            if isinstance(result_age, BeneficiaryAgeComputed):
                if fx["ground_truth"] == "CLEAN":
                    clean_ages.append(result_age.beneficiary_age.days)
                else:
                    planted_ages.append(result_age.beneficiary_age.days)

        counts_after = _get_counts(superuser_engine)
        assert counts_before == counts_after, "Signals must be read-only"

        # design overlap guards
        # 1. velocity counts among controls intersect structuring targets
        intersection = set(clean_vels).intersection(set(planted_struct_vels))
        assert len(intersection) > 0, (
            f"Expected velocity overlap, got clean={set(clean_vels)} "
            f"and struct={set(planted_struct_vels)}"
        )

        # 2. at least 2 control targets have Computed beneficiary age < 7 days
        recent_clean = [a for a in clean_ages if a < 7]
        assert len(recent_clean) >= 2

        # 3. at least 2 planted targets have Computed beneficiary age >= 30 days
        old_planted = [a for a in planted_ages if a >= 30]
        assert len(old_planted) >= 2

    finally:
        clear_data(superuser_engine)


def test_baseline_compatibility(tmp_path: typing.Any, superuser_engine: Engine) -> None:
    res_v03 = generate_fixtures_v03("baseline_seed")
    clear_data(superuser_engine)
    insert_data(superuser_engine, res_v03)
    try:
        from meridian.fixtures.amount_deviation_baseline import measure_baseline
        counts_before = _get_counts(superuser_engine)
        measure_baseline(superuser_engine, res_v03["manifest"])
        counts_after = _get_counts(superuser_engine)
        assert counts_before == counts_after, "Baseline mutated DB state"
    finally:
        clear_data(superuser_engine)
