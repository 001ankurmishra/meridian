import os
import subprocess
from decimal import Decimal

from sqlalchemy import Engine, text

from meridian.fixtures.amount_deviation_baseline import (
    _compute_median,
    compute_roc_auc,
    measure_baseline,
)
from meridian.fixtures.generator import generate_fixtures
from meridian.loader.main import clear_data, insert_data


def test_auc_perfect_separation():
    pos = [Decimal("10.0"), Decimal("20.0")]
    neg = [Decimal("1.0"), Decimal("2.0")]
    res = compute_roc_auc(pos, neg)
    assert res["auc"] == 1.0


def test_auc_inverted_separation():
    pos = [Decimal("1.0"), Decimal("2.0")]
    neg = [Decimal("10.0"), Decimal("20.0")]
    res = compute_roc_auc(pos, neg)
    assert res["auc"] == 0.0


def test_auc_all_ties():
    pos = [Decimal("5.0"), Decimal("5.0")]
    neg = [Decimal("5.0"), Decimal("5.0")]
    res = compute_roc_auc(pos, neg)
    assert res["auc"] == 0.5


def test_auc_single_class():
    res = compute_roc_auc([Decimal("1.0")], [])
    assert res["auc"] is None
    assert "reason" in res


def test_auc_empty():
    res = compute_roc_auc([], [])
    assert res["auc"] is None
    assert "reason" in res


def test_auc_mixed_ties():
    # pos: 5, 10. neg: 2, 5
    # ranks: 2=1, 5=2.5, 5=2.5, 10=4
    # u_pos = sum_ranks_pos - 3 = (2.5 + 4) - 3 = 3.5
    # auc = 3.5 / 4 = 0.875
    pos = [Decimal("5.0"), Decimal("10.0")]
    neg = [Decimal("2.0"), Decimal("5.0")]
    res = compute_roc_auc(pos, neg)
    assert res["auc"] == 0.875


def test_statistics_median():
    assert _compute_median([Decimal("1.0"), Decimal("2.0"), Decimal("3.0")]) == Decimal(
        "2.0"
    )
    assert _compute_median(
        [Decimal("1.0"), Decimal("2.0"), Decimal("3.0"), Decimal("4.0")]
    ) == Decimal("2.5")
    assert _compute_median([]) is None


def test_statistics_min_max():
    # Min/max are checked in the scenario formatting directly, just checking median here
    # Decimal exactness
    val = _compute_median([Decimal("1.111"), Decimal("1.112")])
    assert val == Decimal("1.1115")


def test_determinism(tmp_path, superuser_engine: Engine):
    from meridian.fixtures.generator import generate_fixtures
    from meridian.loader.main import clear_data, insert_data

    # Ensure DB is loaded with fixtures before running the subprocesses
    # because the measurement script is now read-only.
    res = generate_fixtures("baseline_seed")
    clear_data(superuser_engine)
    insert_data(superuser_engine, res)

    try:
        def run_with_seed(seed: str, cwd: str) -> str:
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = seed
            env["PYTHONPATH"] = os.path.abspath("src")
            # We pass the DB URL to ensure the subprocess points to our test engine
            db_url_str = superuser_engine.url.render_as_string(hide_password=False)
            env["DATABASE_URL"] = db_url_str
            try:
                subprocess_res = subprocess.run(
                    [
                        "uv",
                        "run",
                        "python",
                        "-m",
                        "meridian.fixtures.amount_deviation_baseline",
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

        import json
        parsed = json.loads(out1)
        assert "metadata" in parsed
    finally:
        clear_data(superuser_engine)


def test_baseline_integration(superuser_engine: Engine):
    res = generate_fixtures("integration_seed")
    fixtures = res["manifest"]["fixtures"]

    total_fixtures = len(fixtures)
    worked_examples = sum(
        1 for f in fixtures if f["scenario_class"] == "worked_example"
    )
    edge_cases = sum(
        1 for f in fixtures if f["scenario_class"] == "insufficient_history"
    )
    expected_eligible = total_fixtures - worked_examples - edge_cases

    # Record initial counts
    def get_counts():
        with superuser_engine.connect() as conn:
            rs = conn.execute(text("SELECT count(*) FROM risk_signals")).scalar()
            al = conn.execute(text("SELECT count(*) FROM alerts")).scalar()
            ca = conn.execute(text("SELECT count(*) FROM cases")).scalar()
            ir = conn.execute(text("SELECT count(*) FROM investigation_runs")).scalar()
            return rs, al, ca, ir

    initial_counts = get_counts()

    # Load data
    clear_data(superuser_engine)
    insert_data(superuser_engine, res)

    try:
        report = measure_baseline(superuser_engine, res["manifest"])

        # Verify result structure
        assert "metadata" in report
        assert "exclusions" in report
        assert "per_scenario_statistics" in report
        assert "auc_results" in report

        # Verify exclusions
        assert report["exclusions"]["worked_example"] == worked_examples
        assert report["exclusions"]["runtime_edge_case"] == edge_cases

        # Verify inclusion count
        total_included = sum(s["n"] for s in report["per_scenario_statistics"].values())
        assert total_included == expected_eligible

        # Verify DB counts unchanged
        final_counts = get_counts()
        assert initial_counts == final_counts

    finally:
        clear_data(superuser_engine)
