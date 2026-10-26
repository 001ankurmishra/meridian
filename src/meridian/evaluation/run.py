"""Run existing synthetic baselines in the guarded disposable test database."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine

from meridian.evaluation.policy import EVALUATION_DIR, validate_freeze
from meridian.fixtures.amount_deviation_baseline import canonical_json, measure_baseline
from meridian.fixtures.er_baseline import measure_er_baseline
from meridian.fixtures.generator import generate_fixtures_v02
from meridian.fixtures.generator_v03 import generate_fixtures_v03
from meridian.fixtures.generator_v04 import generate_fixtures_v04
from meridian.fixtures.generator_v05 import generate_fixtures_v05
from meridian.fixtures.graph_structure_baseline import measure_graph_baseline
from meridian.fixtures.sanctions_baseline import measure_sanctions_baseline
from meridian.fixtures.signal_baseline import measure_signal_baselines
from meridian.loader.main import clear_data, insert_data
from meridian.testing.guard import verify_test_database_safety


def recorded_policy() -> dict[str, Any]:
    """Reuse immutable measured results; never rerun or tune HELDOUT."""
    digest = validate_freeze()
    receipt_path = EVALUATION_DIR / "policy_retrieval_eval_v1.heldout-receipt.json"
    if not receipt_path.exists():
        return {"status": "NOT PERFORMED", "frozen_sha256": digest}
    receipt = json.loads(receipt_path.read_text())
    result_path = EVALUATION_DIR / "policy_retrieval_eval_v1.heldout.json"
    raw = result_path.read_bytes()
    if (
        receipt["status"] != "COMPLETED"
        or receipt["frozen_sha256"] != digest
        or hashlib.sha256(raw).hexdigest() != receipt["result_sha256"]
    ):
        raise ValueError("Recorded HELDOUT evidence does not match its receipt.")
    return {
        "status": "RECORDED_RESULT_REUSED",
        "sha256": receipt["result_sha256"],
        "result": json.loads(raw),
    }


def run() -> dict[str, Any]:
    # This check precedes every connection and fixture mutation.
    identity, _ = verify_test_database_safety()
    maintenance = create_engine(identity.validated_url, hide_parameters=True)
    loader = create_engine(os.environ["LOADER_DATABASE_URL"], hide_parameters=True)
    app = create_engine(os.environ["APP_DATABASE_URL"], hide_parameters=True)
    results: dict[str, Any] = {
        "tier": "PROTOTYPE",
        "human_comparison": "NOT PERFORMED",
        "limitations": (
            "Synthetic fixture fidelity only. No production effectiveness claim."
        ),
    }
    try:
        for name, generator, measure, seed in (
            (
                "amount_deviation",
                generate_fixtures_v02,
                measure_baseline,
                "baseline_seed",
            ),
            (
                "transaction_signals",
                generate_fixtures_v03,
                measure_signal_baselines,
                "baseline_seed",
            ),
            (
                "graph_structure",
                generate_fixtures_v04,
                measure_graph_baseline,
                "baseline_seed",
            ),
            (
                "entity_resolution",
                generate_fixtures_v05,
                measure_er_baseline,
                "er_corpus_v0.5_freeze",
            ),
        ):
            clear_data(maintenance)  # Also refuses any existing downstream alerts.
            fixture = generator(seed)
            insert_data(loader, fixture)
            payload = fixture if name == "entity_resolution" else fixture["manifest"]
            results[name] = measure(app, payload)
        results["sanctions"] = measure_sanctions_baseline()
        results["policy"] = recorded_policy()
        return results
    finally:
        # Source fixtures are disposable; do not leave mixed-version evaluation data.
        try:
            clear_data(maintenance)
        finally:
            app.dispose()
            loader.dispose()
            maintenance.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite evaluation evidence.")
    result = run()
    with args.output.open("x") as output:
        output.write(canonical_json(result) + "\n")
    print(f"Evaluation evidence written to {args.output}")


if __name__ == "__main__":
    main()
