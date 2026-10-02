import os
import subprocess
import typing
from decimal import Decimal

import pytest
from sqlalchemy import Engine

from meridian.fixtures.generator_v03 import generate_fixtures_v03
from meridian.fixtures.signal_baseline import (
    AMOUNT_DEVIATION_DIRECTION,
    BENEFICIARY_AGE_DIRECTION,
    TRANSACTION_VELOCITY_DIRECTION,
    compute_hanley_mcneil_se,
    measure_signal_baselines,
)
from meridian.loader.main import clear_data, insert_data


def test_hanley_mcneil_se() -> None:
    # Test case 1 from prompt
    # A=0.5, n1=10, n2=10 -> SE = 0.1322875656...
    se = compute_hanley_mcneil_se(0.5, 10, 10)
    assert abs(se - 0.132287565553) < 1e-9

    # Test case 2: A=1.0 -> 0.0
    se = compute_hanley_mcneil_se(1.0, 10, 10)
    assert se == 0.0

    # Test case 3: A=0.0 -> 0.0
    se = compute_hanley_mcneil_se(0.0, 10, 10)
    assert se == 0.0

    # Test case 4: null handling equivalent
    se = compute_hanley_mcneil_se(0.5, 0, 10)
    assert se == 0.0

    # Additional hand-computed vector:
    # A=0.75, n1=5, n2=5
    # Q1 = 0.75 / 1.25 = 0.6
    # Q2 = 2 * 0.5625 / 1.75 = 1.125 / 1.75 = 0.6428571428571429
    # A^2 = 0.5625
    # A * (1 - A) = 0.1875
    # var = (0.1875 + 4 * (0.6 - 0.5625) + 4 * (0.6428571428571429 - 0.5625)) / 25
    #     = (0.1875 + 0.15 + 0.3214285714285716) / 25
    #     = 0.6589285714285716 / 25
    #     = 0.026357142857142864
    # SE = sqrt(0.026357142857142864) = 0.162348830784795
    se_hand = compute_hanley_mcneil_se(0.75, 5, 5)
    assert abs(se_hand - 0.162348830784795) < 1e-9


def test_direction_handling() -> None:
    # Check constants
    assert AMOUNT_DEVIATION_DIRECTION == "HIGHER"
    assert TRANSACTION_VELOCITY_DIRECTION == "HIGHER"
    assert BENEFICIARY_AGE_DIRECTION == "LOWER"

    from meridian.fixtures.amount_deviation_baseline import compute_roc_auc

    # Beneficiary age: LOWER = more suspicious
    # If planted data has lower age than clean, AUC should be 1.0 (after applying direction)
    planted_ages = [Decimal(100), Decimal(200)]  # lower
    clean_ages = [Decimal(1000), Decimal(2000)]  # higher

    # Apply direction: negate ages
    auc = compute_roc_auc([-a for a in planted_ages], [-a for a in clean_ages])["auc"]
    assert auc == 1.0

    # If reversing relationship, AUC should be 0.0
    auc = compute_roc_auc([-a for a in clean_ages], [-a for a in planted_ages])["auc"]
    assert auc == 0.0


def test_selection_and_strictness() -> None:
    # Test worked_example, insufficient_history exclusions
    from unittest.mock import MagicMock

    engine = MagicMock(spec=Engine)
    manifest = {
        "fixture_version": "0.3",
        "generator_version": "0.3",
        "seed": "test",
        "split_methodology": "test",
        "fixtures": [
            {"scenario_class": "worked_example", "split": "train", "ground_truth": "CLEAN"},
            {"scenario_class": "insufficient_history", "split": "eval", "ground_truth": "CLEAN"},
        ],
    }

    report = measure_signal_baselines(engine, manifest)
    assert report["exclusions"]["worked_example"] == 1
    assert report["exclusions"]["insufficient_history"] == 1
    assert sum(c["n"] for c in report["signals"]["amount_deviation"]["per_scenario_statistics"].values()) == 0

    # Missing split
    manifest["fixtures"].append({"scenario_class": "structuring", "ground_truth": "CLEAN"})  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="Missing split"):
        measure_signal_baselines(engine, manifest)

    manifest["fixtures"].pop()  # type: ignore[attr-defined]

    # Unexpected split
    manifest["fixtures"].append({"scenario_class": "structuring", "split": "invalid", "ground_truth": "CLEAN"})  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="Unexpected split"):
        measure_signal_baselines(engine, manifest)

    manifest["fixtures"].pop()  # type: ignore[attr-defined]

    # Missing split_methodology
    manifest.pop("split_methodology")
    with pytest.raises(KeyError, match="split_methodology"):
        measure_signal_baselines(engine, manifest)


