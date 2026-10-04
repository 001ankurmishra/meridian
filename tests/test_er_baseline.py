import json
import os
import subprocess
from pathlib import Path

from sqlalchemy import Engine, text

from meridian.fixtures.er_baseline import measure_er_baseline
from meridian.fixtures.generator_v05 import generate_fixtures_v05
from meridian.loader.main import insert_data


def _clear_data(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE alerts, recommendations, findings, document_chunks, "
                "documents, graph_relationships, entities, beneficiaries, "
                "transactions, accounts, customers CASCADE"
            )
        )

def test_er_baseline_determinism(tmp_path: Path, superuser_engine: Engine) -> None:
    res = generate_fixtures_v05("er_corpus_v0.5_freeze")
    _clear_data(superuser_engine)
    insert_data(superuser_engine, res)

    try:

        def run_with_seed(seed: str, cwd: str) -> str:
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = seed
            env["PYTHONPATH"] = os.path.abspath("src")
            db_url_str = superuser_engine.url.render_as_string(hide_password=False)
            env["DATABASE_URL"] = db_url_str
            try:
                subprocess_res = subprocess.run(
                    [
                        "uv",
                        "run",
                        "python",
                        "-m",
                        "meridian.fixtures.er_baseline",
                    ],
                    env=env,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return subprocess_res.stdout
            except subprocess.CalledProcessError as e:
                print("STDERR:", e.stderr)
                raise

        d1 = tmp_path / "d1"
        d2 = tmp_path / "d2"
        d1.mkdir()
        d2.mkdir()

        out1 = run_with_seed("1", str(d1))
        out2 = run_with_seed("999", str(d2))

        assert out1 == out2
        assert len(out1) > 0

        parsed = json.loads(out1)
        assert "metadata" in parsed
    finally:
        _clear_data(superuser_engine)


def test_er_baseline_integration(superuser_engine: Engine) -> None:
    res = generate_fixtures_v05("er_corpus_v0.5_freeze")

    # Load data
    _clear_data(superuser_engine)
    insert_data(superuser_engine, res)

    try:
        report = measure_er_baseline(superuser_engine, res)

        # Verify result structure
        assert "metadata" in report
        assert "metrics" in report
        assert "investigation_triggers" in report

        # Verify structural fidelity metrics exist
        metrics = report["metrics"]
        assert "tp" in metrics
        assert "fp" in metrics
        assert "fn" in metrics
        assert "tn" in metrics
        assert "precision" in metrics
        assert "recall" in metrics

        # 1. Full pair universe
        customer_count = 186  # From v0.5 fixture freeze
        expected_total_pairs = customer_count * (customer_count - 1) // 2

        # 2. Confusion-matrix conservation
        tp, fp, fn, tn = metrics["tp"], metrics["fp"], metrics["fn"], metrics["tn"]
        assert tp + fp + fn + tn == expected_total_pairs

        # 3. Negative universe
        # 4. Designed negatives are not complete negative universe
        # The number of true matches is 15. The designed negatives are 5.
        # Negatives should be all pairs - true_match_pairs.
        # So total negatives = 17205 - 15 = 17190.
        total_negatives = expected_total_pairs - 15
        assert tn + fp == total_negatives
        assert total_negatives > 5  # designed_negative_pairs is much smaller

        # 5. An unlisted negative pair predicted by the matcher is still counted as FP
        # This is indirectly tested by the above equations. Any unlisted predicted pair
        # is part of fp.

        # 6. Stratification preserves true-match categories
        stratified = report.get("stratified_recall", {})
        assert any(k.startswith("scope=True") for k in stratified.keys())
        assert any(k.startswith("scope=False") for k in stratified.keys())

        # 7. Abstention accounting remains deterministic
        abstentions = report.get("abstention_reasons", {})
        assert "dob_null" in abstentions
        assert "name_null" in abstentions
        assert "name_empty_after_normalization" in abstentions

        # 8. Baseline remains independent of fixture-construction implementation details
        # The tests do not inspect `manifest.planted_customers` directly to compute TN,
        # they rely on the database and explicit pairs.
    finally:
        _clear_data(superuser_engine)

def test_undefined_precision_recall(superuser_engine: Engine) -> None:
    _clear_data(superuser_engine)
    try:
        # Create 2 customers that do NOT match to ensure TP=0, FP=0, FN=0, TN=1
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO customers (
                        customer_id, full_name, date_of_birth, kyc_risk_rating,
                        source, onboarded_at, created_at, is_synthetic
                    )
                    VALUES
                    (
                        '00000000-0000-0000-0000-000000000001', 'Alice',
                        '1990-01-01', 'LOW', 'test', NOW(), NOW(), true
                    ),
                    (
                        '00000000-0000-0000-0000-000000000002', 'Bob',
                        '1990-01-01', 'LOW', 'test', NOW(), NOW(), true
                    )
                    """
                )
            )

        manifest = {
            "customers": [
                {"customer_id": "00000000-0000-0000-0000-000000000001"},
                {"customer_id": "00000000-0000-0000-0000-000000000002"},
            ],
            "manifest": {
                "er_ground_truth": {
                    "true_match_pairs": [],
                    "designed_negative_pairs": []
                }
            }
        }

        report = measure_er_baseline(superuser_engine, manifest)

        metrics = report["metrics"]
        assert metrics["tp"] + metrics["fp"] == 0
        assert metrics["tp"] + metrics["fn"] == 0

        assert metrics["precision"] is None
        assert metrics["recall"] is None
    finally:
        _clear_data(superuser_engine)

def test_no_second_normalization_implementation() -> None:
    import ast
    from pathlib import Path

    baseline_path = Path("src/meridian/fixtures/er_baseline.py")
    content = baseline_path.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(baseline_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                assert name.name != "unicodedata"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "unicodedata"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"casefold", "normalize", "lower", "upper"}

def test_baseline_measurement_failing_universe(superuser_engine: Engine) -> None:
    _clear_data(superuser_engine)
    try:
        # DB has no customers, but manifest expects 1
        manifest = {
            "customers": [
                {"customer_id": "00000000-0000-0000-0000-000000000001"},
            ],
            "manifest": {
                "er_ground_truth": {
                    "true_match_pairs": [],
                    "designed_negative_pairs": []
                }
            }
        }
        
        import pytest
        with pytest.raises(RuntimeError, match="Database customers do not match manifest customers"):
            measure_er_baseline(superuser_engine, manifest)
    finally:
        _clear_data(superuser_engine)

def test_baseline_unplanned_fp(superuser_engine: Engine) -> None:
    _clear_data(superuser_engine)
    try:
        # Create 2 customers that match perfectly but are not in true_match_pairs
        with superuser_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO customers (
                        customer_id, full_name, date_of_birth, kyc_risk_rating,
                        source, onboarded_at, created_at, is_synthetic
                    )
                    VALUES
                    (
                        '00000000-0000-0000-0000-000000000001', 'Alice',
                        '1990-01-01', 'LOW', 'test', NOW(), NOW(), true
                    ),
                    (
                        '00000000-0000-0000-0000-000000000002', 'Alice',
                        '1990-01-01', 'LOW', 'test', NOW(), NOW(), true
                    )
                    """
                )
            )

        manifest = {
            "customers": [
                {"customer_id": "00000000-0000-0000-0000-000000000001"},
                {"customer_id": "00000000-0000-0000-0000-000000000002"},
            ],
            "manifest": {
                "er_ground_truth": {
                    "true_match_pairs": [],
                    "designed_negative_pairs": []
                }
            }
        }

        report = measure_er_baseline(superuser_engine, manifest)
        
        metrics = report["metrics"]
        assert metrics["fp"] == 1
        assert metrics["tp"] == 0
        
        fp_list = report["fp_list"]
        assert len(fp_list) == 1
        assert fp_list[0]["category"] == "UNPLANNED"
        
        triggers = report["investigation_triggers"]
        assert len(triggers["unplanned_fps"]) == 1
    finally:
        _clear_data(superuser_engine)
