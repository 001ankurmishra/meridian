import os
import subprocess

from sqlalchemy import Engine

from meridian.fixtures.generator_v04 import generate_fixtures_v04
from meridian.fixtures.graph_structure_baseline import measure_graph_baseline
from meridian.loader.main import clear_data, insert_data


def test_determinism(tmp_path, superuser_engine: Engine):
    res = generate_fixtures_v04("baseline_seed")
    clear_data(superuser_engine)
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
                        "meridian.fixtures.graph_structure_baseline",
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
    res = generate_fixtures_v04("integration_seed")

    # Load data
    clear_data(superuser_engine)
    insert_data(superuser_engine, res)

    try:
        report = measure_graph_baseline(superuser_engine, res["manifest"])

        # Verify result structure
        assert "metadata" in report
        assert "exclusions" in report
        assert "signals" in report
        assert "directed_cycle" in report["signals"]
        assert "outbound_chain_depth" in report["signals"]

        # Verify structural fidelity metrics exist
        cycle_fid = report["signals"]["directed_cycle"]["structural_fidelity"]
        assert "exact_match_rate" in cycle_fid
        assert "confusion_matrix" in cycle_fid
        assert cycle_fid["n_applicable"] > 0

        chain_fid = report["signals"]["outbound_chain_depth"]["structural_fidelity"]
        assert "exact_match_rate" in chain_fid
        assert "mean_absolute_error" in chain_fid
        assert chain_fid["n_applicable"] > 0

    finally:
        clear_data(superuser_engine)