def test_statistics() -> None:
    from meridian.fixtures.signal_baseline import _compute_median

    assert _compute_median([]) is None
    assert _compute_median([Decimal("1.0")]) == Decimal("1.0")
    assert _compute_median([Decimal("1.0"), Decimal("3.0")]) == Decimal("2.0")
    assert _compute_median([Decimal("2.0"), Decimal("3.0"), Decimal("4.0")]) == Decimal("3.0")
    # exact Decimal arithmetic
    assert _compute_median([Decimal("1.111111"), Decimal("2.222222")]) == Decimal("1.6666665")


def test_determinism(tmp_path: typing.Any, superuser_engine: Engine) -> None:
    # Same database state
    res = generate_fixtures_v03("baseline_seed")
    clear_data(superuser_engine)
    insert_data(superuser_engine, res)

    try:
        def run_cli(hash_seed: str, cwd: str) -> str:
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = hash_seed
            env["PYTHONPATH"] = os.path.abspath("src")
            # Override DATABASE_URL to use the test database
            env["DATABASE_URL"] = superuser_engine.url.render_as_string(hide_password=False)
            script = """
import sys
from meridian.fixtures.signal_baseline import measure_signal_baselines
from meridian.fixtures.generator_v03 import generate_fixtures_v03
from meridian.fixtures.amount_deviation_baseline import canonical_json
from sqlalchemy import create_engine
import os

db_url = os.environ.get("DATABASE_URL")
engine = create_engine(db_url)
res = generate_fixtures_v03("baseline_seed")
report = measure_signal_baselines(engine, res["manifest"])
print(canonical_json(report), end="")
"""
            script_path = os.path.join(cwd, "run_cli.py")
            with open(script_path, "w") as f:
                f.write(script)

            try:
                subprocess_res = subprocess.run(
                    ["uv", "run", "python", "run_cli.py"],
                    env=env,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                print(f"STDOUT: {e.stdout}\nSTDERR: {e.stderr}")
                raise
            return subprocess_res.stdout

        d1 = tmp_path / "d1"
        d2 = tmp_path / "d2"
        d1.mkdir()
        d2.mkdir()

        out1 = run_cli("1", str(d1))
        out2 = run_cli("999", str(d2))

        assert out1 == out2
        assert out1.endswith("\n")
    finally:
        clear_data(superuser_engine)


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


def test_db_backed_integration(superuser_engine: Engine) -> None:
    res = generate_fixtures_v03("test_db_seed")
    clear_data(superuser_engine)
    insert_data(superuser_engine, res)

    try:
        counts_before = _get_counts(superuser_engine)
        report = measure_signal_baselines(superuser_engine, res["manifest"])
        counts_after = _get_counts(superuser_engine)

        assert counts_before == counts_after, "Measurement module is not read-only"

        signals = report["signals"]
        assert "amount_deviation" in signals
        assert "transaction_velocity" in signals
        assert "beneficiary_age" in signals

        # Check total included counts match
        for signal_name, signal_data in signals.items():
            total_n = sum(stats["n"] for stats in signal_data["per_scenario_statistics"].values())
            # Total fixtures = 58. worked_example = 1, insufficient = 1. Eligible = 56
            assert total_n == 56

        # Check group keys match manifest groups
        man_groups = set()
        for fx in res["manifest"]["fixtures"]:
            if fx["scenario_class"] not in ("worked_example", "insufficient_history"):
                group = fx["scenario_class"]
                if "scenario_subtype" in fx:
                    group += "/" + fx["scenario_subtype"]
                man_groups.add(group)

        assert set(signals["amount_deviation"]["per_scenario_statistics"].keys()) == man_groups

        assert "worked_example" in report["exclusions"]
        assert "insufficient_history" in report["exclusions"]
    finally:
        clear_data(superuser_engine)


def test_import_guard() -> None:
    import ast
    from pathlib import Path

    file_path = Path(__file__).parent.parent / "src" / "meridian" / "fixtures" / "signal_baseline.py"
    with open(file_path, "r") as f:
        tree = ast.parse(f.read())

    forbidden_imports = [
        "meridian.fixtures.generator",
        "meridian.fixtures.generator_v03",
        "meridian.orchestration",
        "meridian.evidence",
        "meridian.reports",
        "meridian.report",
    ]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # We only check top-level imports here.
                # __main__ block imports are fine.
                pass
        elif isinstance(node, ast.ImportFrom):
            if getattr(node, "module", None):
                for forbidden in forbidden_imports:
                    # Check if node is at the top level
                    pass

    # A better way is to only check nodes that are in the body of the module (top-level)
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            # Skip __main__ block
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                for forbidden in forbidden_imports:
                    assert not alias.name.startswith(forbidden), f"Forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                for forbidden in forbidden_imports:
                    assert not node.module.startswith(forbidden), f"Forbidden import: {node.module}"
